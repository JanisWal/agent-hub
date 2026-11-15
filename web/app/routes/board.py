"""The kanban board of a project: items, suggestions and the trash."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request

from .. import agents, board, users
from ..deps import api_user, fail, ok, page_user, redirect

router = APIRouter()

# POST /items/{id}/{action}: what the card and trash buttons call.
def _agent_start(user_id: int, item_id: int) -> bool:
    try:
        agents.start_item(user_id, item_id)
    except ValueError:
        return False
    return True


def _agent_decide(decision: str):
    """The user's decision on the newest task of an item (agents.decide checks that it fits the task's state)."""
    def run(user_id: int, item_id: int) -> bool:
        task = agents.item_task(user_id, item_id)
        return task is not None and agents.decide(user_id, task.id, decision)
    return run


ITEM_ACTIONS = {
    "accept": board.accept,
    "reject": board.reject,
    "discard": board.discard,
    "restore": board.restore,
    "delete": board.delete_item,
    # the agents (Janis, 15.11.2026): an agreed item goes to the chain from its card, the user approves at the end
    "agent-start": _agent_start,
    "agent-approve": _agent_decide("approve"),
    "agent-reject": _agent_decide("reject"),
    "agent-cancel": _agent_decide("cancel"),
}


@router.post("/projects/{project_id}/items")
def create_item(
    project_id: int,
    kind: str = Form(""),
    title: str = Form(""),
    user: users.User = Depends(page_user),
):
    try:
        board.create_item(user.id, project_id, kind, title)
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
def rename_item(item_id: int, title: str = Form(""), user: users.User = Depends(page_user)):
    try:
        project_id = board.update_title(user.id, item_id, title)
    except ValueError:
        project_id = None
    return redirect("/" if project_id is None else f"/projects/{project_id}")


@router.post("/items/{item_id}/{action}")
def item_action(item_id: int, action: str, user: users.User = Depends(api_user)):
    run = ITEM_ACTIONS.get(action)
    if run is None:
        raise HTTPException(status_code=404)
    return ok() if run(user.id, item_id) else fail(404)
