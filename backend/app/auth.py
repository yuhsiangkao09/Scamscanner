from __future__ import annotations

import base64
import hashlib
import html
import secrets
from typing import Any

from fastapi import HTTPException, Request, status


SESSION_COOKIE_NAME = "surfphish_admin_session"
PASSWORD_HASH_ITERATIONS = 200_000


def build_password_record(password: str) -> dict[str, str]:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return {
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "digest_b64": base64.b64encode(derived).decode("ascii"),
    }


def verify_password(password: str, record: dict[str, str] | None) -> bool:
    if not password or not record:
        return False

    salt = base64.b64decode(record["salt_b64"])
    expected = base64.b64decode(record["digest_b64"])
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return secrets.compare_digest(derived, expected)


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def build_admin_auth_state(admin_password: str) -> dict[str, Any]:
    return {
        "password_record": build_password_record(admin_password),
        "sessions": set(),
    }


def is_admin_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not token:
        return False

    sessions = request.app.state.admin_auth["sessions"]
    return token in sessions


def require_admin_api(request: Request) -> None:
    if not is_admin_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login required",
        )


def render_login_html(error_message: str = "") -> str:
    error_block = (
        f'<div class="error">{html.escape(error_message)}</div>'
        if error_message
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SurfPhish Admin Login</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #edf2f7;
      --surface: rgba(255,255,255,0.95);
      --surface-soft: rgba(248,250,252,0.88);
      --ink: #16202a;
      --muted: #5d6975;
      --line: #d6dde4;
      --accent: #155e75;
      --danger: #b91c1c;
      --shadow: 0 24px 64px rgba(15, 23, 42, 0.12);
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0d1318;
        --surface: rgba(20,26,33,0.96);
        --surface-soft: rgba(24,32,42,0.94);
        --ink: #e6edf3;
        --muted: #98a6b2;
        --line: #26313c;
        --accent: #7dd3fc;
        --danger: #f87171;
        --shadow: 0 24px 54px rgba(0,0,0,0.40);
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      background:
        radial-gradient(circle at top left, rgba(21,94,117,0.16), transparent 34%),
        radial-gradient(circle at 88% 12%, rgba(183,79,42,0.16), transparent 26%),
        linear-gradient(180deg, var(--bg), color-mix(in srgb, var(--bg) 78%, black 6%));
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    .card {{
      width: min(960px, 100%);
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      overflow: hidden;
      border-radius: 28px;
      background: var(--surface);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    .brand {{
      padding: 34px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-soft) 70%, transparent), transparent),
        var(--surface-soft);
      border-right: 1px solid var(--line);
    }}
    .form-panel {{
      padding: 34px;
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    h1 {{
      margin: 0;
      font-size: 42px;
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    p {{
      margin: 14px 0 0;
      color: var(--muted);
      line-height: 1.65;
    }}
    form {{
      display: grid;
      gap: 14px;
      margin-top: 20px;
    }}
    label {{
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    input {{
      width: 100%;
      margin-top: 8px;
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.86);
      color: var(--ink);
      font: inherit;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 14px 18px;
      background: linear-gradient(135deg, var(--accent), #d27947);
      color: #fff8f1;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 16px 30px rgba(21, 94, 117, 0.24);
    }}
    .error {{
      margin-top: 18px;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
      background: color-mix(in srgb, var(--danger) 10%, transparent);
      color: var(--danger);
      font-size: 14px;
    }}
    .fact-list {{
      display: grid;
      gap: 14px;
      margin-top: 26px;
    }}
    .fact {{
      padding: 16px 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.46);
    }}
    .fact strong {{
      display: block;
      margin-bottom: 6px;
      font-size: 14px;
    }}
    .fact span {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
    }}
    @media (max-width: 780px) {{
      .card {{
        grid-template-columns: 1fr;
      }}
      .brand {{
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
    }}
  </style>
</head>
<body>
  <div class="card">
    <section class="brand">
      <p class="eyebrow">SurfPhish</p>
      <h1>Scanner Dashboard</h1>
      <p>Sign in to view the protected scanning dashboard, recent events, and user feedback reports.</p>
      <div class="fact-list">
        <div class="fact">
          <strong>FastAPI backend</strong>
          <span>The service now runs with a dedicated app entrypoint and environment-based configuration.</span>
        </div>
        <div class="fact">
          <strong>Protected dashboard</strong>
          <span>Dashboard and admin APIs require the administrator password stored in your backend environment.</span>
        </div>
      </div>
    </section>
    <section class="form-panel">
      <p class="eyebrow">Admin Access</p>
      <h1>Login</h1>
      <p>Use the administrator password from <code>backend/.env</code>.</p>
      <form method="post" action="/login">
        <label>
          Password
          <input name="password" type="password" autocomplete="current-password" required>
        </label>
        <button type="submit">Open Dashboard</button>
      </form>
      {error_block}
    </section>
  </div>
</body>
</html>"""
