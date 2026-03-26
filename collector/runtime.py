from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .types import (
    CollectionStatus,
    FailureReason,
    HTMLSignals,
    RuntimeFeatureVector,
    RUNTIME_FEATURE_DIM,
)


RENDER_HTTP_STATUSES = {202, 401, 403, 407, 409, 425, 429, 500, 502, 503, 504}
CHALLENGE_HTTP_STATUSES = {401, 403, 407, 429}
CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "verify you are human",
    "security check",
    "checking your browser",
)
REDIRECT_STUB_TITLE_MARKERS = (
    "301 moved permanently",
    "302 found",
    "moved permanently",
    "object moved",
    "redirecting",
)
CHALLENGE_TEXT_MARKERS = (
    "verify you are human",
    "checking your browser",
    "enable javascript and cookies to continue",
    "please stand by while we are checking your browser",
    "sorry, you have been blocked",
    "attention required",
    "security check",
    "please complete the security check",
    "press and hold",
)
CHALLENGE_DOM_MARKERS = (
    "cf-browser-verification",
    "cf-challenge",
    "challenge-form",
    "challenge-running",
    "cf-please-wait",
    "ray id",
)
WIDGET_HINTS = {
    "turnstile": {
        "classes": (".cf-turnstile", "[name='cf-turnstile-response']"),
        "script_substrings": ("challenges.cloudflare.com/turnstile",),
    },
    "recaptcha": {
        "classes": (".g-recaptcha", "[name='g-recaptcha-response']"),
        "script_substrings": ("google.com/recaptcha/api.js", "recaptcha.net/recaptcha/api.js"),
    },
    "hcaptcha": {
        "classes": (".h-captcha", "[name='h-captcha-response']"),
        "script_substrings": ("js.hcaptcha.com/1/api.js", "hcaptcha.com"),
    },
}


def _safe_log(value: int | float | None) -> float:
    if value is None:
        return 0.0
    return float(math.log1p(max(0.0, float(value))))


