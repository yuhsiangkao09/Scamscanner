from __future__ import annotations

import json


EMAIL_SYSTEM_PROMPT = """你是一位電子郵件安全分析師，負責判斷一封郵件是否可能是詐騙、釣魚、冒名頂替，或其他高風險郵件。

你的輸出對象是一一般使用者，所以請用自然、清楚、容易理解的中文解釋，不要使用太多術語。

分析原則：
- 只能根據提供給你的郵件內容、寄件者資訊、連結、附件、畫面截圖做判斷
- 不要憑空猜測寄件者身分
- 如果證據不足，可以判低風險，但要說明為什麼
- 若看到品牌冒用、連結網域不一致、催促付款或驗證、要求密碼/驗證碼等，要提高警覺

請只輸出以下 JSON：
{
  "is_phishing": true/false,
  "risk_level": "high" | "medium" | "low",
  "confidence": 0.0-1.0,
  "summary": "一句話總結這封信的風險",
  "signals": [
    {
      "title": "簡短標題",
      "detail": "用自然中文說明你看到的具體證據與風險"
    }
  ],
  "action": "一句話告訴使用者現在該怎麼做"
}"""


def _trim(value: str | None, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...(truncated)"


def _compact_strings(values, *, limit: int = 20, item_limit: int = 200) -> list[str]:
    unique = []
    seen = set()
    for value in values or []:
        text = _trim(str(value or ""), item_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
        if len(unique) >= limit:
            break
    return unique


def _compact_links(links, *, limit: int = 20) -> list[dict]:
    compacted = []
    seen = set()
    for link in links or []:
        if not isinstance(link, dict):
            continue
        href = _trim(link.get("href"), 400)
        text = _trim(link.get("text"), 160)
        key = (href, text)
        if not href or key in seen:
            continue
        seen.add(key)
        compacted.append({
            "text": text,
            "href": href,
        })
        if len(compacted) >= limit:
            break
    return compacted


def build_email_user_prompt(
    *,
    provider: str,
    page_url: str,
    sender_name: str,
    sender_email: str,
    subject: str,
    body_text: str,
    links,
    attachments,
    warnings,
) -> str:
    compact_links = _compact_links(links)
    compact_attachments = _compact_strings(attachments, limit=20, item_limit=160)
    compact_warnings = _compact_strings(warnings, limit=10, item_limit=240)
    trimmed_body = _trim(body_text, 5000)

    parts = [
        "請分析以下郵件是否具有詐騙或釣魚風險。",
        "",
        "== 郵件基本資訊 ==",
        f"郵件來源平台：{provider or 'unknown'}",
        f"頁面網址：{page_url or '-'}",
        f"寄件者名稱：{sender_name or '-'}",
        f"寄件者信箱：{sender_email or '-'}",
        f"主旨：{subject or '-'}",
    ]

    if compact_warnings:
        parts.extend([
            "",
            "== 平台警告 ==",
            *[f"- {warning}" for warning in compact_warnings],
        ])

    if compact_links:
        parts.extend([
            "",
            "== 郵件中的連結 ==",
            json.dumps(compact_links, ensure_ascii=False, indent=2),
        ])

    if compact_attachments:
        parts.extend([
            "",
            "== 附件名稱 ==",
            json.dumps(compact_attachments, ensure_ascii=False, indent=2),
        ])

    parts.extend([
        "",
        "== 郵件正文 ==",
        trimmed_body or "(empty)",
    ])

    return "\n".join(parts)
