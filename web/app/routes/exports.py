"""The project's code as a ZIP (exports.py): ask, ask how it goes, download. Only one's own projects."""
from fastapi import APIRouter, Depends, Form
from fastapi.responses import FileResponse

from .. import exports, users
from ..deps import api_user, fail, ok

router = APIRouter()


@router.post("/projects/{project_id}/export")
def export_request(project_id: int, task: str = Form(""), user: users.User = Depends(api_user)):
    """Ask for the main state (no `task`) or a task's branch; the answer names the request."""
    try:
        export_id = exports.request(user.id, project_id, int(task) if task.strip().isdigit() else None)
    except ValueError:
        return fail(404)
    return ok(id=export_id)


@router.get("/projects/{project_id}/export/{export_id}")
def export_state(project_id: int, export_id: int, user: users.User = Depends(api_user)):
    state = exports.state(user.id, project_id, export_id)
    return ok(state=state) if state else fail(404)


@router.get("/projects/{project_id}/export/{export_id}/download")
def export_download(project_id: int, export_id: int, user: users.User = Depends(api_user)):
    path = exports.path(user.id, project_id, export_id)
    if path is None:
        return fail(404)
    return FileResponse(path, media_type="application/zip", filename=f"code-{project_id}-{export_id}.zip")