def _status_family(status_code: int | None) -> float:
    if status_code is None:
        return 0.0
    return float(status_code // 100)


def is_html_content_type(content_type: str | None) -> bool:
    if not content_type:
        return True
    lowered = content_type.lower()
    return "text/html" in lowered or "application/xhtml" in lowered


def analyze_html(html: str) -> HTMLSignals:
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    tags = soup.find_all(True)
    text_content = " ".join(soup.get_text(" ", strip=True).split())
    lowered = (html or "").lower()
    title_lowered = (title or "").strip().lower()
    text_lowered = text_content.lower()
    script_srcs = [str(script.get("src", "")).lower() for script in soup.find_all("script") if script.get("src")]

    embedded_widget_signals: list[str] = []
    for provider, config in WIDGET_HINTS.items():
        selector_match = any(soup.select(selector) for selector in config["classes"])
        script_match = any(any(marker in src for marker in config["script_substrings"]) for src in script_srcs)
        if selector_match or script_match:
            embedded_widget_signals.append(provider)

    anti_bot_signals: list[str] = []
    has_challenge_title = any(marker in title_lowered for marker in CHALLENGE_TITLE_MARKERS)
    has_challenge_text = any(marker in text_lowered for marker in CHALLENGE_TEXT_MARKERS)
    has_challenge_dom = any(marker in lowered for marker in CHALLENGE_DOM_MARKERS)
    sparse_gate_like = len(text_content) <= 256 and len(tags) <= 120
    generic_title = title is None or title_lowered in CHALLENGE_TITLE_MARKERS

    if has_challenge_dom and (sparse_gate_like or generic_title):
        anti_bot_signals.append("challenge_dom")
    if has_challenge_title:
        anti_bot_signals.append("challenge_title")
    if has_challenge_text and (sparse_gate_like or generic_title):
        anti_bot_signals.append("challenge_text")
    if any(signal in embedded_widget_signals for signal in ("turnstile", "recaptcha", "hcaptcha")) and (
        sparse_gate_like and (has_challenge_text or generic_title)
    ):
        anti_bot_signals.append("challenge_widget_gate")

    return HTMLSignals(
        page_title=title,
        text_char_count=len(text_content),
        tag_count=len(tags),
        script_count=len(soup.find_all("script")),
        form_count=len(soup.find_all("form")),
        input_count=len(soup.find_all("input")),
        iframe_count=len(soup.find_all("iframe")),
        anchor_count=len(soup.find_all("a")),
        meta_refresh=any((meta.get("http-equiv") or "").lower() == "refresh" for meta in soup.find_all("meta")),
        anti_bot_signals=anti_bot_signals,
        embedded_widget_signals=embedded_widget_signals,
    )


def infer_challenge_reasons(
    *,
    status_code: int | None,
    signals: HTMLSignals,
) -> list[str]:
    reasons = list(signals.anti_bot_signals)
    if status_code in CHALLENGE_HTTP_STATUSES:
        reasons.append(f"http-status-{status_code}")
    if signals.text_char_count <= 32 and signals.script_count >= 5:
        reasons.append("low-text-script-shell")
    if signals.meta_refresh and signals.text_char_count < 256:
        reasons.append("meta-refresh-interstitial")
    if (signals.page_title or "").strip() == "" and signals.script_count >= 8:
        reasons.append("empty-title-script-heavy")
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def should_escalate_to_browser(
    *,
    status_code: int | None,
    content_type: str | None,
    signals: HTMLSignals,
    html: str,
) -> FailureReason | None:
    if not html.strip():
        return FailureReason.EMPTY_BODY
    if not is_html_content_type(content_type):
        return FailureReason.NON_HTML
    title_lowered = (signals.page_title or "").strip().lower()
    if title_lowered in REDIRECT_STUB_TITLE_MARKERS and signals.tag_count <= 20 and signals.anchor_count <= 1 and signals.form_count == 0:
        return FailureReason.JS_SHELL
    if signals.tag_count == 0:
        return FailureReason.JS_SHELL
    if signals.tag_count <= 12 and signals.text_char_count <= 160 and signals.anchor_count <= 1 and signals.form_count == 0:
        return FailureReason.JS_SHELL
    if signals.tag_count <= 3 and signals.text_char_count <= 64:
        return FailureReason.JS_SHELL
    if status_code in RENDER_HTTP_STATUSES:
        return FailureReason.BLOCKED_STATUS
    if signals.anti_bot_signals:
        return FailureReason.CHALLENGE
    if signals.text_char_count <= 32 and signals.script_count >= 5:
        return FailureReason.JS_SHELL
    if (signals.page_title or "").strip() == "" and signals.script_count >= 8:
        return FailureReason.JS_SHELL
    return None


def classify_final_status(
    *,
    status_code: int | None,
    content_type: str | None,
    html: str,
    signals: HTMLSignals,
) -> tuple[CollectionStatus, FailureReason]:
    if not html.strip():
        return CollectionStatus.FETCH_FAILED, FailureReason.EMPTY_BODY
    if not is_html_content_type(content_type):
        return CollectionStatus.NON_HTML, FailureReason.NON_HTML
    challenge_reasons = infer_challenge_reasons(status_code=status_code, signals=signals)
    if status_code in CHALLENGE_HTTP_STATUSES:
        return CollectionStatus.BLOCKED, FailureReason.BLOCKED_STATUS
    if challenge_reasons:
        return CollectionStatus.CHALLENGE, FailureReason.CHALLENGE
    return CollectionStatus.SUCCESS, FailureReason.NONE


def build_runtime_feature_vector(
    *,
    raw_signals: HTMLSignals | None,
    final_signals: HTMLSignals,
    status_code: int | None,
    raw_status_code: int | None,
    redirect_count: int,
    browser_used: bool,
    browser_requested: bool,
    network_summary: dict[str, Any] | None,
    timings: dict[str, Any] | None,
    final_status: CollectionStatus,
) -> RuntimeFeatureVector:
    raw = raw_signals
    final = final_signals
    network = network_summary or {}
    timing = timings or {}

    values = [
        _status_family(status_code),
        _status_family(raw_status_code),
        float(redirect_count),
        _safe_log(raw.text_char_count if raw else 0),
        _safe_log(final.text_char_count),
        _safe_log(raw.tag_count if raw else 0),
        _safe_log(final.tag_count),
        _safe_log(raw.script_count if raw else 0),
        _safe_log(final.script_count),
        float(raw.form_count if raw else 0),
        float(final.form_count),
        float(raw.input_count if raw else 0),
        float(final.input_count),
        float(raw.iframe_count if raw else 0),
        float(final.iframe_count),
        float(final.meta_refresh),
        float(raw.meta_refresh if raw else 0),
        float(len(final.anti_bot_signals)),
        float(final_status in {CollectionStatus.CHALLENGE, CollectionStatus.BLOCKED}),
        float(final_status == CollectionStatus.BLOCKED),
        float(browser_used),
        float(browser_requested),
        _safe_log(network.get("request_total", 0)),
        _safe_log(network.get("request_failed", 0)),
        _safe_log(network.get("xhr_fetch_total", 0)),
        _safe_log(network.get("script_request_total", 0)),
        float(bool(network.get("websocket_seen"))),
        _safe_log(timing.get("navigation_ms")),
        _safe_log(timing.get("domcontentloaded_ms")),
        _safe_log(timing.get("load_ms")),
        _safe_log(timing.get("settle_ms")),
        _safe_log(abs(final.text_char_count - (raw.text_char_count if raw else 0))),
    ]
    if len(values) != RUNTIME_FEATURE_DIM:
        raise ValueError(f"Expected {RUNTIME_FEATURE_DIM} runtime features, got {len(values)}")
    mask = [1.0] * RUNTIME_FEATURE_DIM
    if raw is None:
        for index in (1, 3, 5, 7, 9, 11, 13, 16, 31):
            mask[index] = 0.0
            values[index] = 0.0
    return RuntimeFeatureVector(values=values, mask=mask)


def signals_to_dict(signals: HTMLSignals, *, status_code: int | None) -> dict[str, Any]:
    challenge_reasons = infer_challenge_reasons(status_code=status_code, signals=signals)
    return {
        "page_title": signals.page_title,
        "text_char_count": signals.text_char_count,
        "tag_count": signals.tag_count,
        "script_count": signals.script_count,
        "form_count": signals.form_count,
        "input_count": signals.input_count,
        "iframe_count": signals.iframe_count,
        "anchor_count": signals.anchor_count,
        "meta_refresh": signals.meta_refresh,
        "anti_bot_signals": list(signals.anti_bot_signals),
        "embedded_widget_signals": list(signals.embedded_widget_signals),
        "challenge_reasons": challenge_reasons,
        "challenge_suspected": bool(challenge_reasons),
    }


def extract_redirect_target(html: str, base_url: str) -> str | None:
    if not html.strip():
        return None
    soup = BeautifulSoup(html, "html.parser")

    meta_refresh = soup.find("meta", attrs={"http-equiv": re.compile("^refresh$", re.I)})
    if meta_refresh and meta_refresh.get("content"):
        content = str(meta_refresh.get("content", ""))
        match = re.search(r"url\s*=\s*([^;]+)$", content, re.I)
        if match:
            target = match.group(1).strip().strip("'\"")
            if target:
                return urljoin(base_url, target)

    script_text = "\n".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
    patterns = (
        r"""window\.location(?:\.href)?\s*=\s*['"]([^'"]+)['"]""",
        r"""location\.href\s*=\s*['"]([^'"]+)['"]""",
        r"""location\.replace\(\s*['"]([^'"]+)['"]\s*\)""",
    )
    for pattern in patterns:
        match = re.search(pattern, script_text, re.I)
        if match:
            target = match.group(1).strip()
            if target:
                return urljoin(base_url, target)

    body_text = " ".join(soup.get_text(" ", strip=True).split())
    lowered = body_text.lower()
    redirect_titles = {
        "301 moved permanently",
        "302 found",
        "redirecting",
        "object moved",
        "document moved",
        "文件已移動",
    }
    title = (soup.title.string.strip() if soup.title and soup.title.string else "")
    if title.lower() in redirect_titles or title in redirect_titles:
        anchor = soup.find("a", href=True)
        if anchor and anchor.get("href"):
            return urljoin(base_url, str(anchor["href"]))
    if ("moved" in lowered or "redirecting" in lowered or "移動" in body_text) and len(soup.find_all(True)) <= 12:
        anchor = soup.find("a", href=True)
        if anchor and anchor.get("href"):
            return urljoin(base_url, str(anchor["href"]))
    return None

