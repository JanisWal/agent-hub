import html
import os

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import users

app = FastAPI(title="Agent-Hub")

COOKIE_NAME = "session"
# Set HUB_SECURE_COOKIE=1 in production (HTTPS via Cloudflare Tunnel).
COOKIE_SECURE = os.environ.get("HUB_SECURE_COOKIE") == "1"

LOGIN_PAGE = """<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>Anmelden – Agent-Hub</title></head>
<body>
<h1>Anmelden</h1>
{error}
<form method="post" action="/login">
  <p><label>E-Mail<br><input type="email" name="email" required autofocus></label></p>
  <p><label>Passwort<br><input type="password" name="password" required></label></p>
  <p><button type="submit">Anmelden</button></p>
</form>
</body>
</html>"""

HOME_PAGE = """<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>Agent-Hub</title></head>
<body>
<h1>Agent-Hub läuft</h1>
<p>Angemeldet als {email}</p>
<form method="post" action="/logout"><button type="submit">Abmelden</button></form>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = users.get_user(request.cookies.get(COOKIE_NAME))
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return HOME_PAGE.format(email=html.escape(user.email))


@app.get("/login", response_class=HTMLResponse)
def login_form() -> str:
    return LOGIN_PAGE.format(error="")


@app.post("/login", response_class=HTMLResponse)
def login(email: str = Form(...), password: str = Form(...)):
    user = users.check_login(email, password)
    if user is None:
        error = "<p><strong>E-Mail oder Passwort falsch.</strong></p>"
        return HTMLResponse(LOGIN_PAGE.format(error=error), status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        users.create_session(user.id),
        max_age=users.SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return response


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        users.delete_session(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
