from __future__ import annotations

import atexit
import asyncio
from typing import Any

from .browser import BrowserPool, fingerprint_chromium_version, patchright_ready
from .http import fetch_html, rnet_ready
from .runtime import (
    analyze_html,
    build_runtime_feature_vector,
    classify_final_status,
    extract_redirect_target,
    signals_to_dict,
    should_escalate_to_browser,
)
from .storage import build_cache_key, bundle_paths_for_cache_key, load_cached_page, persist_collected_page, request_to_dict
from .types import (
    ArtifactManifest,
    CachePolicy,
    CollectionMode,
    CollectionRequest,
    CollectionStatus,
    CollectedPage,
    CollectorTier,
    FailureReason,
)


class CollectorService:
    def __init__(self):
        self.browser_pool = BrowserPool()

    def versions(self, request: CollectionRequest) -> dict[str, Any]:
        rnet_ok, rnet_version = rnet_ready()
        patchright_ok, patchright_version = patchright_ready()
        return {
            "rnet_version": rnet_version if rnet_ok else None,
            "patchright_version": patchright_version if patchright_ok else None,
            "fingerprint_chromium_version": fingerprint_chromium_version(request.browser_executable),
            "http_emulation": "Chrome144",
            "browser_tier": request.browser_tier.value,
        }

    def collect_sync(self, request: CollectionRequest) -> CollectedPage:
        versions = self.versions(request)
        cache_key = build_cache_key(request, versions=versions)
        paths = bundle_paths_for_cache_key(cache_key)
        if request.cache_policy == CachePolicy.REUSE:
            cached = load_cached_page(paths)
            if cached is not None:
                return cached

        raw_result = None
        raw_signals = None
        final_html = ""
        final_url = None
        http_status = None
        headers = None
        tier_used = CollectorTier.RNET
        fallback_reason = None
        network_summary: dict[str, Any] = {}
        network_events: list[dict[str, Any]] = []
        timings: dict[str, Any] = {}
        browser_html = None
        error_message = None

        browser_requested = request.collection_mode == CollectionMode.BROWSER_REQUIRED

        if request.collection_mode != CollectionMode.BROWSER_REQUIRED:
            raw_result = fetch_html(request.url, request)
            final_url = raw_result.final_url
            http_status = raw_result.status_code
            headers = raw_result.headers
            final_html = raw_result.text
            if raw_result.text:
                raw_signals = analyze_html(raw_result.text)
                redirect_target = extract_redirect_target(raw_result.text, raw_result.final_url or request.url)
                if redirect_target and redirect_target != (raw_result.final_url or request.url):
                    redirected_request = CollectionRequest(
                        url=redirect_target,
                        purpose=request.purpose,
                        collection_mode=CollectionMode.RNET_ONLY,
                        artifact_profile=request.artifact_profile,
                        cache_policy=CachePolicy.OFF,
                        proxy=request.proxy,
                        locale=request.locale,
                        timezone=request.timezone,
                        fingerprint_seed=request.fingerprint_seed,
                        browser_tier=request.browser_tier,
                        browser_executable=request.browser_executable,
                        browser_user_data_root=request.browser_user_data_root,
                        timeout_sec=request.timeout_sec,
                        headless=request.headless,
                    )
                    redirected_raw = fetch_html(redirect_target, redirected_request)
                    if redirected_raw.text.strip():
                        raw_result = redirected_raw
                        final_url = redirected_raw.final_url
                        http_status = redirected_raw.status_code
                        headers = redirected_raw.headers
                        final_html = redirected_raw.text
                        raw_signals = analyze_html(redirected_raw.text)
            if raw_result.error_message:
                error_message = raw_result.error_message
                fallback_reason = FailureReason.FETCH_ERROR
            elif raw_signals is not None:
                fallback_reason = should_escalate_to_browser(
                    status_code=raw_result.status_code,
                    content_type=raw_result.content_type,
                    signals=raw_signals,
                    html=raw_result.text,
                )
        else:
            fallback_reason = FailureReason.BROWSER_REQUIRED

        if request.collection_mode == CollectionMode.RNET_ONLY:
            fallback_reason = None

        if request.collection_mode == CollectionMode.BROWSER_REQUIRED or (
            request.collection_mode == CollectionMode.AUTO and fallback_reason is not None
        ):
            try:
                session = self.browser_pool.get_session(request)
                browser_result = session.collect(
                    request.url,
                    screenshot_path=paths.screenshot_path if request.artifact_profile.value == "rich" else None,
                    trace_path=paths.trace_path if request.artifact_profile.value == "rich" else None,
                    rich=request.artifact_profile.value == "rich",
                )
                browser_html = browser_result.html
                final_html = browser_result.html
                final_url = browser_result.final_url
                http_status = browser_result.status_code if browser_result.status_code is not None else http_status
                network_summary = browser_result.network_summary
                network_events = browser_result.network_events
                timings = browser_result.timings
                tier_used = request.browser_tier
            except Exception as exc:  # noqa: BLE001
                error_message = str(exc)
                if raw_result is None or not raw_result.text:
                    final_html = ""
                tier_used = CollectorTier.RNET
                if request.collection_mode == CollectionMode.BROWSER_REQUIRED and not final_html:
                    fallback_reason = FailureReason.BROWSER_UNAVAILABLE

        final_signals = analyze_html(final_html)
        status, reason = classify_final_status(
            status_code=http_status,
            content_type=(headers or {}).get("content-type") if headers else None,
            html=final_html,
            signals=final_signals,
        )
        if error_message and not final_html:
            status = (
                CollectionStatus.BROWSER_FAILED
                if request.collection_mode == CollectionMode.BROWSER_REQUIRED
                else CollectionStatus.FETCH_FAILED
            )
            reason = fallback_reason or FailureReason.FETCH_ERROR

        runtime_vector = build_runtime_feature_vector(
            raw_signals=raw_signals,
            final_signals=final_signals,
            status_code=http_status,
            raw_status_code=raw_result.status_code if raw_result is not None else None,
            redirect_count=len(raw_result.history if raw_result is not None else []),
            browser_used=tier_used == request.browser_tier,
            browser_requested=browser_requested,
            network_summary=network_summary,
            timings=timings,
            final_status=status,
        )

        page = CollectedPage(
            requested_url=request.url,
            final_url=final_url,
            final_html=final_html,
            tier_used=tier_used,
            status=status,
            reason=reason,
            artifact_dir=paths.bundle_dir,
            manifest_path=paths.manifest_path,
            http_status=http_status,
            redirect_chain=list(raw_result.history if raw_result is not None else []),
            raw_html=raw_result.text if raw_result is not None and raw_result.text else None,
            browser_html=browser_html,
            fallback_reason=fallback_reason,
            signals={
                "raw": signals_to_dict(raw_signals, status_code=raw_result.status_code) if raw_signals is not None else None,
                "final": signals_to_dict(final_signals, status_code=http_status),
            },
            timings=timings,
            network_summary=network_summary,
            runtime_features=runtime_vector.values,
            runtime_feature_mask=runtime_vector.mask,
            provenance={
                "versions": versions,
                "http_backend": raw_result.backend if raw_result is not None else None,
            },
            cache_key=cache_key,
            error_message=error_message,
        )
        manifest = ArtifactManifest(
            request=request_to_dict(request),
            status=status,
            reason=reason,
            tier_used=tier_used,
            fallback_reason=fallback_reason,
            http_status=http_status,
            final_url=final_url,
            redirect_chain=page.redirect_chain,
            signals=page.signals,
            timings=timings,
            network_summary=network_summary,
            provenance=page.provenance,
            runtime_features=page.runtime_features,
            runtime_feature_mask=page.runtime_feature_mask,
            cache_key=cache_key,
        )
        persist_collected_page(
            paths=paths,
            request=request,
            page=page,
            manifest=manifest,
            headers=headers,
            network_events=network_events,
        )
        return page

    async def collect(self, request: CollectionRequest) -> CollectedPage:
        return await asyncio.to_thread(self.collect_sync, request)

    def close(self) -> None:
        self.browser_pool.close()

    def configure(self, *, browser_workers: int | None = None) -> None:
        self.browser_pool.configure(max_sessions_per_key=browser_workers)


_SERVICE = CollectorService()
atexit.register(_SERVICE.close)


def collect_sync(request: CollectionRequest) -> CollectedPage:
    return _SERVICE.collect_sync(request)


async def collect(request: CollectionRequest) -> CollectedPage:
    return await _SERVICE.collect(request)


def collector_health(request: CollectionRequest | None = None) -> dict[str, Any]:
    req = request or CollectionRequest(url="about:blank")
    rnet_ok, rnet_version = rnet_ready()
    patch_ok, patch_version = patchright_ready()
    fp_version = fingerprint_chromium_version(req.browser_executable)
    return {
        "rnet_ready": rnet_ok,
        "rnet_version": rnet_version,
        "browser_ready": patch_ok and bool(req.browser_executable),
        "patchright_version": patch_version,
        "fingerprint_chromium_version": fp_version,
        "browser_executable": req.browser_executable,
    }


def configure_collector(*, browser_workers: int | None = None) -> None:
    _SERVICE.configure(browser_workers=browser_workers)
