import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import dashboard, i18n, layout, projects, users
from .dashboard import PAGE_SIZE

app = FastAPI(title="Agent-Hub")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

COOKIE_NAME = "session"
# Set HUB_SECURE_COOKIE=1 in production (HTTPS via Cloudflare Tunnel).
COOKIE_SECURE = os.environ.get("HUB_SECURE_COOKIE") == "1"
LOGGED_IN_SCRIPTS = ["/static/dashboard.js"]

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


def login_page(error: str = "") -> str:
    message = f'<p class="error" role="alert">{error}</p>' if error else ""
    return layout.page("Anmelden", layout.fill(LOGIN_BODY, ERROR=message))


def _user(request: Request) -> users.User | None:
    return users.get_user(request.cookies.get(COOKIE_NAME))


def _logged_in_page(user: users.User, title: str, body: str) -> str:
    return layout.page(
        title, body, user.language, top_right=dashboard.settings_bar(user),
        scripts=LOGGED_IN_SCRIPTS,
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request, page: str = "1"):
    user = _user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    all_projects = projects.list_projects(user.id)
    pages = len(all_projects) // PAGE_SIZE + 1  # the free "+" tile may need a new page
    number = min(max(int(page) if page.isdigit() else 1, 1), pages)
    shown = all_projects[(number - 1) * PAGE_SIZE : number * PAGE_SIZE]
    first_project = not user.had_project and not all_projects
    body = dashboard.render(user, shown, number, pages, first_project)
    return _logged_in_page(user, i18n.t(user.language, "home"), body)


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


@app.post("/settings")
def save_settings(request: Request, display_name: str = Form(""), language: str = Form("de")):
    user = _user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if language not in i18n.LANGS:
        language = user.language
    try:
        users.set_profile(user.id, display_name, language)
    except ValueError:
        pass  # name too long: keep the old settings
    return RedirectResponse("/", status_code=303)


@app.post("/projects")
def create_project(request: Request, name: str = Form("")):
    user = _user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    try:
        projects.create_project(user.id, name)
    except ValueError:
        return RedirectResponse("/", status_code=303)
    count = len(projects.list_projects(user.id))
    return RedirectResponse(f"/?page={(count - 1) // PAGE_SIZE + 1}", status_code=303)


@app.post("/projects/reorder")
async def reorder_projects(request: Request):
    user = _user(request)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    try:
        ids = [int(i) for i in (await request.json())["ids"]]
        projects.reorder(user.id, ids)
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"ok": False}, status_code=400)
    return {"ok": True}


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_view(project_id: int, request: Request):
    user = _user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    project = projects.get_project(user.id, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    return _logged_in_page(user, project.name, dashboard.project_page(user, project))


@app.post("/projects/{project_id}/delete")
def delete_project(project_id: int, request: Request, password: str = Form("")):
    user = _user(request)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    if not users.verify_password(user.id, password):
        return JSONResponse({"ok": False}, status_code=403)
    if not projects.delete_project(user.id, project_id):
        return JSONResponse({"ok": False}, status_code=404)
    return {"ok": True}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
