# SurfPhish / Scamscan

SurfPhish is a phishing-site detection project with three connected parts:

- `backend/`: FastAPI backend for DOM-based scan, dashboard, feedback, and Full Check orchestration
- `firefox_extension/`: browser extension that sends URL + DOM for automatic scan and can trigger Full Check
- `RealFake/`: independent Layer 2 API that receives a screenshot as base64 and returns LLM-based visual analysis

## Architecture

Normal scan flow:

1. The extension sends `URL + DOM` to `backend /api/scan`
2. The backend runs the local phishing model
3. The extension popup shows the risk result

Full Check flow:

1. The user clicks `Full Check`
2. SurfPhish asks for consent
3. The extension captures a scrolling/stitching full-page screenshot
4. The extension sends `DOM + URL + stitched screenshot` to the backend
5. The backend stores the screenshot and then calls the separate `RealFake API`
6. `RealFake` receives the screenshot as base64, runs Bedrock/Kimi analysis, and returns structured results
7. The extension shows the Full Check result overlay in the browser

## Project Layout

```text
scamscan/
|- backend/
|  |- app/
|  |- .env
|  `- .env.example
|- firefox_extension/
|- RealFake/
|- models/
|- logs/
`- requirements.cpu.txt
```

## Quick Start

Open two terminals.

Terminal 1: start the main backend

```
uvicorn backend.app.main:app --host 127.0.0.1 --port 5000
```

Terminal 2: start RealFake API

```
uvicorn server:app --reload --port 9000
```

Then load the Firefox extension from:

```
scamscan/firefox_extension
```

## Backend Setup

Copy the example env file:

```

Copy-Item backend\.env.example backend\.env
```

Important backend settings in [backend/.env.example](/c:/Users/snoozedog/Desktop/workspace/0326/scamscan/backend/.env.example):

```env
APP_HOST=127.0.0.1
APP_PORT=8000
APP_ADMIN_PASSWORD=change-me-please
APP_REALFAKE_ENABLED=true
APP_REALFAKE_API_BASE_URL=http://127.0.0.1:9000
APP_REALFAKE_TIMEOUT=45
```

Notes:

- Change `APP_ADMIN_PASSWORD` before real use
- `APP_REALFAKE_ENABLED=true` lets Full Check call the separate RealFake API
- `APP_REALFAKE_API_BASE_URL` must match the RealFake server port

Install backend dependencies if needed:

```
.\.venv\Scripts\pip.exe install -r requirements.cpu.txt
```

Useful backend URLs:

- Health: `http://127.0.0.1:8000/health`
- Login: `http://127.0.0.1:8000/login`
- Dashboard: `http://127.0.0.1:8000/dashboard`

## RealFake Setup

RealFake is a separate API. The main backend does not run Bedrock directly anymore. It sends the screenshot to RealFake as base64.

Install dependencies inside your RealFake environment:

```
\RealFake
pip install -r requirements.txt
playwright install chromium
```

You also need AWS credentials with Bedrock access. If `aws` CLI is unavailable, configure credentials through either:

- `aws configure`
- `C:\Users\snoozedog\.aws\credentials`
- environment variables like `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_DEFAULT_REGION`

Recommended region:

```text
us-west-2
```

Run RealFake:

```
uvicorn server:app --reload --port 9000
```

## Extension Setup

Load the extension temporarily in Firefox:

1. Open `about:debugging`
2. Go to `This Firefox`
3. Click `Load Temporary Add-on`
4. Select [manifest.json](/c:/Users/snoozedog/Desktop/workspace/0326/scamscan/firefox_extension/manifest.json)

Open the extension popup and confirm:

- Protection is `Allow`
- API Base URL points to `http://127.0.0.1:8000`

## How To Test

### Standard scan

1. Open a website
2. Wait for auto scan, or click `Check Again` in the popup
3. The popup should show risk level, phishing score, and prediction

### Full Check

1. Open the popup
2. Click `Full Check`
3. Approve the consent prompt on the page
4. Wait for `SurfPhish is thinking...`
5. The result overlay should show:
   - risk
   - confidence
   - summary
   - recommended action
   - key signals

Even if the page currently looks benign, the popup still provides a `Full Check` button.

### Fetch-URL API

Use the CLI helper to test the backend route that accepts only a URL:

```

.\.venv\Scripts\python.exe tools\test_fetch_url.py https://example.com --pretty
```

Use a remote backend:

```
.\.venv\Scripts\python.exe tools\test_fetch_url.py https://example.com --api-base-url https://your-api-domain
```

Full endpoint guide:

- [tools/docs/fetch-url-api-guide.md](/c:/Users/snoozedog/Desktop/workspace/0326/scamscan/docs/fetch-url-api-guide.md)

## Screenshot Behavior

Current Full Check screenshot behavior:

- Uses scrolling and stitching
- Hides SurfPhish UI before capture
- Restores UI after capture
- Stores the stitched screenshot on the backend
- Stores the screenshot file and a `.base64.txt` copy
- Sends the stitched screenshot to RealFake as base64

The stitched output is currently encoded as `JPEG` before base64 upload to reduce request size.

## Logs And Artifacts

The backend stores artifacts under `logs/`.

Common paths:

- screenshots: `logs/url_scanner_screenshots`
- HTML snapshots: `logs/url_scanner_html`
- event log: `logs/url_scanner_events.jsonl`
- feedback log: `logs/url_scanner_feedback.jsonl`
- feedback HTML: `logs/url_scanner_feedback_html`

## Troubleshooting

### `Missing activeTab permission`

Reload the extension after manifest or permission changes.

### `WinError 10013` when starting RealFake

The port is already blocked or occupied. Start on another port such as `9000`.

### Bedrock `length limit exceeded`

This usually means the screenshot payload is too large. The current flow already switches the stitched upload to JPEG to reduce request size, but very tall pages may still need more compression logic in RealFake.

### `aws` is not recognized

Install AWS CLI or configure credentials manually through `.aws` files or environment variables.

## Git Workflow

Typical upload flow:

```

git status
git add .
git commit -m "your update message"
git push
```
