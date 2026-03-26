from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs

import requests
from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .auth import (
    SESSION_COOKIE_NAME,
    create_session_token,
    is_admin_authenticated,
    render_login_html,
    require_admin_api,
    verify_password,
)
from .scanner import read_event_log_tail
from .utils import compact_text, decode_submitted_html, decode_submitted_screenshot


router = APIRouter()


def _scanner_service(request: Request):
    return request.app.state.scanner_service


@router.get("/", include_in_schema=False)
async def handle_root(request: Request):
    target = "/dashboard" if is_admin_authenticated(request) else "/login"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def handle_login_get(request: Request):
    if is_admin_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(render_login_html())


@router.post("/login", include_in_schema=False)
async def handle_login_post(request: Request):
    form_data = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    password = (form_data.get("password") or [""])[0]
    auth = request.app.state.admin_auth

    if not verify_password(password, auth["password_record"]):
        return HTMLResponse(
            render_login_html("Invalid administrator password."),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_session_token()
    auth["sessions"].add(token)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return response


@router.post("/logout", include_in_schema=False)
async def handle_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if token:
        request.app.state.admin_auth["sessions"].discard(token)
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def handle_dashboard(request: Request):
    if not is_admin_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(request.app.state.ui_html)


@router.get("/health")
async def handle_health(request: Request):
    service = _scanner_service(request)
    config = service.config_payload()
    return {
        "status": "ok",
        "model": config["model_name"],
        "device": config["device"],
    }


@router.get("/api/config")
async def handle_config(request: Request):
    require_admin_api(request)
    return _scanner_service(request).config_payload()


@router.get("/api/history")
async def handle_history(request: Request):
    require_admin_api(request)
    items = await _scanner_service(request).get_history()
    return {"items": items}


@router.get("/api/events")
async def handle_events(request: Request):
    require_admin_api(request)
    service = _scanner_service(request)
    limit = int(request.query_params.get("limit", 40))
    limit = max(1, min(limit, 200))
    events = await asyncio.to_thread(read_event_log_tail, service.event_log_path, limit)
    return {"items": events}


@router.get("/api/feedback")
async def handle_feedback_list(request: Request):
    require_admin_api(request)
    service = _scanner_service(request)
    limit = int(request.query_params.get("limit", 40))
    limit = max(1, min(limit, 200))
    items = await service.get_feedback_reports(limit)
    return {"items": items}


@router.get("/api/feedback/{feedback_id}")
async def handle_feedback_detail(feedback_id: str, request: Request):
    require_admin_api(request)
    item = await _scanner_service(request).get_feedback_report(feedback_id)
    if not item:
        return JSONResponse(
            {"error": "Feedback report not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return {"item": item}


@router.get("/api/feedback/{feedback_id}/html", response_class=HTMLResponse)
async def handle_feedback_html(feedback_id: str, request: Request):
    require_admin_api(request)
    service = _scanner_service(request)
    item = await service.get_feedback_report(feedback_id)
    if not item:
        return JSONResponse(
            {"error": "Feedback report not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    html_info = item.get("html_info") or {}
    stored_path = html_info.get("stored_path")
    if not stored_path:
        return JSONResponse(
            {"error": "No stored HTML for this report"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    path = Path(stored_path)
    if not path.exists():
        return JSONResponse(
            {"error": "Stored HTML file is missing"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return HTMLResponse(path.read_text(encoding="utf-8", errors="ignore"))


@router.post("/api/feedback")
async def handle_feedback_submit(request: Request):
    service = _scanner_service(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON payload"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    kind = str(payload.get("kind", "")).strip().lower()
    url = str(payload.get("url", "")).strip()
    source = str(payload.get("source", "")).strip() or "extension"
    page_context = payload.get("page_context")
    summary = payload.get("summary")
    notes = payload.get("notes")
    source_url = str(payload.get("source_url", "")).strip() or url

    if kind not in {"false_positive", "report_site"}:
        return JSONResponse(
            {"error": "Unsupported feedback kind"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not url:
        return JSONResponse(
            {"error": "Missing feedback URL"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        html = decode_submitted_html(payload)
    except Exception as exc:
        return JSONResponse(
            {"error": f"Invalid compressed HTML payload: {exc}"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    html_info = None
    feedback_id = secrets.token_urlsafe(9)
    if isinstance(html, str) and html.strip():
        html_path = await asyncio.to_thread(
            service.save_feedback_html,
            source_url,
            html,
            feedback_id,
        )
        html_info = {
            "source_url": source_url,
            "html_chars": len(html),
            "stored_path": html_path,
            "preview": compact_text(html, limit=1200),
        }

    record = service.build_feedback_record(
        feedback_id=feedback_id,
        kind=kind,
        source=source,
        url=url,
        page_context=page_context,
        summary=summary,
        html_info=html_info,
        notes=notes if isinstance(notes, list) else [],
    )
    await service.append_feedback_log(record)
    return {"ok": True, "record": record}


@router.post("/api/scan")
async def handle_scan(request: Request):
    service = _scanner_service(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON payload"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    url = str(payload.get("url", "")).strip()
    source_url = str(payload.get("source_url", "")).strip()
    detail_level = str(payload.get("detail_level", "standard") or "standard").strip().lower()
    debug = bool(payload.get("debug", False))
    insecure = payload.get("insecure")
    timeout = payload.get("timeout", service.settings.timeout)
    scan_timeout = service.settings.timeout if timeout is None else int(timeout)
    scan_insecure = False if insecure is None else bool(insecure)

    try:
        html = decode_submitted_html(payload)
    except Exception as exc:
        return JSONResponse(
            {"error": f"Invalid compressed HTML payload: {exc}"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        screenshot_payload = decode_submitted_screenshot(payload)
    except Exception as exc:
        return JSONResponse(
            {"error": f"Invalid screenshot payload: {exc}"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    has_html = isinstance(html, str) and html.strip() != ""
    if not url and not has_html:
        return JSONResponse(
            {"error": "Missing URL or HTML input"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    request_url = source_url if has_html else url
    input_mode = "html" if has_html else "url"
    service.log_received_payload(
        input_mode=input_mode,
        request_url=request_url,
        source_url=source_url,
        html_content=html,
        payload=payload,
        debug=debug,
        insecure=scan_insecure,
        timeout=scan_timeout,
    )

    try:
        if has_html:
            result, timings = await service.scan_html(
                html_content=html,
                source_url=source_url,
                debug=debug,
            )
        else:
            result, timings = await service.scan(
                url=url,
                debug=debug,
                insecure=insecure,
                timeout=scan_timeout,
            )

        if screenshot_payload:
            screenshot_artifact = await asyncio.to_thread(
                service.save_scan_screenshot,
                request_url or url or source_url or "unknown",
                screenshot_payload["image_bytes"],
                screenshot_payload["image_format"],
                detail_level,
            )
            artifacts = dict(result.get("artifacts") or {})
            artifacts["full_page_screenshot"] = {
                "stored_path": screenshot_artifact["stored_path"],
                "base64_path": screenshot_artifact["base64_path"],
                "base64_chars": screenshot_artifact["base64_chars"],
                "format": screenshot_payload["image_format"],
                "width": screenshot_payload["width"],
                "height": screenshot_payload["height"],
                "capture_mode": screenshot_payload["capture_mode"],
                "scale": screenshot_payload["scale"],
            }
            result["artifacts"] = artifacts

        if (
            detail_level == "detailed"
            and screenshot_payload
            and service.realfake.enabled
        ):
            full_check_started = time.perf_counter()
            try:
                full_check_analysis = await asyncio.to_thread(
                    service.analyze_full_check,
                    url=source_url or request_url or url or "unknown",
                    image_bytes=screenshot_payload["image_bytes"],
                    image_format=screenshot_payload["image_format"],
                )
                if full_check_analysis is not None:
                    result["full_check_analysis"] = full_check_analysis
            except Exception as exc:
                result["full_check_analysis_error"] = {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            finally:
                timings["full_check_analysis_ms"] = (time.perf_counter() - full_check_started) * 1000.0

        if detail_level:
            result["detail_level"] = detail_level

        response_result = result
        if not debug:
            response_result = dict(result)
            response_result.pop("preprocess_debug", None)
            response_result.pop("model_debug", None)

        service.log_scan_result(
            request_url=request_url,
            result=result,
            timings=timings,
        )
        await service.append_event_log(
            service.build_event_record(
                url=request_url,
                input_mode=input_mode,
                debug=debug,
                insecure=scan_insecure,
                timeout=scan_timeout,
                status="success",
                result=result,
                timings=timings,
                http_status=(result.get("preprocess_debug") or {}).get("http_status"),
            )
        )
        return {"result": response_result, "timings": timings}
    except requests.exceptions.SSLError as exc:
        service.log_scan_error(
            request_url=url,
            input_mode="url",
            error_type="SSLError",
            error_message=str(exc),
        )
        await service.append_event_log(
            service.build_event_record(
                url=url,
                input_mode="url",
                debug=debug,
                insecure=scan_insecure,
                timeout=scan_timeout,
                status="error",
                error={
                    "type": "SSLError",
                    "message": str(exc),
                },
            )
        )
        return JSONResponse(
            {
                "error": (
                    "TLS verification failed. Retry with insecure mode if your "
                    "certificate store is incomplete."
                ),
                "detail": str(exc),
            },
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except requests.exceptions.RequestException as exc:
        response = getattr(exc, "response", None)
        service.log_scan_error(
            request_url=url or source_url,
            input_mode="html" if has_html else "url",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        await service.append_event_log(
            service.build_event_record(
                url=url or source_url,
                input_mode="html" if has_html else "url",
                debug=debug,
                insecure=scan_insecure,
                timeout=scan_timeout,
                status="error",
                error={
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
                http_status=None if response is None else response.status_code,
            )
        )
        return JSONResponse(
            {"error": f"Request failed: {exc}"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        service.log_scan_error(
            request_url=url or source_url,
            input_mode="html" if has_html else "url",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        await service.append_event_log(
            service.build_event_record(
                url=url or source_url,
                input_mode="html" if has_html else "url",
                debug=debug,
                insecure=scan_insecure,
                timeout=scan_timeout,
                status="error",
                error={
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
        )
        return JSONResponse(
            {"error": str(exc)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/api/scan/email")
async def handle_scan_email(request: Request):
    service = _scanner_service(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON payload"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    provider = str(payload.get("provider", "gmail") or "gmail").strip().lower()
    page_url = str(payload.get("page_url", "")).strip()
    sender_name = compact_text(str(payload.get("sender_name", "")).strip(), 240)
    sender_email = compact_text(str(payload.get("sender_email", "")).strip(), 240)
    subject = compact_text(str(payload.get("subject", "")).strip(), 400)
    body_text = compact_text(str(payload.get("body_text", "")).strip(), 8000)
    warnings = [
        compact_text(str(item).strip(), 300)
        for item in (payload.get("warnings") or [])
        if str(item).strip()
    ][:20]
    attachments = [
        compact_text(str(item).strip(), 240)
        for item in (payload.get("attachments") or [])
        if str(item).strip()
    ][:20]
    links = []
    for item in payload.get("links") or []:
        if not isinstance(item, dict):
            continue
        href = compact_text(str(item.get("href", "")).strip(), 500)
        if not href:
            continue
        links.append({
            "text": compact_text(str(item.get("text", "")).strip(), 200),
            "href": href,
        })
        if len(links) >= 30:
            break

    if not page_url:
        return JSONResponse(
            {"error": "Missing page_url"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not subject and not body_text:
        return JSONResponse(
            {"error": "Missing email subject and body_text"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        screenshot_payload = decode_submitted_screenshot(payload)
    except Exception as exc:
        return JSONResponse(
            {"error": f"Invalid screenshot payload: {exc}"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    page_context = payload.get("page_context")
    service.log_received_payload(
        input_mode="email_message",
        request_url=page_url,
        source_url=page_url,
        html_content=body_text,
        payload=payload,
        debug=False,
        insecure=False,
        timeout=service.realfake.timeout,
    )

    timings = {}
    started = time.perf_counter()
    try:
        result = {
            "detail_level": "email_check",
            "provider": provider,
            "page_url": page_url,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "subject": subject,
        }

        if screenshot_payload:
            screenshot_artifact = await asyncio.to_thread(
                service.save_scan_screenshot,
                page_url,
                screenshot_payload["image_bytes"],
                screenshot_payload["image_format"],
                "email",
            )
            result["artifacts"] = {
                "message_screenshot": {
                    "stored_path": screenshot_artifact["stored_path"],
                    "base64_path": screenshot_artifact["base64_path"],
                    "base64_chars": screenshot_artifact["base64_chars"],
                    "format": screenshot_payload["image_format"],
                    "width": screenshot_payload["width"],
                    "height": screenshot_payload["height"],
                    "capture_mode": screenshot_payload["capture_mode"],
                    "scale": screenshot_payload["scale"],
                }
            }

        analyze_started = time.perf_counter()
        try:
            analysis = await asyncio.to_thread(
                service.analyze_email_check,
                provider=provider,
                page_url=page_url,
                sender_name=sender_name,
                sender_email=sender_email,
                subject=subject,
                body_text=body_text,
                links=links,
                attachments=attachments,
                warnings=warnings,
                image_bytes=None if not screenshot_payload else screenshot_payload["image_bytes"],
                image_format="jpeg" if not screenshot_payload else screenshot_payload["image_format"],
            )
            if analysis is not None:
                result["full_check_analysis"] = analysis
        except Exception as exc:
            result["full_check_analysis_error"] = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
        finally:
            timings["full_check_analysis_ms"] = (time.perf_counter() - analyze_started) * 1000.0

        if page_context is not None:
            result["page_context"] = page_context

        timings["total_ms"] = (time.perf_counter() - started) * 1000.0
        await service.append_event_log(
            service.build_event_record(
                url=page_url,
                input_mode="email_message",
                debug=False,
                insecure=False,
                timeout=service.realfake.timeout,
                status="success",
                result=result,
                timings=timings,
            )
        )
        return {"result": result, "timings": timings}
    except Exception as exc:
        await service.append_event_log(
            service.build_event_record(
                url=page_url,
                input_mode="email_message",
                debug=False,
                insecure=False,
                timeout=service.realfake.timeout,
                status="error",
                error={
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
        )
        return JSONResponse(
            {"error": str(exc)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/api/scan/fetch-url")
async def handle_scan_fetch_url(request: Request):
    service = _scanner_service(request)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON payload"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    url = str(payload.get("url", "")).strip()
    debug = bool(payload.get("debug", False))
    timeout = payload.get("timeout", service.settings.collector_timeout)
    collection_mode = payload.get("collection_mode")
    cache_policy = payload.get("cache_policy")
    artifact_profile = payload.get("artifact_profile")
    proxy = payload.get("proxy")
    locale = payload.get("locale")
    timezone = payload.get("timezone")
    fingerprint_seed = payload.get("fingerprint_seed")
    headless = payload.get("headless")

    if not url:
        return JSONResponse(
            {"error": "Missing URL input"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        collector_timeout = int(timeout)
    except (TypeError, ValueError):
        return JSONResponse(
            {"error": "Invalid timeout value"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    service.log_received_payload(
        input_mode="collector_url",
        request_url=url,
        source_url=url,
        html_content="",
        payload=payload,
        debug=debug,
        insecure=False,
        timeout=collector_timeout,
    )

    collection_payload = None
    collector_request = None
    total_started = time.perf_counter()
    try:
        result, model_timings = await service.scan(
            url=url,
            debug=debug,
            insecure=False,
            timeout=collector_timeout,
        )
        request_url = (
            ((result.get("preprocess_debug") or {}).get("final_url"))
            or url
        )
        result["detail_level"] = "collector_url"

        timings = {
            **model_timings,
        }

        screenshot_payload = None
        collector_error = None
        try:
            collector_request, collected_page = await service.collect_page_from_url(
                url=request_url,
                timeout=collector_timeout,
                collection_mode=collection_mode,
                cache_policy=cache_policy,
                artifact_profile=artifact_profile,
                proxy=proxy,
                locale=locale,
                timezone=timezone,
                fingerprint_seed=fingerprint_seed,
                headless=headless,
            )
            collection_payload = service.build_collection_payload(collector_request, collected_page)
            timings["collector_ms"] = float((collected_page.timings or {}).get("elapsed_ms", 0.0))
            timings["collector_settle_ms"] = float((collected_page.timings or {}).get("settle_ms", 0.0))

            screenshot_payload = await asyncio.to_thread(service.load_collector_screenshot, collected_page)
            if screenshot_payload:
                artifacts = dict(result.get("artifacts") or {})
                artifacts["collector_screenshot"] = {
                    "stored_path": screenshot_payload["path"],
                    "format": screenshot_payload["image_format"],
                }
                result["artifacts"] = artifacts
            else:
                collector_error = {
                    "type": "CollectorScreenshotMissing",
                    "message": "Collector did not produce a screenshot for RealFake analysis.",
                }
        except Exception as exc:
            collector_error = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            result["collector_error"] = collector_error

        if service.realfake.enabled:
            full_check_started = time.perf_counter()
            try:
                if not screenshot_payload:
                    if collector_error:
                        raise RuntimeError(collector_error["message"])
                    raise RuntimeError("Collector did not produce a screenshot for RealFake analysis.")
                full_check_analysis = await asyncio.to_thread(
                    service.analyze_full_check,
                    url=request_url,
                    image_bytes=screenshot_payload["image_bytes"],
                    image_format=screenshot_payload["image_format"],
                )
                if full_check_analysis is not None:
                    result["full_check_analysis"] = full_check_analysis
            except Exception as exc:
                result["full_check_analysis_error"] = {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            finally:
                timings["full_check_analysis_ms"] = (time.perf_counter() - full_check_started) * 1000.0

        timings["total_ms"] = (time.perf_counter() - total_started) * 1000.0

        response_result = result
        if not debug:
            response_result = dict(result)
            response_result.pop("preprocess_debug", None)
            response_result.pop("model_debug", None)

        service.log_scan_result(
            request_url=request_url,
            result=result,
            timings=timings,
        )
        await service.append_event_log(
            service.build_event_record(
                url=request_url,
                input_mode="collector_url",
                debug=debug,
                insecure=False,
                timeout=collector_request.timeout_sec if collector_request is not None else collector_timeout,
                status="success",
                result=result,
                timings=timings,
                http_status=(result.get("preprocess_debug") or {}).get("http_status"),
            )
        )
        return {"result": response_result, "timings": timings}
    except requests.exceptions.RequestException as exc:
        response = getattr(exc, "response", None)
        service.log_scan_error(
            request_url=url,
            input_mode="collector_url",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        await service.append_event_log(
            service.build_event_record(
                url=url,
                input_mode="collector_url",
                debug=debug,
                insecure=False,
                timeout=collector_timeout,
                status="error",
                error={
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                    "collection": collection_payload,
                },
                http_status=None if response is None else response.status_code,
            )
        )
        return JSONResponse(
            {"error": f"Request failed: {exc}", "collection": collection_payload},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        service.log_scan_error(
            request_url=url,
            input_mode="collector_url",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        await service.append_event_log(
            service.build_event_record(
                url=url,
                input_mode="collector_url",
                debug=debug,
                insecure=False,
                timeout=collector_timeout,
                status="error",
                error={
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                    "collection": collection_payload,
                },
            )
        )
        return JSONResponse(
            {"error": str(exc), "collection": collection_payload},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
