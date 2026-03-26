from __future__ import annotations

import contextlib
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import DATA_DIR

from .types import CollectionRequest


def patchright_ready() -> tuple[bool, str | None]:
    try:
        import patchright  # type: ignore
    except ModuleNotFoundError:
        return False, None
    return True, getattr(patchright, "__version__", None)


def fingerprint_chromium_version(executable_path: str | None) -> str | None:
    if not executable_path:
        return None
    path = Path(executable_path)
    version_pattern = re.compile(r"\d+\.\d+\.\d+\.\d+")
    for part in reversed(path.parts):
        match = version_pattern.fullmatch(part)
        if match:
            return match.group(0)
    parent = path.parent
    try:
        version_dirs = sorted(
            [child.name for child in parent.iterdir() if child.is_dir() and version_pattern.fullmatch(child.name)],
            reverse=True,
        )
    except Exception:  # noqa: BLE001
        version_dirs = []
    if version_dirs:
        return version_dirs[0]
    return None


def _fingerprint_args(request: CollectionRequest) -> list[str]:
    locale = request.locale or "en-US"
    accept_lang = ",".join(dict.fromkeys(item.strip() for item in locale.split(",") if item.strip())) or "en-US"
    return [
        f"--fingerprint={request.fingerprint_seed}",
        "--fingerprint-brand=Chrome",
        "--fingerprint-brand-version=144",
        "--disable-non-proxied-udp",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-search-engine-choice-screen",
        "--disable-features=Translate,MediaRouter,OptimizationHints,AutofillServerCommunication,PasswordManagerOnboarding",
        f"--lang={locale}",
        f"--accept-lang={accept_lang}",
        f"--timezone={request.timezone}",
    ]


def _wait_for_dom_stability(page, timeout_sec: int, settle_interval_ms: int = 250, stable_observations: int = 3) -> int:
    deadline = time.monotonic() + 1.5
    last_signature: tuple[str, int, int] | None = None
    stable_count = 0
    with contextlib.suppress(Exception):
        page.wait_for_selector("body", state="attached", timeout=min(timeout_sec * 1000, 5_000))
    while time.monotonic() < deadline:
        try:
            ready_state, tag_count, text_count = page.evaluate(
                """() => {
                    const body = document.body;
                    const text = body ? body.innerText || "" : "";
                    return [document.readyState, document.getElementsByTagName('*').length, text.trim().length];
                }"""
            )
        except Exception:  # noqa: BLE001
            break
        signature = (ready_state, int(tag_count), int(text_count))
        if ready_state in {"interactive", "complete"} and signature == last_signature:
            stable_count += 1
            if stable_count >= stable_observations:
                break
        else:
            last_signature = signature
            stable_count = 1 if ready_state in {"interactive", "complete"} else 0
        page.wait_for_timeout(settle_interval_ms)
    return int((1.5 - max(0.0, deadline - time.monotonic())) * 1000)


@dataclass(slots=True)
class BrowserCollectionResult:
    html: str
    final_url: str
    status_code: int | None
    network_summary: dict[str, Any]
    network_events: list[dict[str, Any]]
    timings: dict[str, Any]


