"""Settings of the manager, changed in the Manager view (Janis, 07.11.2026): model, effort level, how freely it
decides and the switch "web and code together".

They belong to the user (agents.configure, role "chef"), so they hold for everything the manager does, not only
for the chat. Only the fields that are sent change. The answer has all of them as the server has them now: after a
new model the level may have become that model's default (catalog.resolve), and the page shows that.
"""
import time

from fastapi import APIRouter, Depends, Form

from .. import agents, chat, db, i18n, questions, users
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


# "Waiting for you" (Janis, 19.11.2026): the user answers questions and decides about tasks right in the tile.
@router.post("/questions/{question_id}/answer")
def answer_question(question_id: int, answer: str = Form(""), user: users.User = Depends(api_user)):
    """The answer to a question of the manager or a role (questions.answer). A question of the manager chat goes on
    at once as the user's next chat message, so the manager works on; while another question of his runs, it waits
    and comes with the next one. A question of a run comes with the next run of its task."""
    found = questions.answer(user.id, question_id, answer)
    if found is None:
        return fail(404)
    sent = False
    if found.task_id is None:
        text = i18n.t(user.language, "w_answer_prompt", question=found.text[:600], answer=found.answer)
        try:
            chat.send(user.id, found.project_id, text[:chat.MAX_PROMPT])
            sent = True
        except ValueError:      # a question still runs, or no AI: the answer waits for the next question
            pass
        if sent:
            with db.connect() as conn:
                questions.mark_delivered(conn, found.id)
    return ok(sent=sent)


@router.post("/tasks/{task_id}/decide")
def decide_task(task_id: int, decision: str = Form(""), note: str = Form(""), user: users.User = Depends(api_user)):
    """Approve, another round (with the user's remark for the programmer) or cancel, from "waiting for you"."""
    if decision not in ("approve", "reject", "cancel"):
        return fail(400)
    return ok() if agents.decide(user.id, task_id, decision, note) else fail(404)
