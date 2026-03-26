from __future__ import annotations

import base64

import requests


class RealFakeService:
    def __init__(self, *, enabled: bool, api_base_url: str, timeout: int):
        self.enabled = bool(enabled)
        self.api_base_url = str(api_base_url or "").strip().rstrip("/")
        self.timeout = max(1, int(timeout))

    def analyze(self, *, url: str, image_bytes: bytes, image_format: str = "png") -> dict | None:
        if not self.enabled:
            return None

        if not self.api_base_url:
            raise RuntimeError("RealFake API is enabled but APP_REALFAKE_API_BASE_URL is not configured.")

        if not image_bytes:
            raise RuntimeError("RealFake API request requires screenshot bytes.")

        response = requests.post(
            f"{self.api_base_url}/analyze",
            json={
                "url": url,
                "screenshot": base64.b64encode(image_bytes).decode("ascii"),
                "screenshot_format": str(image_format or "png").lower(),
            },
            timeout=self.timeout,
        )

        payload = response.json()
        if not response.ok:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if isinstance(detail, dict):
                message = detail.get("error") or detail.get("detail") or str(detail)
            elif isinstance(detail, str) and detail.strip():
                message = detail
            else:
                message = payload.get("error") if isinstance(payload, dict) else None
            raise RuntimeError(message or f"RealFake API failed with {response.status_code}.")

        if not isinstance(payload, dict):
            raise RuntimeError("RealFake API returned an unexpected response payload.")

        return payload
