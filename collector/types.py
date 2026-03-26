from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


RUNTIME_FEATURE_NAMES = (
    "final_status_family",
    "raw_status_family",
    "redirect_count",
    "raw_text_chars_log",
    "final_text_chars_log",
    "raw_tag_count_log",
    "final_tag_count_log",
    "raw_script_count_log",
    "final_script_count_log",
    "raw_form_count",
    "final_form_count",
    "raw_input_count",
    "final_input_count",
    "raw_iframe_count",
    "final_iframe_count",
    "final_meta_refresh",
    "raw_meta_refresh",
    "anti_bot_signal_count",
    "challenge_suspected",
    "blocked_status",
    "browser_used",
    "browser_requested",
    "request_total_log",
    "request_failed_log",
    "xhr_fetch_log",
    "script_request_log",
    "websocket_seen",
    "nav_time_log",
    "domcontentloaded_time_log",
    "load_time_log",
    "settle_time_log",
    "raw_final_text_delta_log",
)
RUNTIME_FEATURE_DIM = len(RUNTIME_FEATURE_NAMES)


class CollectionMode(str, Enum):
    AUTO = "auto"
    RNET_ONLY = "rnet_only"
    BROWSER_REQUIRED = "browser_required"


class CollectorTier(str, Enum):
    RNET = "rnet"
    CHROMIUM_HARDENED = "chromium_hardened"


class ArtifactProfile(str, Enum):
    RICH = "rich"
    MINIMAL = "minimal"


class CachePolicy(str, Enum):
    REUSE = "reuse"
    REFRESH = "refresh"
    OFF = "off"


class CollectionPurpose(str, Enum):
    LIVE_INFERENCE = "live_inference"
    BACKFILL = "backfill"
    REBUILD = "rebuild"
    DATASET_FETCH = "dataset_fetch"


class CollectionStatus(str, Enum):
    SUCCESS = "success"
    CHALLENGE = "challenge"
    BLOCKED = "blocked"
    NON_HTML = "non_html"
    BROWSER_FAILED = "browser_failed"
    FETCH_FAILED = "fetch_failed"
    PREPROCESS_FAILED = "preprocess_failed"


class FailureReason(str, Enum):
    NONE = "none"
    EMPTY_BODY = "empty_body"
    JS_SHELL = "js_shell"
    CHALLENGE = "challenge"
    BLOCKED_STATUS = "blocked_status"
    NON_HTML = "non_html"
    RNET_UNAVAILABLE = "rnet_unavailable"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    BROWSER_REQUIRED = "browser_required"
    FETCH_ERROR = "fetch_error"
    PREPROCESS_ERROR = "preprocess_error"


@dataclass(slots=True, frozen=True)
class CollectionRequest:
    url: str
    purpose: CollectionPurpose = CollectionPurpose.LIVE_INFERENCE
    collection_mode: CollectionMode = CollectionMode.AUTO
    artifact_profile: ArtifactProfile = ArtifactProfile.RICH
    cache_policy: CachePolicy = CachePolicy.REUSE
    proxy: str | None = None
    locale: str = "en-US"
    timezone: str = "UTC"
    fingerprint_seed: int = 1000
    browser_tier: CollectorTier = CollectorTier.CHROMIUM_HARDENED
    browser_executable: str | None = None
    browser_user_data_root: Path | None = None
    timeout_sec: int = 20
    headless: bool = False


@dataclass(slots=True)
class HTMLSignals:
    page_title: str | None
    text_char_count: int
    tag_count: int
    script_count: int
    form_count: int
    input_count: int
    iframe_count: int
    anchor_count: int
    meta_refresh: bool
    anti_bot_signals: list[str] = field(default_factory=list)
    embedded_widget_signals: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeFeatureVector:
    values: list[float]
    mask: list[float]
    names: tuple[str, ...] = RUNTIME_FEATURE_NAMES


@dataclass(slots=True)
class CollectionFailure:
    code: CollectionStatus
    reason: FailureReason
    message: str
    retryable: bool = False


@dataclass(slots=True)
class ArtifactManifest:
    request: dict[str, Any]
    status: CollectionStatus
    reason: FailureReason
    tier_used: CollectorTier
    fallback_reason: FailureReason | None
    http_status: int | None
    final_url: str | None
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    network_summary: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    artifact_paths: dict[str, str] = field(default_factory=dict)
    runtime_features: list[float] = field(default_factory=list)
    runtime_feature_mask: list[float] = field(default_factory=list)
    cache_key: str = ""


@dataclass(slots=True)
class CollectedPage:
    requested_url: str
    final_url: str | None
    final_html: str
    tier_used: CollectorTier
    status: CollectionStatus
    reason: FailureReason
    artifact_dir: Path
    manifest_path: Path
    http_status: int | None = None
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    raw_html: str | None = None
    browser_html: str | None = None
    fallback_reason: FailureReason | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, Any] = field(default_factory=dict)
    network_summary: dict[str, Any] = field(default_factory=dict)
    runtime_features: list[float] = field(default_factory=list)
    runtime_feature_mask: list[float] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    cache_key: str = ""
    error_message: str | None = None
