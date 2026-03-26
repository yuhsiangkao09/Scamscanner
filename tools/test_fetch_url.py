from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test the SurfPhish /api/scan/fetch-url endpoint."
    )
    parser.add_argument("url", help="Target URL to collect and scan.")
    parser.add_argument(
        "--api-base-url",
        default="http://127.0.0.1:8000",
        help="Backend API base URL. Default: %(default)s",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Collector timeout seconds sent to the backend. Default: %(default)s",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=180,
        help="HTTP client timeout when waiting for the backend response. Default: %(default)s",
    )
    parser.add_argument(
        "--collection-mode",
        choices=["auto", "rnet_only", "browser_required"],
        default=None,
        help="Optional collector mode override.",
    )
    parser.add_argument(
        "--cache-policy",
        choices=["reuse", "refresh", "off"],
        default=None,
        help="Optional collector cache policy override.",
    )
    parser.add_argument(
        "--artifact-profile",
        choices=["rich", "minimal"],
        default=None,
        help="Optional collector artifact profile override.",
    )
    parser.add_argument(
        "--locale",
        default=None,
        help="Optional collector locale override.",
    )
    parser.add_argument(
        "--timezone",
        default=None,
        help="Optional collector timezone override.",
    )
    parser.add_argument(
        "--fingerprint-seed",
        type=int,
        default=None,
        help="Optional collector fingerprint seed override.",
    )
    parser.add_argument(
        "--proxy",
        default="",
        help="Optional collector proxy URL.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Ask the backend collector to run browser automation in headful mode.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Request debug fields in the response.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print the full JSON response.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to save the JSON response.",
    )
    return parser


def build_payload(args: argparse.Namespace) -> dict:
    payload = {
        "url": args.url,
        "debug": args.debug,
        "timeout": args.timeout,
    }
    if args.collection_mode:
        payload["collection_mode"] = args.collection_mode
    if args.cache_policy:
        payload["cache_policy"] = args.cache_policy
    if args.artifact_profile:
        payload["artifact_profile"] = args.artifact_profile
    if args.locale:
        payload["locale"] = args.locale
    if args.timezone:
        payload["timezone"] = args.timezone
    if args.fingerprint_seed is not None:
        payload["fingerprint_seed"] = args.fingerprint_seed
    if args.headful:
        payload["headless"] = False
    if args.proxy.strip():
        payload["proxy"] = args.proxy.strip()
    return payload


def summarize_response(payload: dict) -> str:
    result = payload.get("result") or {}
    timings = payload.get("timings") or {}
    full_check = result.get("full_check_analysis") or {}
    artifacts = result.get("artifacts") or {}
    screenshot = artifacts.get("collector_screenshot") or {}

    lines = [
        f"Model prediction: {result.get('prediction', '-')}",
        f"Risk level: {result.get('risk_level', '-')}",
        f"Phishing score: {result.get('phishing_score', '-')}",
        f"Recon error: {result.get('reconstruction_error', '-')}",
        f"Threshold: {result.get('threshold', '-')}",
        f"Detail level: {result.get('detail_level', '-')}",
        f"Collector ms: {timings.get('collector_ms', '-')}",
        f"Model total ms: {timings.get('total_ms', '-')}",
    ]

    raw_html_path = artifacts.get("raw_html_path")
    if raw_html_path:
        lines.append(f"Raw HTML: {raw_html_path}")
    if screenshot:
        lines.append(f"Collector screenshot: {screenshot.get('stored_path', '-')}")

    if full_check:
        lines.extend([
            f"RealFake risk: {full_check.get('risk_level', '-')}",
            f"RealFake confidence: {full_check.get('confidence', '-')}",
            f"RealFake summary: {full_check.get('summary', '-')}",
        ])
    elif result.get("full_check_analysis_error"):
        lines.append(
            "RealFake error: "
            f"{(result.get('full_check_analysis_error') or {}).get('message', '-')}"
        )
    if result.get("collector_error"):
        lines.append(
            "Collector error: "
            f"{(result.get('collector_error') or {}).get('message', '-')}"
        )

    return "\n".join(lines)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    api_base_url = str(args.api_base_url).rstrip("/")
    endpoint = f"{api_base_url}/api/scan/fetch-url"
    payload = build_payload(args)

    try:
        response = requests.post(endpoint, json=payload, timeout=args.request_timeout)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    try:
        response_payload = response.json()
    except ValueError:
        print(f"Non-JSON response from backend: HTTP {response.status_code}", file=sys.stderr)
        print(response.text[:2000], file=sys.stderr)
        return 1

    if args.output.strip():
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(response_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"HTTP {response.status_code}")
    print(summarize_response(response_payload))

    if args.pretty or not response.ok:
        print()
        print(json.dumps(response_payload, ensure_ascii=False, indent=2))

    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
