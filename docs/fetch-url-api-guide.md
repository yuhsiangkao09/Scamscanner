# Fetch-URL API Guide

This guide documents the backend endpoint:

```text
POST /api/scan/fetch-url
```

It is designed for clients that only want to send a URL.

The backend will:

1. run the existing SurfPhish model flow on the target URL
2. optionally use the collector to crawl the page
3. try to obtain a screenshot for RealFake
4. call the RealFake API when a screenshot is available
5. return the model result and the LLM result together

## Endpoint

Local example:

```text
http://127.0.0.1:8000/api/scan/fetch-url
```

Remote example:

```text
https://your-api-domain/api/scan/fetch-url
```

Method:

```text
POST
```

Content-Type:

```text
application/json
```

## Request Body

Minimum request:

```json
{
  "url": "https://example.com"
}
```

Optional fields:

```json
{
  "url": "https://example.com",
  "debug": false,
  "timeout": 20,
  "collection_mode": "browser_required",
  "cache_policy": "refresh",
  "artifact_profile": "rich",
  "locale": "en-US",
  "timezone": "UTC",
  "fingerprint_seed": 1000,
  "proxy": null,
  "headless": true
}
```

### Field Notes

- `url`: required target URL
- `debug`: when `true`, debug fields such as `preprocess_debug` are kept in `result`
- `timeout`: collector timeout in seconds
- `collection_mode`:
  - `rnet_only`: fetch HTML only, no browser screenshot
  - `browser_required`: use the browser collector and try to capture a screenshot
  - `auto`: let the collector choose based on its logic
- `cache_policy`:
  - `refresh`: best for testing
  - `reuse`: reuse previous collector bundle
  - `off`: disable collector cache
- `artifact_profile`:
  - `rich`: keep richer collector artifacts
  - `minimal`: lighter artifact bundle
- `headless`: browser collector headless mode

If you do not send these optional fields, the backend will fall back to values from `backend/.env`.

## Current Workflow

The current `fetch-url` route runs in this order:

1. client sends `url`
2. backend runs `service.scan(url)` with the existing SurfPhish model pipeline
3. backend resolves the final URL from model preprocessing
4. backend runs the collector against that URL
5. if the collector produces a screenshot, backend sends it to RealFake
6. backend returns:
   - SurfPhish model result
   - screenshot artifact path when available
   - RealFake analysis when available
   - timing breakdown

Important:

- the model result is the primary result
- collector failure does not have to fail the whole request
- RealFake only runs when a screenshot is available

## Response Shape

Successful response:

```json
{
  "result": {
    "reconstruction_error": 2.99,
    "threshold": 0.64023596,
    "threshold_benign_score": 0.08,
    "classifier_benign_score": 0.05,
    "fused_benign_score": 0.07,
    "phishing_score": 0.92,
    "prediction": "phishing",
    "error_only_prediction": "phishing",
    "risk_level": "HIGH",
    "is_phishing": true,
    "artifacts": {
      "raw_html_path": "C:\\path\\to\\raw.html",
      "collector_screenshot": {
        "stored_path": "C:\\path\\to\\screenshot.png",
        "format": "png"
      }
    },
    "detail_level": "collector_url",
    "full_check_analysis": {
      "is_phishing": true,
      "risk_level": "high",
      "confidence": 0.92,
      "summary": "....",
      "signals": [],
      "action": "....",
      "collected_evidence": {}
    }
  },
  "timings": {
    "preprocess_ms": 496.1,
    "inference_ms": 27.1,
    "collector_ms": 11087.0,
    "collector_settle_ms": 718.0,
    "full_check_analysis_ms": 23725.5,
    "total_ms": 37595.3
  }
}
```

## Error Fields Inside `result`

The endpoint may still return `HTTP 200` even if some secondary stages fail.

Possible fields:

- `result.full_check_analysis_error`
- `result.collector_error`

Examples:

```json
{
  "result": {
    "prediction": "phishing",
    "risk_level": "HIGH",
    "full_check_analysis_error": {
      "type": "RuntimeError",
      "message": "Collector did not produce a screenshot for RealFake analysis."
    }
  },
  "timings": {
    "preprocess_ms": 300.0,
    "inference_ms": 30.0,
    "total_ms": 900.0
  }
}
```

That means:

- the SurfPhish model result is still valid
- the secondary screenshot or RealFake stage failed

## Environment Settings

Relevant settings in `backend/.env`:

```env
APP_REALFAKE_ENABLED=true
APP_REALFAKE_API_BASE_URL=http://127.0.0.1:9000
APP_REALFAKE_TIMEOUT=45

APP_COLLECTOR_BROWSER_EXECUTABLE=
APP_COLLECTOR_BROWSER_USER_DATA_ROOT=data/collector_v2/browser_profiles
APP_COLLECTOR_COLLECTION_MODE=rnet_only
APP_COLLECTOR_CACHE_POLICY=refresh
APP_COLLECTOR_ARTIFACT_PROFILE=rich
APP_COLLECTOR_LOCALE=en-US
APP_COLLECTOR_TIMEZONE=UTC
APP_COLLECTOR_FINGERPRINT_SEED=1000
APP_COLLECTOR_TIMEOUT=20
APP_COLLECTOR_HEADLESS=true
```

### Two Useful Modes

HTML-only test mode:

```env
APP_COLLECTOR_COLLECTION_MODE=rnet_only
```

Behavior:

- HTML fetch works
- model result works
- no browser screenshot
- RealFake usually cannot run

Full browser mode:

```env
APP_COLLECTOR_COLLECTION_MODE=browser_required
APP_COLLECTOR_BROWSER_EXECUTABLE=C:\path\to\fingerprint-chromium\chrome.exe
```

Behavior:

- collector opens the hardened browser
- screenshot can be produced
- RealFake can run when screenshot capture succeeds

## CLI Test Tool

Use the helper tool:

```powershell
cd C:\Users\snoozedog\Desktop\workspace\0326\scamscan
.\.venv\Scripts\python.exe tools\test_fetch_url.py https://example.com --pretty
```

Use a remote backend:

```powershell
.\.venv\Scripts\python.exe tools\test_fetch_url.py https://example.com --api-base-url https://your-api-domain
```

Override collector mode for one request:

```powershell
.\.venv\Scripts\python.exe tools\test_fetch_url.py https://example.com --collection-mode browser_required --pretty
```

## Common Problems

### `fingerprint-chromium executable path is required`

You are in `browser_required` mode, but `APP_COLLECTOR_BROWSER_EXECUTABLE` is empty or invalid.

### `Collector did not produce a screenshot for RealFake analysis`

Usually one of these:

- collector is running in `rnet_only`
- browser collector failed before screenshot capture
- screenshot path was not created

### Old error still appears after you fixed config

Make sure:

- backend was fully restarted
- collector cache is `refresh` during testing
- the request is not explicitly overriding `collection_mode`

## Recommendation

For development:

1. start with `APP_COLLECTOR_COLLECTION_MODE=rnet_only`
2. confirm model-only URL flow works
3. switch to `browser_required`
4. configure `APP_COLLECTOR_BROWSER_EXECUTABLE`
5. confirm screenshot + RealFake works
