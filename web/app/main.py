"""Agent-Hub web app: creates the FastAPI app and wires routes, static files and safety headers."""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .deps import ApiLoginRequired, LoginRequired, PasswordChangeRequired, fail, is_https, redirect
from .routes import (account, accounts, admin, ai, auth, backup, board, chat, checks, claude, devices, exports, files,
                     manager, memory, projects, resets, roles, runner, setup, system, todos)

# No /docs, /redoc or /openapi.json: the site is public, nobody needs the list of routes.
app = FastAPI(title="Agent-Hub", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
for router in (auth.router, resets.router, account.router, accounts.router, admin.router, projects.router, board.router, checks.router, devices.router, exports.router, files.router, chat.router, manager.router, memory.router, roles.router, todos.router, claude.router, ai.router, system.router, runner.router, setup.router, backup.router):
    app.include_router(router)


@app.exception_handler(LoginRequired)
def _login_required(request: Request, error: LoginRequired):
    return redirect("/login")


@app.exception_handler(PasswordChangeRequired)
def _password_change_required(request: Request, error: PasswordChangeRequired):
    return redirect("/password")


@app.exception_handler(ApiLoginRequired)
def _api_login_required(request: Request, error: ApiLoginRequired):
    return fail(401)


# What a page may load (14.11.2026 checklist, built 15.11.2026). Scripts only from /static: text that slips into a
# page unescaped can not run. Styles also inline (the pages set positions with style attributes). Pictures from
# anywhere over http(s): the icon of a linked website; blob: for previews the browser makes itself. Nothing may
# frame the site, post a form elsewhere or change the base address. Stored files are served with a stricter policy
# of their own (routes/files.py), which stays (setdefault).
# The shell of a device is a WebSocket to the hub itself (routes/devices.py, 17.11.2026): its wss:// address is named
# too, because older Safari versions do not count ws/wss as 'self'. The terminal (xterm.js) is a file in /static.
def _socket_origin() -> str:
    from urllib.parse import urlsplit
    base = urlsplit(os.environ.get("HUB_BASE_URL", "").strip())
    if base.scheme in ("http", "https") and base.netloc:
        return f" {'wss' if base.scheme == 'https' else 'ws'}://{base.netloc}"
    return ""


CONTENT_POLICY = "; ".join((
    "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https: http:", "media-src 'self' blob:", "connect-src 'self' blob:" + _socket_origin(),
    "object-src 'none'", "base-uri 'none'", "form-action 'self'", "frame-ancestors 'self'",
))


@app.middleware("http")
async def safety_headers(request: Request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("Content-Security-Policy", CONTENT_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.url.path.startswith("/static/"):
        headers.setdefault("Cache-Control", "no-store")  # pages hold personal data
    if is_https(request):  # we are served over HTTPS (not over the server's address in the home network)
        headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Browsers and feed readers ask for /favicon.ico on their own; the pages name the icons in <head> (layout.py)."""
    return FileResponse(Path(__file__).parent / "static" / "icon-48.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
