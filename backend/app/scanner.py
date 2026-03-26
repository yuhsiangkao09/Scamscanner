from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from .services.detector import PhishingDetector
from .services.preprocessor import URLPreprocessor
from .services.realfake import RealFakeService
from .utils import compact_text, read_event_log_by_id, read_event_log_tail


class ScannerService:
    def __init__(self, settings):
        self.settings = settings
        self.verify_tls = not settings.insecure
        self.with_domain = not settings.no_domain
        self.preprocessor = URLPreprocessor(
            save_raw_html=settings.save_raw_html,
            raw_html_dir=str(settings.raw_html_dir),
        )
        self.detector = PhishingDetector(
            model_path=str(settings.model_path),
            threshold=settings.threshold,
            with_domain=self.with_domain,
            device=settings.device,
        )
        self.realfake = RealFakeService(
            enabled=settings.realfake_enabled,
            api_base_url=settings.realfake_api_base_url,
            timeout=settings.realfake_timeout,
        )
        self.history = deque(maxlen=settings.history_limit)
        self.history_lock = asyncio.Lock()
        self.event_log_path = Path(settings.event_log_path)
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_log_lock = asyncio.Lock()
        self.feedback_log_path = Path(settings.feedback_log_path)
        self.feedback_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.feedback_log_lock = asyncio.Lock()
        self.feedback_html_dir = Path(settings.feedback_html_dir)
        self.feedback_html_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir = Path(settings.screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _log_prefix() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log_received_payload(
        self,
        *,
        input_mode,
        request_url,
        source_url,
        html_content,
        payload,
        debug,
        insecure,
        timeout,
    ) -> None:
        page_context = payload.get("page_context")
        html_encoding = str(payload.get("html_encoding", "identity") or "identity")
        compressed_size = len(payload.get("html_gzip_base64") or "")
        screenshot_size = len(payload.get("screenshot_png_base64") or "")
        print(
            f"[{self._log_prefix()}] [scan request] "
            f"mode={input_mode} request_url={request_url or '-'} source_url={source_url or '-'} "
            f"html_chars={len(html_content) if isinstance(html_content, str) else 0} "
            f"encoding={html_encoding} compressed_b64_chars={compressed_size} "
            f"screenshot_b64_chars={screenshot_size} "
            f"timeout={timeout} insecure={bool(insecure)} debug={bool(debug)}"
        )
        if page_context:
            print(
                f"[{self._log_prefix()}] [scan request] page_context="
                f"{json.dumps(page_context, ensure_ascii=False, sort_keys=True)}"
            )
        if html_content:
            print(
                f"[{self._log_prefix()}] [scan request] dom_preview="
                f"{compact_text(html_content)}"
            )

    def log_scan_result(self, *, request_url, result, timings) -> None:
        preprocess_debug = (
            (result.get("preprocess_debug") or {}) if isinstance(result, dict) else {}
        )
        raw_html_path = (
            ((result.get("artifacts") or {}).get("raw_html_path"))
            if isinstance(result, dict)
            else None
        )
        print(
            f"[{self._log_prefix()}] [scan result] "
            f"url={request_url or '-'} prediction={result.get('prediction')} "
            f"risk={result.get('risk_level')} phishing_score={result.get('phishing_score'):.4f} "
            f"reconstruction_error={result.get('reconstruction_error'):.6f} "
            f"threshold={result.get('threshold'):.6f} total_ms={float((timings or {}).get('total_ms', 0.0)):.2f}"
        )
        print(
            f"[{self._log_prefix()}] [scan result] final_url={preprocess_debug.get('final_url')} "
            f"node_count={preprocess_debug.get('node_count_without_dummy')} "
            f"edge_count={preprocess_debug.get('edge_count_before_root')} "
            f"raw_html_path={raw_html_path or preprocess_debug.get('raw_html_path')}"
        )

    def log_scan_error(self, *, request_url, input_mode, error_type, error_message) -> None:
        print(
            f"[{self._log_prefix()}] [scan error] "
            f"mode={input_mode} url={request_url or '-'} type={error_type} message={error_message}"
        )

    def _build_analysis_notes(self, graph_data):
        debug = graph_data.get("debug", {}) or {}
        notes = []

        if (
            debug.get("input_mode") == "html"
            and self.with_domain
            and debug.get("used_fallback_source_url")
        ):
            notes.append(
                "Manual HTML scan ran without source_url, so the with-domain model used "
                "the fallback domain uploaded-html.local. The score may be less reliable "
                "than a real URL scan because domain features were unavailable."
            )

        if (
            float(debug.get("unknown_tag_ratio", 0.0)) >= 0.35
            or float(debug.get("unknown_attr_ratio", 0.0)) >= 0.35
        ):
            notes.append(
                "This page contains many tags or attributes outside the model vocabulary. "
                "SpecularNet may underperform when the DOM is far from the structures seen "
                "during training."
            )

        if (
            int(debug.get("node_count_without_dummy", 0)) < 25
            or int(debug.get("edge_count_before_root", 0)) < 25
        ):
            notes.append(
                "This sample is structurally small. Scores are usually more stable on fuller "
                "DOM trees than on tiny synthetic pages."
            )

        return notes

    async def scan(self, url, debug=False, insecure=None, timeout=None):
        scan_verify = self.verify_tls if insecure is None else (not insecure)
        scan_timeout = self.settings.timeout if timeout is None else int(timeout)
        internal_debug = True
        start = time.perf_counter()

        graph_data = await asyncio.to_thread(
            self.preprocessor.process_url,
            url,
            self.with_domain,
            scan_timeout,
            scan_verify,
            internal_debug,
        )
        preprocess_done = time.perf_counter()

        result = await asyncio.to_thread(
            self.detector.predict,
            graph_data,
            self.settings.beta,
            internal_debug,
        )
        inference_done = time.perf_counter()

        result["preprocess_debug"] = graph_data.get("debug", {})
        if graph_data.get("artifacts"):
            result["artifacts"] = graph_data["artifacts"]
        analysis_notes = self._build_analysis_notes(graph_data)
        if analysis_notes:
            result["analysis_notes"] = analysis_notes

        timings = {
            "preprocess_ms": (preprocess_done - start) * 1000.0,
            "inference_ms": (inference_done - preprocess_done) * 1000.0,
            "total_ms": (inference_done - start) * 1000.0,
        }

        history_item = {
            "url": url,
            "prediction": result["prediction"],
            "risk_level": result["risk_level"],
            "phishing_score": result["phishing_score"],
            "total_ms": timings["total_ms"],
            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        raw_html_path = (result.get("artifacts") or {}).get("raw_html_path")
        if raw_html_path:
            history_item["raw_html_path"] = raw_html_path
        async with self.history_lock:
            self.history.appendleft(history_item)

        return result, timings

    async def scan_html(self, html_content, source_url, debug=False):
        del debug
        start = time.perf_counter()

        graph_data = await asyncio.to_thread(
            self.preprocessor.process_html,
            html_content,
            source_url,
            self.with_domain,
            True,
        )
        preprocess_done = time.perf_counter()

        result = await asyncio.to_thread(
            self.detector.predict,
            graph_data,
            self.settings.beta,
            True,
        )
        inference_done = time.perf_counter()

        result["preprocess_debug"] = graph_data.get("debug", {})
        if graph_data.get("artifacts"):
            result["artifacts"] = graph_data["artifacts"]
        analysis_notes = self._build_analysis_notes(graph_data)
        if analysis_notes:
            result["analysis_notes"] = analysis_notes

        timings = {
            "preprocess_ms": (preprocess_done - start) * 1000.0,
            "inference_ms": (inference_done - preprocess_done) * 1000.0,
            "total_ms": (inference_done - start) * 1000.0,
        }

        history_item = {
            "url": source_url or "[manual html upload]",
            "prediction": result["prediction"],
            "risk_level": result["risk_level"],
            "phishing_score": result["phishing_score"],
            "total_ms": timings["total_ms"],
            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "input_mode": "html",
        }
        async with self.history_lock:
            self.history.appendleft(history_item)

        return result, timings

    async def get_history(self):
        async with self.history_lock:
            return list(self.history)

    async def append_feedback_log(self, feedback_record) -> None:
        line = json.dumps(self._json_ready(feedback_record), ensure_ascii=False)
        async with self.feedback_log_lock:
            await asyncio.to_thread(
                self._append_log_line_sync,
                self.feedback_log_path,
                line,
            )

    async def get_feedback_reports(self, limit=50):
        return await asyncio.to_thread(read_event_log_tail, self.feedback_log_path, limit)

    async def get_feedback_report(self, feedback_id):
        return await asyncio.to_thread(read_event_log_by_id, self.feedback_log_path, feedback_id)

    def _json_ready(self, value):
        if isinstance(value, dict):
            return {key: self._json_ready(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, deque)):
            return [self._json_ready(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, np.generic):
            return value.item()
        return value

    def build_event_record(
        self,
        *,
        url,
        input_mode,
        debug,
        insecure,
        timeout,
        status,
        result=None,
        timings=None,
        error=None,
        http_status=None,
    ):
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "request": {
                "url": url,
                "input_mode": input_mode,
                "debug_requested": bool(debug),
                "insecure_requested": bool(insecure),
                "timeout_seconds": int(timeout),
            },
            "service_config": self.config_payload(),
            "result": self._json_ready(result) if result is not None else None,
            "timings": self._json_ready(timings) if timings is not None else None,
            "http_status": http_status,
            "error": error,
        }

    def build_feedback_record(
        self,
        *,
        feedback_id,
        kind,
        source,
        url,
        page_context,
        summary,
        html_info=None,
        notes=None,
    ):
        return {
            "id": feedback_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "source": source,
            "url": url,
            "page_context": self._json_ready(page_context) if page_context is not None else None,
            "summary": self._json_ready(summary) if summary is not None else None,
            "html_info": self._json_ready(html_info) if html_info is not None else None,
            "notes": notes or [],
            "service_config": self.config_payload(),
        }

    async def append_event_log(self, event_record) -> None:
        line = json.dumps(self._json_ready(event_record), ensure_ascii=False)
        async with self.event_log_lock:
            await asyncio.to_thread(
                self._append_log_line_sync,
                self.event_log_path,
                line,
            )

    @staticmethod
    def _append_log_line_sync(path: Path, line: str) -> None:
        with open(path, "a", encoding="utf-8") as file:
            file.write(line + "\n")

    def config_payload(self):
        return {
            "model_path": str(self.settings.model_path),
            "model_name": self.settings.model_path.name,
            "threshold": self.settings.threshold,
            "device": self.detector.device,
            "with_domain": self.with_domain,
            "verify_tls": self.verify_tls,
            "default_timeout": self.settings.timeout,
            "beta": self.settings.beta,
            "save_raw_html": self.settings.save_raw_html,
            "raw_html_dir": str(self.settings.raw_html_dir),
            "event_log_path": str(self.event_log_path),
            "feedback_log_path": str(self.feedback_log_path),
            "feedback_html_dir": str(self.feedback_html_dir),
            "screenshot_dir": str(self.screenshot_dir),
            "realfake_enabled": self.realfake.enabled,
            "realfake_api_base_url": self.realfake.api_base_url,
            "realfake_timeout": self.realfake.timeout,
        }

    def analyze_full_check(self, *, url: str, image_bytes: bytes):
        return self.realfake.analyze(
            url=url,
            image_bytes=image_bytes,
        )

    def save_feedback_html(self, url, html_content, prefix="feedback"):
        host = urlparse(url).netloc.lower() or "report"
        safe_host = "".join(
            char if char.isalnum() or char in ("-", ".") else "_"
            for char in host
        ).strip("._")
        if not safe_host:
            safe_host = "report"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        url_hash = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:12]
        output_path = self.feedback_html_dir / f"{prefix}__{timestamp}__{safe_host}__{url_hash}.html"
        with open(output_path, "w", encoding="utf-8", errors="ignore") as file:
            file.write(html_content)
        return str(output_path)

    def save_scan_screenshot(self, url, image_bytes, image_format="png", prefix="detailed"):
        host = urlparse(url).netloc.lower() or "report"
        safe_host = "".join(
            char if char.isalnum() or char in ("-", ".") else "_"
            for char in host
        ).strip("._")
        if not safe_host:
            safe_host = "report"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        url_hash = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:12]
        extension = "png" if str(image_format or "").lower() != "jpeg" else "jpg"
        output_path = self.screenshot_dir / (
            f"{prefix}__{timestamp}__{safe_host}__{url_hash}.{extension}"
        )
        base64_path = self.screenshot_dir / (
            f"{prefix}__{timestamp}__{safe_host}__{url_hash}.{extension}.base64.txt"
        )
        with open(output_path, "wb") as file:
            file.write(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        with open(base64_path, "w", encoding="utf-8") as file:
            file.write(image_base64)
        return {
            "stored_path": str(output_path),
            "base64_path": str(base64_path),
            "base64_chars": len(image_base64),
        }


def load_ui_html(ui_html_path: Path) -> str:
    return ui_html_path.read_text(encoding="utf-8")
