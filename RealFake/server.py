"""
FastAPI server for phishing analysis.

Usage:
    uvicorn server:app --reload --port 8000
"""

import base64
import json
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from analyze import call_bedrock, parse_vlm_response, take_screenshot
from generate_prompt import (
    SYSTEM_PROMPT,
    build_user_prompt,
    extract_html_signals,
    fetch_page,
    get_url_intelligence,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RealFake", description="Layer 2 phishing detection API")


class AnalyzeRequest(BaseModel):
    url: str
    screenshot: str | None = None  # base64-encoded PNG


class Signal(BaseModel):
    title: str
    detail: str


class ExternalLink(BaseModel):
    text: str
    domain: str


class CollectedEvidence(BaseModel):
    redirects: list[str]
    final_url: str
    external_links: list[ExternalLink]
    external_script_domains: list[str]
    iframes: list[str]


class AnalyzeResponse(BaseModel):
    is_phishing: bool
    risk_level: str
    confidence: float
    summary: str
    signals: list[Signal]
    action: str
    collected_evidence: CollectedEvidence


class ErrorResponse(BaseModel):
    error: str
    stage: str
    detail: str | None = None


@app.post("/analyze", responses={500: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    url = req.url if req.url.startswith("http") else f"https://{req.url}"

    # 1. Screenshot
    try:
        if req.screenshot:
            image_bytes = base64.b64decode(req.screenshot)
        else:
            image_bytes = take_screenshot(url)
    except Exception as e:
        logger.error(f"Screenshot failed for {url}: {e}")
        raise HTTPException(status_code=502, detail={
            "error": "截圖失敗",
            "stage": "screenshot",
            "detail": str(e),
        })

    # 2. Fetch page & extract signals
    page_data = fetch_page(url)
    html_signals = extract_html_signals(page_data["html"], page_data["final_url"])
    url_intel = get_url_intelligence(url)

    # 3. Call VLM
    user_prompt = build_user_prompt(url, page_data, html_signals, url_intel)
    try:
        raw = call_bedrock(SYSTEM_PROMPT, user_prompt, image_bytes)
    except Exception as e:
        logger.error(f"Bedrock call failed for {url}: {e}")
        raise HTTPException(status_code=502, detail={
            "error": "模型呼叫失敗",
            "stage": "bedrock",
            "detail": str(e),
        })

    # 4. Parse VLM response
    try:
        result = parse_vlm_response(raw)
    except json.JSONDecodeError as e:
        logger.error(f"VLM returned invalid JSON for {url}: {raw[:200]}")
        raise HTTPException(status_code=502, detail={
            "error": "模型回傳格式錯誤",
            "stage": "parse",
            "detail": raw[:500],
        })

    # 5. Attach collected evidence
    result["collected_evidence"] = {
        "redirects": page_data.get("redirects", []),
        "final_url": page_data["final_url"],
        "external_links": html_signals.get("external_links", []),
        "external_script_domains": html_signals.get("external_script_domains", []),
        "iframes": html_signals.get("iframes", []),
    }

    return result
