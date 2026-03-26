from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
import urllib3

from .types import CollectionRequest


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/144.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
DEFAULT_ORIGINAL_HEADERS = ["Host", "Connection", "Upgrade-Insecure-Requests", "User-Agent", "Accept", "Accept-Language"]
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass(slots=True)
class HTTPCollectionResult:
    requested_url: str
    final_url: str | None
    status_code: int | None
    headers: dict[str, Any] = field(default_factory=dict)
    content_type: str | None = None
    text: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    backend: str = "requests"
    error_message: str | None = None


def rnet_ready() -> tuple[bool, str | None]:
    try:
        import rnet  # type: ignore
    except ModuleNotFoundError:
        return False, None
    return True, getattr(rnet, "__version__", None)


def _parse_status(status: Any) -> int | None:
    if status is None:
        return None
    candidates = [getattr(status, "value", None), getattr(status, "code", None), getattr(status, "as_int", None), status]
    for candidate in candidates:
        if candidate is None:
            continue
        if callable(candidate):
            try:
                candidate = candidate()
            except Exception:  # noqa: BLE001
                continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _headers_to_dict(headers: Any) -> dict[str, Any]:
    if headers is None:
        return {}
    if isinstance(headers, dict):
        return {str(key): value for key, value in headers.items()}
    try:
        iterable = list(headers)
        converted: dict[str, Any] = {}
        for key, value in iterable:
            key_str = key.decode("utf-8", errors="ignore") if isinstance(key, (bytes, bytearray)) else str(key)
            value_str = value.decode("utf-8", errors="ignore") if isinstance(value, (bytes, bytearray)) else str(value)
            converted[key_str] = value_str
        return converted
    except Exception:  # noqa: BLE001
        return {}


def _history_to_list(history: Any) -> list[dict[str, Any]]:
    if history is None:
        return []
    items: list[dict[str, Any]] = []
    try:
        iterator = list(history)
    except Exception:  # noqa: BLE001
        return items
    for entry in iterator:
        items.append(
            {
                "url": str(getattr(entry, "url", "")),
                "status": _parse_status(getattr(entry, "status", None)),
                "headers": _headers_to_dict(getattr(entry, "headers", None)),
            }
        )
    return items


def _build_proxy(proxy: str):
    from rnet import Proxy  # type: ignore

    try:
        return Proxy.all(proxy)
    except Exception:  # noqa: BLE001
        return Proxy.http(proxy)


def _request_via_rnet(url: str, *, timeout: int, proxy: str | None, accept_html: bool = True) -> HTTPCollectionResult:
    from rnet import Emulation  # type: ignore
    import rnet.blocking  # type: ignore

    client_kwargs: dict[str, Any] = {
        "emulation": Emulation.Chrome144,
        "cookie_store": True,
        "timeout": timedelta(seconds=timeout),
        "orig_headers": DEFAULT_ORIGINAL_HEADERS,
    }
    if proxy:
        client_kwargs["proxies"] = [_build_proxy(proxy)]
    headers = dict(DEFAULT_HEADERS)
    if not accept_html:
        headers["Accept"] = "*/*"
    client = rnet.blocking.Client(**client_kwargs)
    response = client.get(url, headers=headers, orig_headers=DEFAULT_ORIGINAL_HEADERS)
    text = ""
    try:
        text = response.text()
    except Exception:  # noqa: BLE001
        text = ""
    headers_dict = _headers_to_dict(getattr(response, "headers", None))
    return HTTPCollectionResult(
        requested_url=url,
        final_url=str(getattr(response, "url", url)),
        status_code=_parse_status(getattr(response, "status", None)),
        headers=headers_dict,
        content_type=str(headers_dict.get("content-type") or headers_dict.get("Content-Type") or "") or None,
        text=text,
        history=_history_to_list(getattr(response, "history", None)),
        backend="rnet",
    )


def _follow_redirects_rnet(initial: HTTPCollectionResult, *, timeout: int, proxy: str | None, max_hops: int = 4) -> HTTPCollectionResult:
    current = initial
    history = list(initial.history)
    seen = {initial.requested_url, initial.final_url or initial.requested_url}
    hop = 0
    while hop < max_hops:
        status_code = current.status_code
        if status_code not in {301, 302, 303, 307, 308}:
            break
        location = current.headers.get("location") or current.headers.get("Location")
        if not location:
            break
        next_url = str(location)
        if next_url in seen:
            break
        seen.add(next_url)
        history.append(
            {
                "url": current.final_url or current.requested_url,
                "status": current.status_code,
                "headers": dict(current.headers),
            }
        )
        current = _request_via_rnet(next_url, timeout=timeout, proxy=proxy, accept_html=True)
        hop += 1
    current.history = history + list(current.history)
    return current


