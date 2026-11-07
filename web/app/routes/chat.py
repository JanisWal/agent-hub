"""TEMPORARY test chat of a project page (see chat.py): ask Claude, poll for the answer."""
from fastapi import APIRouter, Depends, Form

from .. import chat, users
from ..deps import api_user, error, fail, ok

router = APIRouter()

# ValueError text from chat.send -> (message key in i18n.py, status)
_PROBLEMS = {"claude": ("chat_err_claude", 409), "busy": ("chat_err_busy", 409),
             "prompt": ("chat_err_prompt", 400)}


@router.post("/chat/delete")
def delete_history(user: users.User = Depends(api_user)):
    """Delete the whole chat history of the logged-in user (the menu asks "are you sure" first)."""
    return ok(deleted=chat.delete_all(user.id))


@router.get("/projects/{project_id}/chat")
def messages(project_id: int, user: users.User = Depends(api_user)):
    return ok(messages=[
        {"id": m.id, "prompt": m.prompt, "status": m.status, "answer": m.answer}
        for m in chat.list_messages(user.id, project_id)
    ])


@router.post("/projects/{project_id}/chat")
def ask(project_id: int, prompt: str = Form(""), user: users.User = Depends(api_user)):
    try:
        message = chat.send(user.id, project_id, prompt)
    except ValueError as problem:
        key, status = _PROBLEMS.get(str(problem), (None, 404))   # "project": not found
        return error(user.language, key, status) if key else fail(404)
    return ok(id=message.id)