class PatchrightBrowserSession:
    def __init__(self, request: CollectionRequest, *, profile_key: str):
        self.request = request
        self.profile_key = profile_key
        self._playwright_cm = None
        self._context = None
        self._lock = threading.RLock()
        self._semaphore = threading.Semaphore(4)

    def _user_data_dir(self) -> Path:
        root = self.request.browser_user_data_root or (DATA_DIR / "collector_v2" / "browser_profiles")
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{self.profile_key}+pid{os.getpid()}"

    def _launch(self) -> None:
        if self._context is not None:
            return
        ready, _ = patchright_ready()
        if not ready:
            raise RuntimeError("Patchright is not installed. Install collector browser dependencies first.")
        if not self.request.browser_executable:
            raise RuntimeError("fingerprint-chromium executable path is required for chromium_hardened collection.")
        from patchright.sync_api import sync_playwright  # type: ignore

        args = _fingerprint_args(self.request)
        self._playwright_cm = sync_playwright()
        playwright = self._playwright_cm.__enter__()
        self._context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._user_data_dir()),
            executable_path=self.request.browser_executable,
            headless=self.request.headless,
            no_viewport=True,
            args=args,
        )

    def close(self) -> None:
        with contextlib.suppress(Exception):
            if self._context is not None:
                self._context.close()
        self._context = None
        if self._playwright_cm is not None:
            with contextlib.suppress(Exception):
                self._playwright_cm.__exit__(None, None, None)
            self._playwright_cm = None

    def _acquire_page(self):
        existing_pages = list(getattr(self._context, "pages", []) or [])
        page = existing_pages[0] if existing_pages else self._context.new_page()
        for extra_page in existing_pages[1:]:
            with contextlib.suppress(Exception):
                extra_page.close()
        return page

    def collect(self, url: str, *, screenshot_path: Path | None = None, trace_path: Path | None = None, rich: bool = True) -> BrowserCollectionResult:
        with self._semaphore:
            with self._lock:
                self._launch()
                page = self._acquire_page()
                network_events: list[dict[str, Any]] = []
                summary = {
                    "request_total": 0,
                    "request_failed": 0,
                    "xhr_fetch_total": 0,
                    "script_request_total": 0,
                    "websocket_seen": False,
                }

                def on_request(req):
                    summary["request_total"] += 1
                    if req.resource_type in {"xhr", "fetch"}:
                        summary["xhr_fetch_total"] += 1
                    if req.resource_type == "script":
                        summary["script_request_total"] += 1
                    if rich:
                        network_events.append(
                            {"event": "request", "url": req.url, "method": req.method, "resource_type": req.resource_type}
                        )

                def on_response(resp):
                    if rich:
                        with contextlib.suppress(Exception):
                            network_events.append(
                                {
                                    "event": "response",
                                    "url": resp.url,
                                    "status": resp.status,
                                    "headers": resp.headers,
                                }
                            )

                def on_failed(req):
                    summary["request_failed"] += 1
                    if rich:
                        network_events.append({"event": "request_failed", "url": req.url, "resource_type": req.resource_type})

                def on_websocket(ws):
                    summary["websocket_seen"] = True
                    if rich:
                        network_events.append({"event": "websocket", "url": ws.url})

                page.on("request", on_request)
                page.on("response", on_response)
                page.on("requestfailed", on_failed)
                page.on("websocket", on_websocket)

                tracing_started = False
                if trace_path is not None and rich and hasattr(self._context, "tracing"):
                    with contextlib.suppress(Exception):
                        self._context.tracing.start(screenshots=True, snapshots=True)
                        tracing_started = True

                try:
                    started = time.perf_counter()
                    response = page.goto(url, wait_until="domcontentloaded", timeout=self.request.timeout_sec * 1000)
                    with contextlib.suppress(Exception):
                        page.wait_for_load_state("load", timeout=min(self.request.timeout_sec * 1000, 8_000))
                    settle_ms = _wait_for_dom_stability(page, self.request.timeout_sec)
                    html = page.content()
                    nav_entry = None
                    with contextlib.suppress(Exception):
                        nav_entry = page.evaluate(
                            """() => {
                                const nav = performance.getEntriesByType('navigation')[0];
                                if (!nav) return null;
                                return {
                                    navigation_ms: nav.duration,
                                    domcontentloaded_ms: nav.domContentLoadedEventEnd,
                                    load_ms: nav.loadEventEnd
                                };
                            }"""
                        )
                    timings = {
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "settle_ms": settle_ms,
                    }
                    if isinstance(nav_entry, dict):
                        timings.update(nav_entry)
                    if screenshot_path is not None and rich:
                        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                        with contextlib.suppress(Exception):
                            page.screenshot(path=str(screenshot_path), full_page=True)
                    return BrowserCollectionResult(
                        html=html,
                        final_url=page.url,
                        status_code=response.status if response else None,
                        network_summary=summary,
                        network_events=network_events,
                        timings=timings,
                    )
                finally:
                    if tracing_started and trace_path is not None:
                        challenge_like = any(event.get("event") == "request_failed" for event in network_events)
                        if challenge_like:
                            with contextlib.suppress(Exception):
                                trace_path.parent.mkdir(parents=True, exist_ok=True)
                                self._context.tracing.stop(path=str(trace_path))
                        else:
                            with contextlib.suppress(Exception):
                                self._context.tracing.stop()
                    with contextlib.suppress(Exception):
                        if page != (list(getattr(self._context, "pages", []) or [])[:1] or [page])[0]:
                            page.close()


class BrowserPool:
    def __init__(self, max_sessions_per_key: int = 1):
        self.max_sessions_per_key = max(1, max_sessions_per_key)
        self._sessions: dict[tuple[str, ...], list[PatchrightBrowserSession]] = {}
        self._next_index: dict[tuple[str, ...], int] = {}
        self._lock = threading.RLock()

    def configure(self, *, max_sessions_per_key: int | None = None) -> None:
        if max_sessions_per_key is not None:
            self.max_sessions_per_key = max(1, max_sessions_per_key)

    def session_key(self, request: CollectionRequest) -> tuple[str, ...]:
        return (
            request.browser_executable or "",
            request.proxy or "",
            request.locale,
            request.timezone,
            str(request.fingerprint_seed),
        )

    def get_session(self, request: CollectionRequest) -> PatchrightBrowserSession:
        key = self.session_key(request)
        with self._lock:
            sessions = self._sessions.setdefault(key, [])
            if not sessions or len(sessions) < self.max_sessions_per_key:
                worker_id = len(sessions)
                profile_key = "profile+" + "+".join(re.sub(r"[^A-Za-z0-9._-]+", "_", item or "none") for item in key)
                profile_key = f"{profile_key}+worker{worker_id}"
                sessions.append(PatchrightBrowserSession(request, profile_key=profile_key))
            next_index = self._next_index.get(key, 0) % len(sessions)
            self._next_index[key] = next_index + 1
            return sessions[next_index]

    def close(self) -> None:
        with self._lock:
            for session_group in self._sessions.values():
                for session in session_group:
                    session.close()
            self._sessions.clear()
            self._next_index.clear()
