# RealFake — Layer 2 Phishing Detection

透過 VLM (Kimi K2.5 via AWS Bedrock) 分析網頁截圖與結構化證據，產出可解釋的詐騙網站判斷結果。

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
aws configure  # 需要 Bedrock 存取權限 (us-west-2)
```

## 啟動 API Server

```bash
uvicorn server:app --reload --port 8000
```

## API

### POST /analyze

**Request:**

```json
{
  "url": "https://example.com",
  "screenshot": null
}
```

| 欄位 | 類型 | 說明 |
|---|---|---|
| `url` | string (必填) | 要分析的網址 |
| `screenshot` | string (選填) | base64 編碼的 PNG 截圖，不帶的話 server 會用 Playwright 自動截 |

**Response (200):**

```json
{
  "is_phishing": true,
  "risk_level": "high",
  "confidence": 0.92,
  "summary": "一句話結論",
  "signals": [
    {
      "title": "簡短標題",
      "detail": "詳細說明"
    }
  ],
  "action": "建議使用者做什麼",
  "collected_evidence": {
    "redirects": ["http://step1.com"],
    "final_url": "http://final.com",
    "external_links": [{"text": "連結文字", "domain": "example.com"}],
    "external_script_domains": ["tracker.xyz"],
    "iframes": ["https://embed.com/page"]
  }
}
```

**Error (502):**

```json
{
  "error": "錯誤描述",
  "stage": "screenshot | bedrock | parse",
  "detail": "debug 資訊"
}
```

## CLI 工具

```bash
# 分析單一 URL (自動截圖)
python analyze.py https://example.com

# 用現有截圖
python analyze.py https://example.com --screenshot shot.png

# 結果存檔
python analyze.py https://example.com -o result.json

# 批次分析
python analyze.py -f urls.txt -o logs/results

# 只產生 prompt (不呼叫模型)
python generate_prompt.py https://example.com
```

## collected_evidence 用途

`collected_evidence` 是程式端抓取的原始資料，VLM 不會重複列出這些。前端可以用來畫導向圖 (graph)：

- 以輸入 URL 為中心節點
- `redirects` → 跳轉鏈 (chain edges)
- `external_links` → 頁面上的外部連結 (outdeg edges)
- `iframes` → 嵌入的外部頁面
- `external_script_domains` → 載入的外部程式來源