def _bytes_via_rnet(url: str, *, timeout: int, proxy: str | None, headers: dict[str, str] | None = None) -> bytes:
    from rnet import Emulation  # type: ignore
    import rnet.blocking  # type: ignore

    client_kwargs: dict[str, Any] = {
        "emulation": Emulation.Chrome144,
        "cookie_store": True,
        "timeout": timedelta(seconds=timeout),
        "orig_headers": DEFAULT_ORIGINAL_HEADERS,
    }
    if proxy:
        client_kwargs["proxies"] = [_build_proxy(proxy)]
    client = rnet.blocking.Client(**client_kwargs)
    response = client.get(url, headers=headers or DEFAULT_HEADERS, orig_headers=DEFAULT_ORIGINAL_HEADERS)
    return response.bytes()


def _request_via_requests(url: str, *, timeout: int, proxy: str | None, accept_html: bool = True, stream: bool = False):
    headers = dict(DEFAULT_HEADERS)
    if not accept_html:
        headers["Accept"] = "*/*"
    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = requests.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
        proxies=proxies,
        verify=False,
        stream=stream,
    )
    return response


def fetch_html(url: str, request: CollectionRequest) -> HTTPCollectionResult:
    ready, _ = rnet_ready()
    last_error: Exception | None = None
    if ready:
        try:
            result = _request_via_rnet(url, timeout=request.timeout_sec, proxy=request.proxy, accept_html=True)
            if result.status_code in {301, 302, 303, 307, 308} and not result.text.strip():
                result = _follow_redirects_rnet(result, timeout=request.timeout_sec, proxy=request.proxy)
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    try:
        response = _request_via_requests(url, timeout=request.timeout_sec, proxy=request.proxy, accept_html=True)
        response.encoding = response.encoding or response.apparent_encoding or "utf-8"
        return HTTPCollectionResult(
            requested_url=url,
            final_url=response.url,
            status_code=response.status_code,
            headers=dict(response.headers),
            content_type=response.headers.get("content-type"),
            text=response.text,
            history=[
                {"url": item.url, "status": item.status_code, "headers": dict(item.headers)}
                for item in response.history
            ],
            backend="requests",
        )
    except Exception as exc:  # noqa: BLE001
        error_message = str(last_error or exc)
        return HTTPCollectionResult(
            requested_url=url,
            final_url=None,
            status_code=None,
            headers={},
            content_type=None,
            text="",
            history=[],
            backend="rnet" if ready else "requests",
            error_message=error_message,
        )


def fetch_json(url: str, *, timeout: int, proxy: str | None = None) -> Any:
    ready, _ = rnet_ready()
    if ready:
        try:
            result = _request_via_rnet(url, timeout=timeout, proxy=proxy, accept_html=False)
            return json.loads(result.text)
        except Exception:  # noqa: BLE001
            pass
    response = _request_via_requests(url, timeout=timeout, proxy=proxy, accept_html=False)
    response.raise_for_status()
    return response.json()


def fetch_json_request(
    url: str,
    *,
    timeout: int,
    proxy: str | None = None,
    params: list[tuple[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    if params:
        query = urlencode(params)
        url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
    ready, _ = rnet_ready()
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)
    if ready:
        try:
            result = _request_via_rnet(url, timeout=timeout, proxy=proxy, accept_html=False)
            return json.loads(result.text)
        except Exception:  # noqa: BLE001
            pass
    response = requests.get(
        url,
        headers=merged_headers,
        timeout=timeout,
        proxies={"http": proxy, "https": proxy} if proxy else None,
        verify=False,
    )
    response.raise_for_status()
    return response.json()


def fetch_text_request(
    url: str,
    *,
    timeout: int,
    proxy: str | None = None,
    params: list[tuple[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    if params:
        query = urlencode(params)
        url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"
    ready, _ = rnet_ready()
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)
    if ready:
        try:
            result = _request_via_rnet(url, timeout=timeout, proxy=proxy, accept_html=False)
            return result.text
        except Exception:  # noqa: BLE001
            pass
    response = requests.get(
        url,
        headers=merged_headers,
        timeout=timeout,
        proxies={"http": proxy, "https": proxy} if proxy else None,
        verify=False,
    )
    response.raise_for_status()
    response.encoding = response.encoding or response.apparent_encoding or "utf-8"
    return response.text


def fetch_bytes(url: str, *, timeout: int, proxy: str | None = None, headers: dict[str, str] | None = None) -> bytes:
    ready, _ = rnet_ready()
    merged_headers = headers or DEFAULT_HEADERS
    if ready:
        try:
            return _bytes_via_rnet(url, timeout=timeout, proxy=proxy, headers=merged_headers)
        except Exception:  # noqa: BLE001
            pass
    response = requests.get(
        url,
        headers=merged_headers,
        timeout=timeout,
        proxies={"http": proxy, "https": proxy} if proxy else None,
        verify=False,
    )
    response.raise_for_status()
    return response.content


def download_file(url: str, output_path: Path, *, timeout: int, proxy: str | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    response = _request_via_requests(url, timeout=timeout, proxy=proxy, accept_html=False, stream=True)
    response.raise_for_status()
    with output_path.open("wb") as file_handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                file_handle.write(chunk)
