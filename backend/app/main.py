from __future__ import annotations

import requests
from fastapi import FastAPI
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from .auth import build_admin_auth_state
from .config import get_settings
from .routes import router
from .scanner import ScannerService, load_ui_html


def create_app() -> FastAPI:
    settings = get_settings()

    if settings.insecure:
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

    app = FastAPI(
        title="SurfPhish Scanner API",
        version="2.0.0",
    )
    app.state.settings = settings
    app.state.scanner_service = ScannerService(settings)
    app.state.ui_html = load_ui_html(settings.ui_html_path)
    app.state.admin_auth = build_admin_auth_state(settings.admin_password)
    app.include_router(router)
    return app


app = create_app()
