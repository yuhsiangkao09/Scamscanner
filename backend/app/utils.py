from __future__ import annotations

import base64
import gzip
import json
from collections import deque
from pathlib import Path


def read_event_log_tail(path: Path, limit=50):
    if not path.exists():
        return []
    lines = deque(maxlen=limit)
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    events = []
    for line in reversed(lines):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def read_event_log_by_id(path: Path, event_id: str):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if item.get("id") == event_id:
                return item
    return None


def decode_submitted_html(payload):
    html = payload.get("html")
    if isinstance(html, str) and html.strip():
        return html

    encoding = str(payload.get("html_encoding", "")).strip().lower()
    compressed = payload.get("html_gzip_base64")
    if isinstance(compressed, str) and compressed.strip():
        compressed_bytes = base64.b64decode(compressed)
        if encoding in ("", "gzip+base64", "gzip-base64", "gzip"):
            return gzip.decompress(compressed_bytes).decode("utf-8", errors="ignore")
        raise ValueError(f"Unsupported html_encoding: {encoding}")

    return None


def decode_submitted_screenshot(payload):
    encoded = payload.get("screenshot_png_base64")
    if not encoded:
        return None

    image_format = str(payload.get("screenshot_format", "png") or "png").lower()
    return {
        "image_bytes": base64.b64decode(encoded),
        "image_format": image_format,
        "width": int(payload.get("screenshot_width") or 0),
        "height": int(payload.get("screenshot_height") or 0),
        "capture_mode": str(payload.get("screenshot_capture_mode", "") or ""),
        "scale": float(payload.get("screenshot_scale") or 0.0),
    }


def compact_text(text, limit=320):
    if not isinstance(text, str):
        return ""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "...(truncated)"
