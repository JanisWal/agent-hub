import html
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import users

app = FastAPI(title="Agent-Hub")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

COOKIE_NAME = "session"
# Set HUB_SECURE_COOKIE=1 in production (HTTPS via Cloudflare Tunnel).
COOKIE_SECURE = os.environ.get("HUB_SECURE_COOKIE") == "1"

# Shared page shell: top bar with the always-visible theme toggle (see DESIGN.md).
# The inline script applies the saved theme before first paint to avoid a flash.
SHELL = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE% – Agent-Hub</title>
<script>try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}catch(e){}</script>
<link rel="stylesheet" href="/static/theme.css">
<script src="/static/theme.js" defer></script>
</head>
<body>
<div class="orbs" aria-hidden="true"><i></i><i></i><i></i></div>
<header class="topbar">
  <span class="brand">Agent-Hub</span>
  <button id="theme-toggle" class="icon-button" type="button" aria-label="Hell oder Dunkel umschalten">
    <svg class="i-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
    <svg class="i-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
  </button>
</header>
<main>
%BODY%
</main>
</body>
</html>"""

LOGIN_BODY = """<section class="glass">
  <h1>Anmelden</h1>
  <p class="subtitle">Willkommen zurück.</p>
  %ERROR%
  <form method="post" action="/login" novalidate>
    <label>E-Mail<input type="email" name="email" required autofocus autocomplete="username" placeholder="name@beispiel.de"></label>
    <label>Passwort<input type="password" name="password" required autocomplete="current-password" placeholder="••••••••"></label>
    <button class="primary" type="submit">Anmelden</button>
  </form>
  <!-- Placeholder: password reset by e-mail is a later module. -->
  <button class="link" type="button" disabled title="Kommt später">Passwort vergessen?</button>
</section>"""

HOME_BODY = """<section class="glass">
  <h1>Agent-Hub läuft</h1>
  <p>Angemeldet als %EMAIL%</p>
  <form method="post" action="/logout"><button class="primary" type="submit">Abmelden</button></form>
</section>"""


def page(title: str, body: str) -> str:
    return SHELL.replace("%TITLE%", title).replace("%BODY%", body)


def login_page(error: str = "") -> str:
    message = f'<p class="error" role="alert">{error}</p>' if error else ""
    return page("Anmelden", LOGIN_BODY.replace("%ERROR%", message))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = users.get_user(request.cookies.get(COOKIE_NAME))
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return page("Start", HOME_BODY.replace("%EMAIL%", html.escape(user.email)))


@app.get("/login", response_class=HTMLResponse)
def login_form() -> str:
    return login_page()


@app.post("/login", response_class=HTMLResponse)
def login(email: str = Form(""), password: str = Form("")):
    user = users.check_login(email, password)
    if user is None:
        return HTMLResponse(login_page("E-Mail oder Passwort falsch."), status_code=401)
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
