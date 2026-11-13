"""The dashboard and everything about projects (not the board inside a project)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import board, checks, dashboard, files, i18n, projectpage, projects, ui, users
from ..deps import api_user, fail, ok, page_user, reauth, redirect

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(page: str = "1", user: users.User = Depends(page_user)):
    pages = projects.layout(user.id)
    first_project = not user.had_project and not pages
    body = dashboard.render(user, pages, int(page) if page.isdigit() else 1, first_project)
    return ui.logged_in_page(
        user, i18n.t(user.language, "home"), body,
        scripts=dashboard.SCRIPTS, styles=dashboard.STYLES, body_class="fit",  # fits the window
    )


@router.post("/projects")
def create_project(name: str = Form(""), user: users.User = Depends(page_user)):
    try:
        project = projects.create_project(user.id, name)
    except ValueError:
        return redirect("/")
    return redirect(f"/?page={projects.display_page(user.id, project.id) or 1}")


@router.post("/projects/move")
async def move_project(request: Request, user: users.User = Depends(api_user)):
    """Drag and drop of a tile: {"id": ..., "page": 1, "index": 0}. Answers the final page."""
    try:
        data = await request.json()
        page = projects.move(user.id, int(data["id"]), int(data["page"]), int(data["index"]))
    except (ValueError, KeyError, TypeError):
        return fail(400)
    return ok(page=page)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_view(project_id: int, user: users.User = Depends(page_user)):
    project = projects.get_project(user.id, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    body = projectpage.render(
        user, project, board.list_items(user.id, project.id), checks.list_checks(user.id, project.id),
        files.list_files(user.id, project.id),
    )
    return ui.logged_in_page(
        user, project.name, body, scripts=projectpage.SCRIPTS, styles=projectpage.STYLES,
        top_center=projectpage.title_html(project, user.language), top_left=projectpage.back_html(user.language), drawer_extras=projectpage.drawer_buttons(user.language),
        body_class="project-page",
    )


@router.post("/projects/{project_id}/settings")
def project_settings(
    project_id: int, name: str = Form(""), description: str = Form(""), user: users.User = Depends(page_user)
):
    """Name and description from the Manager view. A foreign project is 404, bad input changes nothing."""
    try:
        project = projects.update_details(user.id, project_id, name, description)
    except ValueError:
        return redirect(f"/projects/{project_id}#manager")
    if project is None:
        raise HTTPException(status_code=404)
    return redirect(f"/projects/{project_id}#manager")


@router.post("/projects/{project_id}/delete")
def delete_project(
    request: Request, project_id: int, password: str = Form(""), user: users.User = Depends(api_user)
):
    """Deleting needs the password again, even though the user is logged in."""
    denied = reauth(request, user, password)
    if denied:
        return denied
    if not projects.delete_project(user.id, project_id):
        return fail(404)
    return ok()
