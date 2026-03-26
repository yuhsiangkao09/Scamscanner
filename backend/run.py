from __future__ import annotations

import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()

    print("Starting SurfPhish backend with uvicorn...")
    print(f"  Model: {settings.model_path}")
    print(f"  Threshold: {settings.threshold:.8f}")
    print(f"  Device: {settings.device}")
    print(f"  Domain features: {'disabled' if settings.no_domain else 'enabled'}")
    print(f"  Default TLS verification: {'disabled' if settings.insecure else 'enabled'}")
    print(f"  Save raw HTML: {'enabled' if settings.save_raw_html else 'disabled'}")
    if settings.save_raw_html:
        print(f"  Raw HTML dir: {settings.raw_html_dir}")
    print(f"  Feedback log: {settings.feedback_log_path}")
    print(f"  Feedback HTML dir: {settings.feedback_html_dir}")
    print(f"  Dashboard: http://{settings.host}:{settings.port}/dashboard")
    print(f"  Admin login: http://{settings.host}:{settings.port}/login")
    print(f"  Admin password: {settings.admin_password}")
    if settings.admin_password_generated:
        print("  Warning: APP_ADMIN_PASSWORD was empty, so a temporary password was generated.")

    uvicorn.run(
        "backend.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


if __name__ == "__main__":
    main()
