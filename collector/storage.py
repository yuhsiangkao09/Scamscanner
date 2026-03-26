from __future__ import annotations

import json
import re
from dataclasses import asdict
from hashlib import sha1
from pathlib import Path
from typing import Any

from common import DATA_DIR

from .types import (
    ArtifactManifest,
    CollectionRequest,
    CollectionStatus,
    CollectedPage,
    CollectorTier,
    FailureReason,
)


def sanitize_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return sanitized.strip("._-") or "sample"


def bundle_root() -> Path:
    return DATA_DIR / "collector_v2"


class BundlePaths:
    def __init__(self, bundle_dir: Path):
        self.bundle_dir = bundle_dir
        self.request_path = bundle_dir / "request.json"
        self.manifest_path = bundle_dir / "manifest.json"
        self.http_raw_path = bundle_dir / "http_raw.html"
        self.browser_final_path = bundle_dir / "browser_final.html"
        self.final_path = bundle_dir / "final.html"
        self.headers_path = bundle_dir / "headers.json"
        self.redirects_path = bundle_dir / "redirects.json"
        self.network_path = bundle_dir / "network.jsonl"
        self.screenshot_path = bundle_dir / "screenshot.png"
        self.trace_path = bundle_dir / "trace.zip"


def build_cache_key(request: CollectionRequest, *, versions: dict[str, Any]) -> str:
    payload = {
        "url": request.url.strip(),
        "purpose": request.purpose.value,
        "collection_mode": request.collection_mode.value,
        "artifact_profile": request.artifact_profile.value,
        "browser_tier": request.browser_tier.value,
        "proxy": request.proxy or "",
        "locale": request.locale,
        "timezone": request.timezone,
        "fingerprint_seed": request.fingerprint_seed,
        "browser_executable": request.browser_executable or "",
        "versions": versions,
    }
    digest = sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    host = sanitize_component(request.url.split("//", 1)[-1].split("/", 1)[0])
    return f"bundle+{request.collection_mode.value}+{host}+{digest}"


def bundle_paths_for_cache_key(cache_key: str) -> BundlePaths:
    bundle_dir = bundle_root() / cache_key
    bundle_dir.mkdir(parents=True, exist_ok=True)
    return BundlePaths(bundle_dir)


def request_to_dict(request: CollectionRequest) -> dict[str, Any]:
    payload = asdict(request)
    if payload["browser_user_data_root"] is not None:
        payload["browser_user_data_root"] = str(payload["browser_user_data_root"])
    payload["purpose"] = request.purpose.value
    payload["collection_mode"] = request.collection_mode.value
    payload["artifact_profile"] = request.artifact_profile.value
    payload["cache_policy"] = request.cache_policy.value
    payload["browser_tier"] = request.browser_tier.value
    return payload


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cached_page(paths: BundlePaths) -> CollectedPage | None:
    if not paths.manifest_path.exists() or not paths.final_path.exists():
        return None
    payload = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    final_html = paths.final_path.read_text(encoding="utf-8", errors="ignore")
    raw_html = paths.http_raw_path.read_text(encoding="utf-8", errors="ignore") if paths.http_raw_path.exists() else None
    browser_html = (
        paths.browser_final_path.read_text(encoding="utf-8", errors="ignore")
        if paths.browser_final_path.exists()
        else None
    )
    return CollectedPage(
        requested_url=str(payload["request"]["url"]),
        final_url=payload.get("final_url"),
        final_html=final_html,
        tier_used=CollectorTier(payload["tier_used"]),
        status=CollectionStatus(payload["status"]),
        reason=FailureReason(payload["reason"]),
        artifact_dir=paths.bundle_dir,
        manifest_path=paths.manifest_path,
        http_status=payload.get("http_status"),
        redirect_chain=list(payload.get("redirect_chain") or []),
        raw_html=raw_html,
        browser_html=browser_html,
        fallback_reason=FailureReason(payload["fallback_reason"]) if payload.get("fallback_reason") else None,
        signals=dict(payload.get("signals") or {}),
        timings=dict(payload.get("timings") or {}),
        network_summary=dict(payload.get("network_summary") or {}),
        runtime_features=list(payload.get("runtime_features") or []),
        runtime_feature_mask=list(payload.get("runtime_feature_mask") or []),
        provenance=dict(payload.get("provenance") or {}),
        cache_key=str(payload.get("cache_key") or paths.bundle_dir.name),
        error_message=payload.get("error_message"),
    )


def persist_collected_page(
    *,
    paths: BundlePaths,
    request: CollectionRequest,
    page: CollectedPage,
    manifest: ArtifactManifest,
    headers: dict[str, Any] | None = None,
    network_events: list[dict[str, Any]] | None = None,
) -> CollectedPage:
    write_json(paths.request_path, request_to_dict(request))
    if page.raw_html is not None:
        paths.http_raw_path.write_text(page.raw_html, encoding="utf-8", errors="ignore")
    if page.browser_html is not None:
        paths.browser_final_path.write_text(page.browser_html, encoding="utf-8", errors="ignore")
    paths.final_path.write_text(page.final_html, encoding="utf-8", errors="ignore")
    if headers:
        write_json(paths.headers_path, headers)
    if page.redirect_chain:
        write_json(paths.redirects_path, page.redirect_chain)
    if network_events:
        lines = "\n".join(json.dumps(event, ensure_ascii=False) for event in network_events)
        paths.network_path.write_text(lines, encoding="utf-8")
    manifest_payload = {
        "request": manifest.request,
        "status": manifest.status.value if hasattr(manifest.status, "value") else manifest.status,
        "reason": manifest.reason.value if hasattr(manifest.reason, "value") else manifest.reason,
        "tier_used": manifest.tier_used.value if hasattr(manifest.tier_used, "value") else manifest.tier_used,
        "fallback_reason": (
            manifest.fallback_reason.value if hasattr(manifest.fallback_reason, "value") else manifest.fallback_reason
        ),
        "http_status": manifest.http_status,
        "final_url": manifest.final_url,
        "redirect_chain": manifest.redirect_chain,
        "signals": manifest.signals,
        "timings": manifest.timings,
        "network_summary": manifest.network_summary,
        "provenance": manifest.provenance,
        "artifact_paths": {
            "request": str(paths.request_path),
            "manifest": str(paths.manifest_path),
            "http_raw": str(paths.http_raw_path) if page.raw_html is not None else None,
            "browser_final": str(paths.browser_final_path) if page.browser_html is not None else None,
            "final": str(paths.final_path),
            "headers": str(paths.headers_path) if headers else None,
            "redirects": str(paths.redirects_path) if page.redirect_chain else None,
            "network": str(paths.network_path) if network_events else None,
            "screenshot": str(paths.screenshot_path) if paths.screenshot_path.exists() else None,
            "trace": str(paths.trace_path) if paths.trace_path.exists() else None,
        },
        "runtime_features": manifest.runtime_features,
        "runtime_feature_mask": manifest.runtime_feature_mask,
        "cache_key": manifest.cache_key,
        "error_message": page.error_message,
    }
    write_json(paths.manifest_path, manifest_payload)
    page.manifest_path = paths.manifest_path
    return page
