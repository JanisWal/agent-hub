"""Settings of the manager, changed in the Manager view (Janis, 07.11.2026): model, effort level, how freely it
decides and the switch "web and code together".

They belong to the user (agents.configure, role "chef"), so they hold for everything the manager does, not only
for the chat. Only the fields that are sent change. The answer has all of them as the server has them now: after a
new model the level may have become that model's default (catalog.resolve), and the page shows that.
"""
import time

from fastapi import APIRouter, Depends, Form

from .. import agents, users
from ..deps import api_user, fail, ok

router = APIRouter()


@router.post("/manager/settings")
def manager_settings(model: str = Form(""), autonomy: str = Form(""), net: str = Form(""), effort: str = Form(""),
                     user: users.User = Depends(api_user)):
    try:
        agents.configure(user.id, "chef", model=model or None, autonomy=autonomy or None, net=net or None,
                         effort=effort or None)
    except ValueError:
        return fail(400)
    current = agents.settings(user.id)
    manager = current["roles"]["chef"]
    return ok(model=manager["model"], effort=manager["effort"], autonomy=current["autonomy"], net=manager["net"])


@router.post("/projects/{project_id}/status/again")
def status_again(project_id: int, user: users.User = Depends(api_user)):
    """Ask for a new written status now (statusnote.request): 'queued', 'wait' or 'none' (no AI); foreign is 404."""
    from .. import statusnote
    result = statusnote.request(user.id, project_id)
    return fail(404) if result == "missing" else ok(result=result)


@router.get("/projects/{project_id}/status/tile")
def status_tile(project_id: int, user: users.User = Depends(api_user)):
    """The status tile alone (Janis, 22.11.2026: its numbers must follow the board without a reload and without an AI):
    counted from the database, with the newest written status. Light enough to ask for every few seconds."""
    from .. import managerpage, status, statusnote
    assessment = status.assess(user.id, project_id)
    if assessment is None:
        return fail(404)
    return ok(html=managerpage.status_tile(user.language, assessment, int(time.time()),
                                           statusnote.latest(user.id, project_id),
                                           statusnote.writing(user.id, project_id)))


# "Waiting for you" (Janis, 19.11.2026; 22.11.2026: only decisions): the user answers the questions the manager wrote
# anew for him and decides about tasks that stopped, right in the tile. Nothing of it goes into the manager chat.
@router.post("/questions/{question_id}/answer")
def answer_question(question_id: int, answer: str = Form(""), user: users.User = Depends(api_user)):
    """The answer goes to the role that asked; a task that waited for it goes on (agents.answer_question)."""
    return ok() if agents.answer_question(user.id, question_id, answer) else fail(404)


@router.post("/tasks/{task_id}/decide")
def decide_task(task_id: int, choice: str = Form(""), hint: str = Form(""), user: users.User = Depends(api_user)):
    """again (with an optional hint for the programmer), accept or cancel a task that waits for the user."""
    if choice not in ("again", "accept", "cancel"):
        return fail(400)
    return ok() if agents.decide(user.id, task_id, choice, hint) else fail(404)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: int, user: users.User = Depends(api_user)):
    """Stop the task that is on its way (from the roles' tabs); its item goes into the trash."""
    return ok() if agents.cancel(user.id, task_id) else fail(404)
