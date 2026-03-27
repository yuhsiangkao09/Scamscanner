# SurfFish Firefox Extension

This folder contains a Firefox WebExtension that can be loaded temporarily for local testing.

It does three things:

- Automatically sends the current page URL and DOM snapshot to the local SurfFish backend when an HTTP or HTTPS page is opened
- Shows a `LOW`, `MED`, `HI`, or `ERR` badge on the browser toolbar button
- Displays an in-page risk banner and a more detailed result view in the popup
- Lets the user request a detailed check that uploads a stitched full-page screenshot after consent
- Supports Chinese and English UI, plus a URL whitelist that skips future scans for trusted pages

## 1. Start the Backend API First

The backend is now configured through `backend/.env` and started with `uvicorn`.

1. Review `backend/.env`
2. Adjust `APP_MODEL_PATH`, `APP_THRESHOLD`, and `APP_ADMIN_PASSWORD`
3. Start the service from the project root:

```bash
python backend/run.py
```

You can also launch it directly with uvicorn:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## 2. Load the Extension in Firefox

1. Open `about:debugging`
2. Go to `This Firefox`
3. Click `Load Temporary Add-on...`
4. Select `manifest.json` from this folder

## 3. Adjust the Settings

After loading the extension, click the extension icon or open the options page.

Available settings:

- `API Base URL`
  Default: `http://127.0.0.1:8000`
- `Interface Language`
  Switch between Traditional Chinese and English
- `Auto scan page loads`
  Automatically scan pages after loading
- `Show in-page banner`
  Show a risk card in the top-right corner of the webpage
- `Detailed screenshot permission`
  Choose whether full-page screenshots may be uploaded `Always` or once per browser `Session`
- `Allow insecure upstream fetch`
  Tell the backend to ignore TLS certificate problems during scanning

## File Overview

- `manifest.json`
  Firefox extension manifest
- `background.js`
  Automatic scanning, badge updates, and background state management
- `content-script.js`
  In-page risk banner rendering
- `popup.html` and `popup.js`
  Toolbar popup UI
- `options.html` and `options.js`
  Extension settings page
