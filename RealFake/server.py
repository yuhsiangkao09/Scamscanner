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
from email_prompt import EMAIL_SYSTEM_PROMPT, build_email_user_prompt
from image_prompt import IMAGE_SYSTEM_PROMPT, build_image_user_prompt
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
    screenshot: str | None = None  # base64-encoded image payload
    screenshot_format: str | None = None


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


class AnalyzeImageRequest(BaseModel):
    screenshot: str  # base64-encoded image (required)
    screenshot_format: str | None = None
    context: str | None = None  # optional user-provided context


class ImageCollectedEvidence(BaseModel):
    source_type: str = "screenshot_only"
    context: str | None = None


class AnalyzeImageResponse(BaseModel):
    is_scam: bool
    risk_level: str
    confidence: float
    summary: str
    signals: list[Signal]
    action: str
    collected_evidence: ImageCollectedEvidence


class EmailLink(BaseModel):
    text: str | None = None
    href: str


class AnalyzeEmailRequest(BaseModel):
    provider: str = "gmail"
    page_url: str
    sender_name: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    body_text: str | None = None
    links: list[EmailLink] = []
    attachments: list[str] = []
    warnings: list[str] = []
    screenshot: str | None = None
    screenshot_format: str | None = None


class EmailCollectedEvidence(BaseModel):
    provider: str
    page_url: str
    sender_name: str | None = None
    sender_email: str | None = None
    subject: str | None = None
    links: list[EmailLink]
    attachments: list[str]
    warnings: list[str]


class AnalyzeEmailResponse(BaseModel):
    is_phishing: bool
    risk_level: str
    confidence: float
    summary: str
    signals: list[Signal]
    action: str
    collected_evidence: EmailCollectedEvidence


@app.post("/analyze", responses={500: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    url = req.url if req.url.startswith("http") else f"https://{req.url}"

    # 1. Screenshot
    try:
        if req.screenshot:
            image_bytes = base64.b64decode(req.screenshot)
            image_format = str(req.screenshot_format or "png").strip().lower()
        else:
            image_bytes = take_screenshot(url)
            image_format = "png"
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
        raw = call_bedrock(SYSTEM_PROMPT, user_prompt, image_bytes, image_format=image_format)
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


@app.post("/analyze-email", responses={500: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
def analyze_email(req: AnalyzeEmailRequest) -> AnalyzeEmailResponse:
    if req.screenshot:
        try:
            image_bytes = base64.b64decode(req.screenshot)
            image_format = str(req.screenshot_format or "jpeg").strip().lower()
        except Exception as e:
            logger.error(f"Email screenshot decode failed for {req.page_url}: {e}")
            raise HTTPException(status_code=502, detail={
                "error": "Email screenshot decode failed",
                "stage": "screenshot",
                "detail": str(e),
            })
    else:
        image_bytes = None
        image_format = "jpeg"

    user_prompt = build_email_user_prompt(
        provider=req.provider,
        page_url=req.page_url,
        sender_name=req.sender_name or "",
        sender_email=req.sender_email or "",
        subject=req.subject or "",
        body_text=req.body_text or "",
        links=[link.model_dump() for link in req.links],
        attachments=req.attachments,
        warnings=req.warnings,
    )

    try:
        raw = call_bedrock(
            EMAIL_SYSTEM_PROMPT,
            user_prompt,
            image_bytes,
            image_format=image_format,
        )
    except Exception as e:
        logger.error(f"Bedrock email call failed for {req.page_url}: {e}")
        raise HTTPException(status_code=502, detail={
            "error": "Email model call failed",
            "stage": "bedrock",
            "detail": str(e),
        })

    try:
        result = parse_vlm_response(raw)
    except json.JSONDecodeError:
        logger.error(f"Email VLM returned invalid JSON for {req.page_url}: {raw[:200]}")
        raise HTTPException(status_code=502, detail={
            "error": "Email model returned invalid JSON",
            "stage": "parse",
            "detail": raw[:500],
        })

    result["collected_evidence"] = {
        "provider": req.provider,
        "page_url": req.page_url,
        "sender_name": req.sender_name,
        "sender_email": req.sender_email,
        "subject": req.subject,
        "links": [link.model_dump() for link in req.links],
        "attachments": req.attachments,
        "warnings": req.warnings,
    }
    return result


@app.post("/analyze-image", responses={500: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
def analyze_image(req: AnalyzeImageRequest) -> AnalyzeImageResponse:
    # 1. Decode screenshot
    try:
        image_bytes = base64.b64decode(req.screenshot)
        image_format = str(req.screenshot_format or "png").strip().lower()
    except Exception as e:
        logger.error(f"Image decode failed: {e}")
        raise HTTPException(status_code=502, detail={
            "error": "圖片解碼失敗",
            "stage": "screenshot",
            "detail": str(e),
        })

    # 2. Call VLM
    user_prompt = build_image_user_prompt(req.context)
    try:
        raw = call_bedrock(IMAGE_SYSTEM_PROMPT, user_prompt, image_bytes, image_format=image_format)
    except Exception as e:
        logger.error(f"Bedrock call failed for image analysis: {e}")
        raise HTTPException(status_code=502, detail={
            "error": "模型呼叫失敗",
            "stage": "bedrock",
            "detail": str(e),
        })

    # 3. Parse VLM response
    try:
        result = parse_vlm_response(raw)
    except json.JSONDecodeError:
        logger.error(f"VLM returned invalid JSON for image analysis: {raw[:200]}")
        raise HTTPException(status_code=502, detail={
            "error": "模型回傳格式錯誤",
            "stage": "parse",
            "detail": raw[:500],
        })

    # 4. Attach collected evidence
    result["collected_evidence"] = {
        "source_type": "screenshot_only",
        "context": req.context,
    }

    return result
