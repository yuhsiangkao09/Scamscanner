"""
Usage:
    python scripts/generate_prompt.py https://efagh.site/some-page

Fetches the page, extracts HTML signals, gathers URL intelligence,
and prints a ready-to-paste prompt for LLM testing.
"""

import argparse
import json
import re
import socket
import ssl
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
import tldextract
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 1. Fetch page
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_page(url: str) -> dict:
    """Fetch page HTML, following redirects."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        redirects = [r.url for r in resp.history] if resp.history else []
        return {
            "html": resp.text,
            "final_url": resp.url,
            "redirects": redirects,
            "status": resp.status_code,
        }
    except Exception as e:
        return {"html": "", "final_url": url, "redirects": [], "status": None, "error": str(e)}


# ---------------------------------------------------------------------------
# 2. Extract HTML signals
# ---------------------------------------------------------------------------

KNOWN_CDNS = {
    "jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com",
    "googleapis.com", "gstatic.com", "googletagmanager.com",
    "google-analytics.com", "facebook.net", "fbcdn.net",
    "cloudflare.com", "cloudflareinsights.com",
    "jquery.com", "bootstrapcdn.com",
}


def extract_domain(url_str: str) -> str:
    ext = tldextract.extract(url_str)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain


def is_external(href: str, page_domain: str) -> bool:
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    try:
        href_domain = extract_domain(href)
        return href_domain != page_domain and href_domain != ""
    except Exception:
        return False


def is_known_cdn(domain: str) -> bool:
    return any(domain.endswith(cdn) for cdn in KNOWN_CDNS)


def extract_hidden_text(soup: BeautifulSoup) -> list[str]:
    """Find text hidden via CSS (display:none, visibility:hidden, font-size:0, color matching bg, etc.)."""
    hidden = []
    for el in soup.find_all(style=True):
        style = el.get("style", "").lower()
        is_hidden = any(pattern in style for pattern in [
            "display:none", "display: none",
            "visibility:hidden", "visibility: hidden",
            "font-size:0", "font-size: 0",
            "opacity:0", "opacity: 0",
            "color:#fff", "color: #fff",
            "color:white", "color: white",
        ])
        if is_hidden:
            text = el.get_text(strip=True)
            if text and len(text) > 3:
                hidden.append(text[:200])
    # Also check elements with hidden attribute
    for el in soup.find_all(attrs={"hidden": True}):
        text = el.get_text(strip=True)
        if text and len(text) > 3:
            hidden.append(text[:200])
    # Deduplicate
    seen = set()
    deduped = []
    for t in hidden:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped[:20]


def extract_html_signals(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    page_domain = extract_domain(url)

    # Title & meta
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag:
        meta_desc = meta_tag.get("content", "")

    # Forms
    forms = []
    for form in soup.find_all("form"):
        action = form.get("action", "")
        inputs = []
        for inp in form.find_all("input"):
            inp_type = inp.get("type", "text")
            inp_name = inp.get("name", "")
            inp_placeholder = inp.get("placeholder", "")
            inputs.append({"type": inp_type, "name": inp_name, "placeholder": inp_placeholder})
        forms.append({"action": action, "inputs": inputs})

    # External links (deduplicated by domain)
    seen_domains = set()
    external_links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if is_external(href, page_domain):
            domain = extract_domain(href)
            if domain not in seen_domains:
                seen_domains.add(domain)
                text = a.get_text(strip=True)[:50]
                external_links.append({"text": text, "domain": domain})

    # External script domains (deduplicated, known CDNs filtered)
    script_domains = set()
    for s in soup.find_all("script", src=True):
        src = s.get("src", "")
        if src.startswith("http"):
            domain = extract_domain(src)
            if not is_known_cdn(domain):
                script_domains.add(domain)

    # Iframes
    iframes = []
    for iframe in soup.find_all("iframe", src=True):
        src = iframe.get("src", "")
        if src.startswith("http") and is_external(src, page_domain):
            iframes.append(src[:200])

    # Hidden text
    hidden_text = extract_hidden_text(soup)

    # Visible text (condensed, deduplicated)
    lines = soup.get_text(separator="\n", strip=True).split("\n")
    seen_lines = set()
    deduped_lines = []
    for line in lines:
        line = line.strip()
        if line and line not in seen_lines:
            seen_lines.add(line)
            deduped_lines.append(line)
    visible_text = "\n".join(deduped_lines)
    if len(visible_text) > 2000:
        visible_text = visible_text[:2000] + "\n...(truncated)"

    return {
        "title": title,
        "meta_description": meta_desc,
        "forms": forms,
        "external_links": external_links[:30],
        "external_script_domains": sorted(script_domains),
        "iframes": iframes[:10],
        "hidden_text": hidden_text,
        "visible_text": visible_text,
    }


# ---------------------------------------------------------------------------
# 3. URL intelligence
# ---------------------------------------------------------------------------

def get_whois_age(domain: str) -> dict:
    """Try to get domain age via python-whois. Returns dict with available info."""
    try:
        import whois
        w = whois.whois(domain)
        creation = w.creation_date
        if isinstance(creation, list):
            creation = creation[0]
        if creation:
            age_days = (datetime.now(timezone.utc) - creation.replace(tzinfo=timezone.utc)).days
            return {
                "creation_date": creation.isoformat(),
                "age_days": age_days,
                "registrar": w.registrar or "unknown",
            }
    except Exception:
        pass
    return {"creation_date": None, "age_days": None, "registrar": None}


def get_ssl_info(domain: str) -> dict:
    """Get SSL certificate issuer."""
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(5)
            s.connect((domain, 443))
            cert = s.getpeercert()
            issuer = dict(x[0] for x in cert.get("issuer", []))
            not_before = cert.get("notBefore", "")
            return {
                "issuer": issuer.get("organizationName", "unknown"),
                "not_before": not_before,
            }
    except Exception:
        return {"issuer": None, "not_before": None}


def get_url_intelligence(url: str) -> dict:
    domain = extract_domain(url)
    parsed = urlparse(url)
    ext = tldextract.extract(url)

    whois_info = get_whois_age(domain)
    ssl_info = get_ssl_info(parsed.hostname or domain)

    return {
        "domain": domain,
        "subdomain": ext.subdomain or None,
        "tld": f".{ext.suffix}",
        "domain_age_days": whois_info["age_days"],
        "creation_date": whois_info["creation_date"],
        "registrar": whois_info["registrar"],
        "ssl_issuer": ssl_info["issuer"],
        "ssl_not_before": ssl_info["not_before"],
    }


# ---------------------------------------------------------------------------
# 4. Generate prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一位網頁安全分析師，負責判斷網頁是否為詐騙或假冒網站。
你的分析對象是一般民眾（包含不懂技術的長輩），所以你的輸出必須讓任何人都能立刻理解。

用詞規則：
- 不使用英文技術詞彙（不說 domain、SSL、DNS、phishing、redirect）
- 不說「釣魚網站」，說「詐騙網站」或「假冒網站」
- 所有解釋要讓沒用過電腦的人也能聽懂
- 如果需要比喻，用台灣日常生活情境

分析原則：
- 每個 signal 必須基於你實際觀察到的證據，不要猜測或編造
- 如果某個現象其實是合理的，就不要列為可疑（例如：瑞士法語區公司用法文是正常的）
- 推論的範圍要精確，不要過度概括。例如：不要說「正常公司不會用免費工具架站」，而要說「像 VTX 這種規模的電信公司不會用免費工具架站」。差別在於：小公司或新創用免費工具是合理的，但大型電信商不會
- 每個 signal 的 detail 要自然地交代：你看到什麼、為什麼這不合理、這代表什麼。但不要用「觀察：」「推理：」「結論：」這種標籤，像正常人說話一樣寫就好

請輸出以下 JSON 格式（不要輸出其他內容）：
{
  "is_phishing": true/false,
  "risk_level": "high" | "medium" | "low",
  "confidence": 0.0-1.0,
  "summary": "一句話結論，讓任何人都能立刻理解",
  "signals": [
    {
      "title": "簡短標題（10字以內）",
      "detail": "自然語言說明，涵蓋你看到什麼、為什麼不合理、代表什麼風險"
    }
  ],
  "action": "一句話告訴使用者現在該做什麼"
}"""


