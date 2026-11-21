"""The chat window of a project page (see chat.py): ask Claude, poll for the answer, delete the history."""
from fastapi import APIRouter, Depends, Form

from .. import chat, claude_link, ui, users
from ..deps import api_user, error, fail, ok

router = APIRouter()

# ValueError text from chat.send -> (message key in i18n.py, status)
_PROBLEMS = {"claude": ("chat_err_claude", 409), "mistral": ("chat_err_mistral", 409), "custom": ("chat_err_custom", 409),
             "chatgpt": ("chat_err_chatgpt", 409),
             "busy": ("chat_err_busy", 409),
             "prompt": ("chat_err_prompt", 400), "mode": ("chat_err_prompt", 400), "none": ("chat_err_none", 409)}


def _name(provider: str, lang: str) -> str:
    return ui.ai_name(lang, provider)


@router.post("/chat/delete")
def delete_history(user: users.User = Depends(api_user)):
    """Delete the whole chat history of the logged-in user (the menu asks "are you sure" first)."""
    return ok(deleted=chat.delete_all(user.id))


@router.get("/projects/{project_id}/chat")
def messages(project_id: int, user: users.User = Depends(api_user)):
    """The latest questions and answers. A failed one carries only the kind of failure (chat.FAILURES), never the
    reason Claude Code gave. `claude` is the state of the user's connection, so the menu shows "expired" at once."""
    return ok(claude=claude_link.status(user.id), messages=[
        {"id": m.id, "prompt": m.prompt, "status": m.status, "answer": "" if m.status == "failed" else m.answer,
         "failure": chat.failure_kind(m.answer) if m.status == "failed" else "", "mode": m.mode, "model": m.model,
         "memory": m.memory_saved, "thoughts": "" if m.status == "failed" else m.thoughts.strip(),
         # the fallback (aichoice.py): another AI of the user answered; "instead" is the one asked first
         "via": _name(m.provider, user.language) if m.tried and m.status == "done" else "",
         "instead": _name(m.tried.split(",")[0], user.language) if m.tried else ""}
        for m in chat.list_messages(user.id, project_id)
    ])


@router.get("/projects/{project_id}/chat/archive")
def archive(project_id: int, user: users.User = Depends(api_user)):
    """The chat archive of the project (only the user's own; the manager never reads it)."""
    return ok(entries=[{"id": a.id, "prompt": a.prompt, "answer": a.answer, "failure": a.failure, "model": a.model,
                        "at": a.created_at} for a in chat.archive(user.id, project_id)])


@router.post("/projects/{project_id}/chat/archive/delete")
def archive_delete(project_id: int, ids: str = Form(""), user: users.User = Depends(api_user)):
    """Delete entries of the archive for good (one day; the page asks first). `ids`: numbers, comma separated."""
    numbers = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    return ok(deleted=chat.archive_delete(user.id, project_id, numbers))


@router.post("/projects/{project_id}/chat")
def ask(project_id: int, prompt: str = Form(""), user: users.User = Depends(api_user)):
    """A question to the manager; model and the web/code switch are the user's settings (routes/manager.py)."""
    try:
        message = chat.send(user.id, project_id, prompt)
    except ValueError as problem:
        key, status = _PROBLEMS.get(str(problem), (None, 404))   # "project": not found
        return error(user.language, key, status) if key else fail(404)
    return ok(id=message.id)
