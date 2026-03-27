# RealFake API Reference

Base URL: `http://localhost:8000`

啟動：`uvicorn server:app --reload --port 8000`

---

## 共用格式

### Signal

```json
{
  "title": "簡短標題（10字以內）",
  "detail": "自然語言說明，涵蓋看到什麼、為什麼不合理、代表什麼風險"
}
```

### Error Response (502)

所有 endpoint 的錯誤格式一致：

```json
{
  "error": "錯誤描述",
  "stage": "screenshot | bedrock | parse",
  "detail": "debug 資訊"
}
```

| stage | 說明 |
|---|---|
| `screenshot` | 截圖取得或解碼失敗 |
| `bedrock` | VLM 模型呼叫失敗（AWS credentials、網路等） |
| `parse` | 模型回傳的 JSON 格式不合法 |

---

## POST /analyze

分析網頁是否為詐騙網站。會抓取頁面 HTML、萃取訊號、查詢 WHOIS/SSL，再結合截圖送 VLM 判斷。

### Request

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `url` | string | 是 | 要分析的網址 |
| `screenshot` | string | 否 | base64 編碼的截圖，不帶的話 server 會用 Playwright 自動截 |
| `screenshot_format` | string | 否 | 圖片格式，預設 `png` |

```json
{
  "url": "https://example.com",
  "screenshot": null,
  "screenshot_format": null
}
```

### Response (200)

```json
{
  "is_phishing": true,
  "risk_level": "high",
  "confidence": 0.92,
  "summary": "一句話結論",
  "signals": [
    { "title": "簡短標題", "detail": "詳細說明" }
  ],
  "action": "建議使用者做什麼",
  "collected_evidence": {
    "redirects": ["http://step1.com"],
    "final_url": "http://final.com",
    "external_links": [{ "text": "連結文字", "domain": "example.com" }],
    "external_script_domains": ["tracker.xyz"],
    "iframes": ["https://embed.com/page"]
  }
}
```

### Pipeline

```
截圖（Playwright 或傳入）
  → fetch_page() — 抓 HTML、跟隨 redirects
  → extract_html_signals() — 表單、外部連結、iframe、隱藏文字
  → get_url_intelligence() — WHOIS、SSL、TLD
  → build_user_prompt() — 組裝結構化 prompt
  → call_bedrock() — Kimi K2.5 推論
  → 附上 collected_evidence → 回傳
```

---

## POST /analyze-email

分析 Email 是否為詐騙/釣魚郵件。

### Request

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `provider` | string | 否 | 郵件平台，預設 `gmail` |
| `page_url` | string | 是 | 郵件所在頁面 URL |
| `sender_name` | string | 否 | 寄件者名稱 |
| `sender_email` | string | 否 | 寄件者信箱 |
| `subject` | string | 否 | 郵件主旨 |
| `body_text` | string | 否 | 郵件正文 |
| `links` | array | 否 | 郵件中的連結 `[{ "text": "...", "href": "..." }]` |
| `attachments` | array | 否 | 附件名稱 `["file.pdf"]` |
| `warnings` | array | 否 | 平台警告訊息 |
| `screenshot` | string | 否 | base64 編碼的截圖 |
| `screenshot_format` | string | 否 | 圖片格式，預設 `jpeg` |

### Response (200)

```json
{
  "is_phishing": true,
  "risk_level": "high",
  "confidence": 0.88,
  "summary": "一句話結論",
  "signals": [
    { "title": "簡短標題", "detail": "詳細說明" }
  ],
  "action": "建議使用者做什麼",
  "collected_evidence": {
    "provider": "gmail",
    "page_url": "https://mail.google.com/...",
    "sender_name": "某某銀行",
    "sender_email": "fake@example.com",
    "subject": "緊急通知",
    "links": [{ "text": "點此驗證", "href": "https://..." }],
    "attachments": [],
    "warnings": ["此郵件來自外部寄件者"]
  }
}
```

### Pipeline

```
content script 抽取 email metadata
  → build_email_user_prompt() — 組裝 email 專用 prompt
  → call_bedrock() — Kimi K2.5 推論（含截圖如有提供）
  → 附上 collected_evidence → 回傳
```

---

## POST /analyze-image

純截圖分析。不需要 URL，適用於簡訊詐騙、通訊軟體對話、社群廣告、App 畫面等無法用 URL 分析的場景。

### Request

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `screenshot` | string | 是 | base64 編碼的截圖 |
| `screenshot_format` | string | 否 | 圖片格式，預設 `png` |
| `context` | string | 否 | 使用者補充說明（例如「我爸收到的簡訊」） |

```json
{
  "screenshot": "iVBORw0KGgo...",
  "screenshot_format": "png",
  "context": "我爸收到的簡訊"
}
```

### Response (200)

```json
{
  "is_scam": true,
  "risk_level": "high",
  "confidence": 0.95,
  "summary": "這是假扮銀行的投資詐騙簡訊，想騙你加LINE後推銷假投資",
  "signals": [
    { "title": "陌生信箱發簡訊", "detail": "從 outlook.com 信箱發來，不是銀行官方號碼..." },
    { "title": "急著要你加LINE", "detail": "三則訊息都在要LINE帳號，真正的銀行不會這樣..." }
  ],
  "action": "不要回覆，直接封鎖，有疑問請打官方客服電話確認",
  "collected_evidence": {
    "source_type": "screenshot_only",
    "context": "我爸收到的簡訊"
  }
}
```

### Pipeline

```
base64 decode screenshot
  → build_image_user_prompt(context) — 簡短 prompt + 使用者補充
  → call_bedrock() — Kimi K2.5 推論（純靠截圖判斷）
  → 附上 collected_evidence → 回傳
```

### 支援的截圖類型

VLM 會自動辨識截圖內容類型，包括但不限於：

- 手機簡訊
- LINE / WhatsApp / Messenger 對話
- 社群媒體貼文或廣告
- App 內頁面或通知
- 網頁畫面
- 電子郵件

---

## 三個 Endpoint 比較

| | `/analyze` | `/analyze-email` | `/analyze-image` |
|---|---|---|---|
| 必填輸入 | `url` | `page_url` | `screenshot` |
| 截圖 | 選填（可自動截） | 選填 | 必填 |
| 額外資料收集 | HTML + WHOIS + SSL | email metadata | 無 |
| 判斷依據 | 截圖 + 結構化證據 | 截圖 + email 欄位 | 純截圖 + optional context |
| 回應 key | `is_phishing` | `is_phishing` | `is_scam` |
| 適用場景 | 網頁/URL 分析 | Email 分析 | 簡訊、對話、廣告等 |

---

## 模型設定

| 參數 | 值 |
|---|---|
| Model | `moonshotai.kimi-k2.5` |
| Region | `us-west-2` |
| maxTokens | 2048 |
| temperature | 0.1 |
| response_format | `json_object` |
