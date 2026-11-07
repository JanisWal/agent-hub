"""Agent-Hub web app: creates the FastAPI app and wires routes, static files and safety headers."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .deps import COOKIE_SECURE, ApiLoginRequired, LoginRequired, PasswordChangeRequired, fail, redirect
from .routes import accounts, auth, board, chat, claude, projects, resets, runner

# No /docs, /redoc or /openapi.json: the site is public, nobody needs the list of routes.
app = FastAPI(title="Agent-Hub", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
for router in (auth.router, resets.router, accounts.router, projects.router, board.router, chat.router, claude.router, runner.router):
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
