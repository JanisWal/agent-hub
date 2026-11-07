import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import board, dashboard, i18n, layout, projectpage, projects, users
from .dashboard import PAGE_SIZE

app = FastAPI(title="Agent-Hub")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

COOKIE_NAME = "session"
# Set HUB_SECURE_COOKIE=1 in production (HTTPS via Cloudflare Tunnel).
COOKIE_SECURE = os.environ.get("HUB_SECURE_COOKIE") == "1"
LOGGED_IN_SCRIPTS = ["/static/dashboard.js"]
BOARD_SCRIPTS = LOGGED_IN_SCRIPTS + ["/static/board.js"]

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


def _logged_in_page(user: users.User, title: str, body: str, scripts=None) -> str:
    return layout.page(
        title, body, user.language, top_right=dashboard.settings_bar(user),
        scripts=scripts or LOGGED_IN_SCRIPTS,
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
    items = board.list_items(user.id, project.id)
    body = projectpage.render(user, project, items)
    return _logged_in_page(user, project.name, body, BOARD_SCRIPTS)


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


@app.post("/projects/{project_id}/items")
def create_item(project_id: int, request: Request, kind: str = Form(""), title: str = Form("")):
    user = _user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    try:
        board.create_item(user.id, project_id, kind, title)
    except ValueError:
        pass  # empty title or foreign project: nothing is created
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.post("/projects/{project_id}/trash/empty")
def empty_trash(project_id: int, request: Request):
    user = _user(request)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    board.empty_trash(user.id, project_id)
    return {"ok": True}


@app.post("/items/reorder")
async def reorder_items(request: Request):
    user = _user(request)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    try:
        data = await request.json()
        board.reorder(user.id, data["kind"], [int(i) for i in data["ids"]])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"ok": False}, status_code=400)
    return {"ok": True}


@app.post("/items/{item_id}")
def rename_item(item_id: int, request: Request, title: str = Form("")):
    user = _user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    try:
        project_id = board.update_title(user.id, item_id, title)
    except ValueError:
        project_id = None
    if project_id is None:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


ITEM_ACTIONS = {
    "accept": board.accept,
    "reject": board.reject,
    "discard": board.discard,
    "restore": board.restore,
    "delete": board.delete_item,
}


@app.post("/items/{item_id}/{action}")
def item_action(item_id: int, action: str, request: Request):
    user = _user(request)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    run = ITEM_ACTIONS.get(action)
    if run is None:
        raise HTTPException(status_code=404)
    if not run(user.id, item_id):
        return JSONResponse({"ok": False}, status_code=404)
    return {"ok": True}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