def build_user_prompt(url: str, page_data: dict, html_signals: dict, url_intel: dict) -> str:
    parts = []
    parts.append(f"請分析以下網頁是否為詐騙網站。\n")

    # URL info
    parts.append("== 網址資訊 ==")
    parts.append(f"原始網址：{url}")
    if page_data["final_url"] != url:
        parts.append(f"跳轉後網址：{page_data['final_url']}")
    if page_data["redirects"]:
        parts.append(f"跳轉過程：{' -> '.join(page_data['redirects'])}")

    # URL intelligence
    parts.append(f"\n== 網址背景調查 ==")
    parts.append(f"網站名稱所屬：{url_intel['domain']}")
    parts.append(f"頂級域名：{url_intel['tld']}")
    if url_intel["subdomain"]:
        parts.append(f"子域名：{url_intel['subdomain']}")
    if url_intel["domain_age_days"] is not None:
        parts.append(f"網址註冊天數：{url_intel['domain_age_days']} 天")
        parts.append(f"註冊日期：{url_intel['creation_date']}")
    else:
        parts.append("網址註冊天數：查詢失敗")
    if url_intel["registrar"]:
        parts.append(f"註冊商：{url_intel['registrar']}")
    if url_intel["ssl_issuer"]:
        parts.append(f"安全憑證簽發者：{url_intel['ssl_issuer']}")

    # HTML signals
    parts.append(f"\n== 網頁內容分析 ==")
    parts.append(f"網頁標題：{html_signals['title']}")
    if html_signals["meta_description"]:
        parts.append(f"網頁描述：{html_signals['meta_description']}")

    if html_signals["forms"]:
        parts.append(f"\n表單（共 {len(html_signals['forms'])} 個）：")
        for i, form in enumerate(html_signals["forms"]):
            parts.append(f"  表單 {i+1}: 資料送往 {form['action'] or '(同頁面)'}")
            input_desc = [f"{inp['name'] or inp['placeholder'] or inp['type']}" for inp in form["inputs"]]
            if input_desc:
                parts.append(f"    要求填寫：{', '.join(input_desc)}")

    if html_signals["external_links"]:
        parts.append(f"\n外部連結：")
        for link in html_signals["external_links"]:
            parts.append(f"  [{link['text']}] -> {link['domain']}")

    if html_signals["external_script_domains"]:
        parts.append(f"\n載入外部程式來源：{', '.join(html_signals['external_script_domains'])}")

    if html_signals["iframes"]:
        parts.append(f"\n嵌入外部頁面：")
        for src in html_signals["iframes"]:
            parts.append(f"  {src}")

    if html_signals["hidden_text"]:
        parts.append(f"\n隱藏文字（使用者看不到但網頁中存在）：")
        for text in html_signals["hidden_text"]:
            parts.append(f"  「{text}」")

    parts.append(f"\n== 網頁可見文字內容 ==")
    parts.append(html_signals["visible_text"])

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_single_url(url: str) -> str:
    """Process one URL and return the full prompt text."""
    if not url.startswith("http"):
        url = f"https://{url}"

    print(f"  [1/3] Fetching {url} ...", file=sys.stderr)
    page_data = fetch_page(url)
    if page_data.get("error"):
        print(f"    Warning: {page_data['error']}", file=sys.stderr)

    print(f"  [2/3] Extracting HTML signals ...", file=sys.stderr)
    html_signals = extract_html_signals(page_data["html"], page_data["final_url"])

    print(f"  [3/3] Gathering URL intelligence ...", file=sys.stderr)
    url_intel = get_url_intelligence(url)

    user = build_user_prompt(url, page_data, html_signals, url_intel)
    return user


