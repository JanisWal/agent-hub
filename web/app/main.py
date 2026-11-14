"""Agent-Hub web app: creates the FastAPI app and wires routes, static files and safety headers."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .deps import COOKIE_SECURE, ApiLoginRequired, LoginRequired, PasswordChangeRequired, fail, redirect
from .routes import accounts, admin, ai, auth, board, chat, checks, claude, files, manager, projects, resets, runner, system

# No /docs, /redoc or /openapi.json: the site is public, nobody needs the list of routes.
app = FastAPI(title="Agent-Hub", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
for router in (auth.router, resets.router, accounts.router, admin.router, projects.router, board.router, checks.router, files.router, chat.router, manager.router, claude.router, ai.router, system.router, runner.router):
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


@app.middleware("http")
async def safety_headers(request: Request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.url.path.startswith("/static/"):
        headers.setdefault("Cache-Control", "no-store")  # pages hold personal data
    if COOKIE_SECURE:  # we are served over HTTPS
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
