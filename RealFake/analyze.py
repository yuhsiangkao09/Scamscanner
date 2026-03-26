"""
Layer 2 phishing analysis: screenshot + HTML signals + URL intelligence -> Kimi K2.5 via Bedrock.

Usage:
    python analyze.py https://example.com
    python analyze.py https://example.com --screenshot shot.png
    python analyze.py -f urls.txt -o logs/results
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import boto3
from playwright.sync_api import sync_playwright

from generate_prompt import (
    SYSTEM_PROMPT,
    build_user_prompt,
    extract_html_signals,
    fetch_page,
    get_url_intelligence,
)

MODEL_ID = "moonshotai.kimi-k2.5"
REGION = "us-west-2"


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

def take_screenshot(url: str, wait_ms: int = 3000) -> bytes:
    """Take a full-page screenshot with Playwright. Returns PNG bytes."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(url, wait_until="networkidle", timeout=20000)
        except Exception:
            # Some pages never reach networkidle; fall back to load event
            try:
                page.goto(url, wait_until="load", timeout=15000)
            except Exception:
                pass
        page.wait_for_timeout(wait_ms)
        png_bytes = page.screenshot(full_page=True)
        browser.close()
    return png_bytes


def load_screenshot(path: str) -> bytes:
    """Load a screenshot from disk."""
    return Path(path).read_bytes()


# ---------------------------------------------------------------------------
# Bedrock call
# ---------------------------------------------------------------------------

def call_bedrock(system: str, user_text: str, image_bytes: bytes | None = None) -> str:
    """Call Kimi K2.5 via Bedrock Converse API. Returns raw text response."""
    client = boto3.client("bedrock-runtime", region_name=REGION)

    # Build user content blocks
    user_content = []
    if image_bytes:
        user_content.append({
            "image": {
                "format": "png",
                "source": {"bytes": image_bytes},
            }
        })
    user_content.append({"text": user_text})

    resp = client.converse(
        modelId=MODEL_ID,
        system=[{"text": system}],
        messages=[{"role": "user", "content": user_content}],
        inferenceConfig={"maxTokens": 2048, "temperature": 0.1},
        additionalModelRequestFields={"response_format": {"type": "json_object"}},
    )

    return resp["output"]["message"]["content"][0]["text"]


# ---------------------------------------------------------------------------
# Parse VLM response
# ---------------------------------------------------------------------------

def parse_vlm_response(raw: str) -> dict:
    """Extract JSON from VLM response, handling markdown fences."""
    text = raw.strip()
    # Strip ```json ... ``` if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def analyze_url(url: str, screenshot_path: str | None = None) -> dict:
    """Full analysis pipeline for one URL. Returns parsed VLM result."""
    if not url.startswith("http"):
        url = f"https://{url}"

    # 1. Screenshot
    print(f"  [1/4] Taking screenshot ...", file=sys.stderr)
    if screenshot_path:
        image_bytes = load_screenshot(screenshot_path)
    else:
        image_bytes = take_screenshot(url)

    # 2. Fetch & extract
    print(f"  [2/4] Fetching page & extracting signals ...", file=sys.stderr)
    page_data = fetch_page(url)
    html_signals = extract_html_signals(page_data["html"], page_data["final_url"])

    # 3. URL intelligence
    print(f"  [3/4] Gathering URL intelligence ...", file=sys.stderr)
    url_intel = get_url_intelligence(url)

    # 4. Call VLM
    print(f"  [4/4] Calling Kimi K2.5 via Bedrock ...", file=sys.stderr)
    user_prompt = build_user_prompt(url, page_data, html_signals, url_intel)
    raw = call_bedrock(SYSTEM_PROMPT, user_prompt, image_bytes)

    try:
        result = parse_vlm_response(raw)
    except json.JSONDecodeError:
        result = {"raw_response": raw, "parse_error": True}

    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze URL(s) for phishing via Kimi K2.5")
    parser.add_argument("url", nargs="?", help="Single URL to analyze")
    parser.add_argument("--screenshot", "-s", help="Path to existing screenshot (skip Playwright)")
    parser.add_argument("--file", "-f", help="File with one URL per line")
    parser.add_argument("--output", "-o", help="Output file or directory (batch mode)")
    args = parser.parse_args()

    if not args.url and not args.file:
        parser.error("Provide a URL or --file with a list of URLs")

    if args.url:
        print(f"Analyzing: {args.url}", file=sys.stderr)
        result = analyze_url(args.url, args.screenshot)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Result written to {args.output}", file=sys.stderr)
        else:
            print(output)
    else:
        # Batch mode
        urls = [
            line.strip()
            for line in Path(args.file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        out_dir = Path(args.output or "logs/results")
        out_dir.mkdir(parents=True, exist_ok=True)

        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] {url}", file=sys.stderr)
            try:
                result = analyze_url(url)
                from generate_prompt import extract_domain
                domain = extract_domain(url).replace(".", "_")
                outfile = out_dir / f"{i:02d}_{domain}.json"
                outfile.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"  -> {outfile}", file=sys.stderr)
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)

        print(f"\nDone. {len(urls)} results in {out_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
