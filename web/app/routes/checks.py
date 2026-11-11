"""Regular checks of the Manager view: create, change, mark as done, delete."""
from fastapi import APIRouter, Depends, Form

from .. import checks, users
from ..deps import api_user, fail, ok, page_user, redirect

router = APIRouter()


@router.post("/projects/{project_id}/checks")
def create_check(
    project_id: int, text: str = Form(""), cycle: str = Form(""), user: users.User = Depends(page_user)
):
    try:
        checks.create(user.id, project_id, text, cycle)
    except ValueError:
        pass  # empty text, unknown cycle or a foreign project: nothing is created
    return redirect(f"/projects/{project_id}#manager")


@router.post("/checks/{check_id}")
def change_check(
    check_id: int, text: str = Form(""), cycle: str = Form(""), user: users.User = Depends(page_user)
):
    try:
        project_id = checks.update(user.id, check_id, text, cycle)
    except ValueError:
        project_id = None
    return redirect("/" if project_id is None else f"/projects/{project_id}#manager")


@router.post("/checks/{check_id}/done")
def check_done(check_id: int, user: users.User = Depends(api_user)):
    return ok() if checks.mark_done(user.id, check_id) else fail(404)


@router.post("/checks/{check_id}/delete")
def check_delete(check_id: int, user: users.User = Depends(api_user)):
    return ok() if checks.delete(user.id, check_id) else fail(404)