def main():
    parser = argparse.ArgumentParser(description="Generate phishing analysis prompt from URL(s)")
    parser.add_argument("url", nargs="?", help="Single URL to analyze")
    parser.add_argument("--file", "-f", help="File with one URL per line")
    parser.add_argument("--output", "-o", help="Output directory for batch mode, or file for single mode")
    args = parser.parse_args()

    if not args.url and not args.file:
        parser.error("Provide a URL or --file with a list of URLs")

    # Collect URLs
    urls = []
    if args.file:
        with open(args.file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    else:
        urls.append(args.url)

    system = SYSTEM_PROMPT

    if len(urls) == 1:
        # Single URL mode
        print(f"Processing: {urls[0]}", file=sys.stderr)
        user_prompt = process_single_url(urls[0])
        output_text = f"=== SYSTEM PROMPT ===\n{system}\n\n=== USER PROMPT ===\n{user_prompt}"

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_text)
            print(f"Written to {args.output}", file=sys.stderr)
        else:
            print(output_text)
    else:
        # Batch mode
        import os
        out_dir = args.output or "logs/prompts"
        os.makedirs(out_dir, exist_ok=True)

        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] {url}", file=sys.stderr)
            try:
                user_prompt = process_single_url(url)
                domain = extract_domain(url).replace(".", "_")
                filename = f"{i:02d}_{domain}.txt"
                filepath = os.path.join(out_dir, filename)
                output_text = f"=== SYSTEM PROMPT ===\n{system}\n\n=== USER PROMPT ===\n{user_prompt}"
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(output_text)
                print(f"  -> {filepath}", file=sys.stderr)
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)

        print(f"\nDone. {len(urls)} prompts written to {out_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
