"""The kanban board of a project: items, suggestions and the trash."""
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from .. import agents, board, db, users
from ..deps import api_user, fail, ok, page_user, redirect

router = APIRouter()

# POST /items/{id}/{action}: what the card and trash buttons call.
def _accept(user_id: int, item_id: int) -> bool:
    """Take a suggestion over: it is agreed and goes into the queue; the programmer takes it at once when the project
    is free (Janis, 19.11.2026: no second step)."""
    if not board.accept(user_id, item_id):
        return False
    with db.connect() as conn:
        agents.take_next(conn, int(time.time()))
    return True


ITEM_ACTIONS = {
    "accept": _accept,
    "reject": board.reject,
    "discard": board.discard,
    "restore": board.restore,
    "delete": board.delete_item,
}


@router.post("/projects/{project_id}/items")
def create_item(
    project_id: int,
    kind: str = Form(""),
    title: str = Form(""),
    user: users.User = Depends(page_user),
    details: str = Form(""),
):
    try:
        board.create_item(user.id, project_id, kind, title, details)
    except ValueError:
        pass  # empty title or foreign project: nothing is created
    return redirect(f"/projects/{project_id}")


@router.post("/projects/{project_id}/trash/empty")
def empty_trash(project_id: int, user: users.User = Depends(api_user)):
    board.empty_trash(user.id, project_id)
    return ok()


# Registered before /items/{item_id}, so that "reorder" is not taken for an id.
@router.post("/items/reorder")
async def reorder_items(request: Request, user: users.User = Depends(api_user)):
    try:
        data = await request.json()
        board.reorder(user.id, data["kind"], [int(i) for i in data["ids"]])
    except (ValueError, KeyError, TypeError):
        return fail(400)
    return ok()


@router.post("/items/{item_id}")
def rename_item(item_id: int, title: str = Form(""), user: users.User = Depends(page_user),
                details: str | None = Form(None)):
    try:
        project_id = board.update_title(user.id, item_id, title, details)
    except ValueError:
        project_id = None
    return redirect("/" if project_id is None else f"/projects/{project_id}")


@router.post("/items/{item_id}/{action}")
def item_action(item_id: int, action: str, user: users.User = Depends(api_user)):
    run = ITEM_ACTIONS.get(action)
    if run is None:
        raise HTTPException(status_code=404)
    return ok() if run(user.id, item_id) else fail(404)
