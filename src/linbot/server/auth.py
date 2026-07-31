"""Password gate: a server-side session in front of every page and API route.

Design (and why it can't be bypassed client-side):
- The password lives only in server config (ACCESS_PASSWORD). It is never
  embedded in any served HTML/JS, so there is nothing in "view source" to find.
- POST /login checks the password server-side (constant-time compare) and sets
  an HttpOnly cookie containing an expiry timestamp + HMAC signature. Forging
  a cookie requires the signing secret, which never leaves the server.
- Middleware in main.py rejects every request without a valid cookie before
  any route runs — the chat page and /ask simply are not served. Only /login
  and /healthz (Railway's health check) are exempt.
- Login attempts are rate-limited per client to slow brute-forcing.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

SESSION_COOKIE = "linbot_session"

router = APIRouter()


def make_session_token(secret: str, ttl_seconds: int, now: float | None = None) -> str:
    """Signed token: "<expiry>.<hmac(secret, expiry)>". Stateless — no DB row."""
    expiry = int((now if now is not None else time.time()) + ttl_seconds)
    sig = hmac.new(secret.encode(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def verify_session_token(secret: str, token: str, now: float | None = None) -> bool:
    expiry_str, _, sig = token.partition(".")
    if not expiry_str.isdigit() or not sig:
        return False
    if int(expiry_str) < (now if now is not None else time.time()):
        return False
    expected = hmac.new(secret.encode(), expiry_str.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _login_page(error: str | None = None) -> str:
    error_html = f'<p class="err">{error}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LinBot — Sign in</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: system-ui, -apple-system, sans-serif;
    background: light-dark(#f6f5f2, #191a1c); color: light-dark(#222, #e8e6e3);
    display: flex; align-items: center; justify-content: center; height: 100dvh;
  }}
  form {{
    display: flex; flex-direction: column; gap: 12px; width: min(320px, 90vw);
    padding: 28px; border-radius: 14px;
    background: light-dark(#ffffff, #26282b);
    border: 1px solid light-dark(#e2e0da, #2c2e31);
  }}
  h1 {{ font-size: 1.15rem; margin: 0; }}
  h1 small {{ font-weight: 400; opacity: 0.55; margin-left: 6px; font-size: 0.85rem; }}
  input {{
    padding: 10px 12px; border-radius: 10px; font: inherit;
    border: 1px solid light-dark(#ccc9c0, #3a3d41);
    background: light-dark(#fff, #222427); color: inherit;
  }}
  button {{
    padding: 10px 0; border-radius: 10px; border: none; font: inherit;
    background: light-dark(#3d6b35, #4a7d42); color: #fff; cursor: pointer;
  }}
  .err {{ margin: 0; font-size: 0.85rem; color: light-dark(#a33, #e99); }}
</style>
</head>
<body>
<form method="post" action="/login">
  <h1>LinBot<small>sign in</small></h1>
  {error_html}
  <input type="password" name="password" placeholder="Password" autofocus required
         autocomplete="current-password">
  <button type="submit">Enter</button>
</form>
</body>
</html>"""


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    secret = settings.session_secret or settings.access_password
    token = request.cookies.get(SESSION_COOKIE)
    if token and verify_session_token(secret, token):
        return RedirectResponse("/", status_code=303)  # already signed in
    return HTMLResponse(_login_page())


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request) -> HTMLResponse:
    state = request.app.state
    settings = state.settings

    # Same client-id scheme as /ask; a dedicated, much tighter limiter.
    forwarded = request.headers.get("x-forwarded-for")
    client_id = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    if not state.login_limiter.allow(client_id):
        return HTMLResponse(
            _login_page("Too many attempts — try again in a minute."), status_code=429
        )

    # The form is a single urlencoded field; parsing it directly avoids the
    # python-multipart dependency Starlette's request.form() requires.
    body = (await request.body()).decode("utf-8", errors="replace")
    supplied = parse_qs(body).get("password", [""])[0]
    if not hmac.compare_digest(supplied.encode(), settings.access_password.encode()):
        return HTMLResponse(_login_page("Wrong password."), status_code=401)

    secret = settings.session_secret or settings.access_password
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(secret, settings.session_ttl_seconds),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        # Secure behind Railway's TLS proxy; plain http://localhost still works in dev.
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
        path="/",
    )
    return response
