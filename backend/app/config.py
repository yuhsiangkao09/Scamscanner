from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"


def load_env_file(env_file: Path = DEFAULT_ENV_FILE) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _as_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _resolve_project_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _resolve_optional_project_path(path_str: str | None) -> Path | None:
    value = str(path_str or "").strip()
    if not value:
        return None
    return _resolve_project_path(value)


@dataclass(frozen=True)
class AppSettings:
    model_path: Path
    threshold: float
    device: str
    beta: float
    timeout: int
    host: str
    port: int
    no_domain: bool
    save_raw_html: bool
    raw_html_dir: Path
    insecure: bool
    history_limit: int
    event_log_path: Path
    feedback_log_path: Path
    feedback_html_dir: Path
    screenshot_dir: Path
    collector_browser_executable: str
    collector_browser_user_data_root: Path | None
    collector_collection_mode: str
    collector_cache_policy: str
    collector_artifact_profile: str
    collector_locale: str
    collector_timezone: str
    collector_fingerprint_seed: int
    collector_timeout: int
    collector_headless: bool
    realfake_enabled: bool
    realfake_api_base_url: str
    realfake_timeout: int
    admin_password: str
    admin_password_generated: bool
    reload: bool
    ui_html_path: Path


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    load_env_file()

    generated_admin_password = False
    admin_password = os.getenv("APP_ADMIN_PASSWORD", "").strip()
    if not admin_password:
        admin_password = secrets.token_urlsafe(18)
        generated_admin_password = True

    settings = AppSettings(
        model_path=_resolve_project_path(
            os.getenv(
                "APP_MODEL_PATH",
                "models/SurfPhish_1774277132053218/epoch=4-step=6525.ckpt",
            )
        ),
        threshold=_as_float("APP_THRESHOLD", 0.64023596),
        device=os.getenv("APP_DEVICE", "cpu").strip() or "cpu",
        beta=_as_float("APP_BETA", 1.0),
        timeout=_as_int("APP_TIMEOUT", 15),
        host=os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_as_int("APP_PORT", 8000),
        no_domain=_as_bool("APP_NO_DOMAIN", False),
        save_raw_html=_as_bool("APP_SAVE_RAW_HTML", True),
        raw_html_dir=_resolve_project_path(
            os.getenv("APP_RAW_HTML_DIR", "logs/url_scanner_html")
        ),
        insecure=_as_bool("APP_INSECURE", False),
        history_limit=_as_int("APP_HISTORY_LIMIT", 18),
        event_log_path=_resolve_project_path(
            os.getenv("APP_EVENT_LOG", "logs/url_scanner_events.jsonl")
        ),
        feedback_log_path=_resolve_project_path(
            os.getenv("APP_FEEDBACK_LOG", "logs/url_scanner_feedback.jsonl")
        ),
        feedback_html_dir=_resolve_project_path(
            os.getenv("APP_FEEDBACK_HTML_DIR", "logs/url_scanner_feedback_html")
        ),
        screenshot_dir=_resolve_project_path(
            os.getenv("APP_SCREENSHOT_DIR", "logs/url_scanner_screenshots")
        ),
        collector_browser_executable=os.getenv("APP_COLLECTOR_BROWSER_EXECUTABLE", "").strip(),
        collector_browser_user_data_root=_resolve_optional_project_path(
            os.getenv("APP_COLLECTOR_BROWSER_USER_DATA_ROOT", "")
        ),
        collector_collection_mode=os.getenv("APP_COLLECTOR_COLLECTION_MODE", "browser_required").strip() or "browser_required",
        collector_cache_policy=os.getenv("APP_COLLECTOR_CACHE_POLICY", "reuse").strip() or "reuse",
        collector_artifact_profile=os.getenv("APP_COLLECTOR_ARTIFACT_PROFILE", "rich").strip() or "rich",
        collector_locale=os.getenv("APP_COLLECTOR_LOCALE", "en-US").strip() or "en-US",
        collector_timezone=os.getenv("APP_COLLECTOR_TIMEZONE", "UTC").strip() or "UTC",
        collector_fingerprint_seed=_as_int("APP_COLLECTOR_FINGERPRINT_SEED", 1000),
        collector_timeout=_as_int("APP_COLLECTOR_TIMEOUT", 20),
        collector_headless=_as_bool("APP_COLLECTOR_HEADLESS", True),
        realfake_enabled=_as_bool("APP_REALFAKE_ENABLED", False),
        realfake_api_base_url=os.getenv("APP_REALFAKE_API_BASE_URL", "").strip().rstrip("/"),
        realfake_timeout=_as_int("APP_REALFAKE_TIMEOUT", 90),
        admin_password=admin_password,
        admin_password_generated=generated_admin_password,
        reload=_as_bool("APP_RELOAD", False),
        ui_html_path=_resolve_project_path(
            os.getenv("APP_UI_HTML_PATH", "url_scanner_ui.html")
        ),
    )

    if not settings.model_path.exists():
        raise FileNotFoundError(f"Model file not found: {settings.model_path}")

    if not settings.ui_html_path.exists():
        raise FileNotFoundError(f"Dashboard HTML file not found: {settings.ui_html_path}")

    return settings
