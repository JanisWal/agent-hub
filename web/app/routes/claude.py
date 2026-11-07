"""The Claude connection of the logged-in user, as the settings drawer uses it.

Every route works on the connection of the logged-in user and nobody else's: the user comes from
the session, there is no user id in any request. The login itself is done by the runner
(routes/runner.py): the user only starts it, opens the link and types the code.
"""
from fastapi import APIRouter, Depends, Form

from .. import claude_link, users
from ..deps import api_user, fail, ok

router = APIRouter(prefix="/claude")


def _state(user_id: int) -> dict:
    status = claude_link.status(user_id)
    return {"status": status, "login_url": claude_link.login_url(user_id) if status == "connecting" else None}


@router.get("/status")
def status(user: users.User = Depends(api_user)):
    return ok(**_state(user.id))


@router.post("/connect")
def connect(user: users.User = Depends(api_user)):
    """Start the login (or pick up one that is running). Nothing happens when already connected."""
    claude_link.begin(user.id)
    return ok(**_state(user.id))


@router.post("/code")
def code(code: str = Form(""), user: users.User = Depends(api_user)):
    """The code the user got from Claude. It is handed to the runner once and never stored."""
    try:
        accepted = claude_link.submit_code(user.id, code)
    except ValueError:
        return fail(400)
    return ok() if accepted else fail(409)


@router.post("/disconnect")
def disconnect(user: users.User = Depends(api_user)):
    """Cancel a running login or remove the connection (the runner deletes the saved login)."""
    claude_link.disconnect(user.id)
    return ok()
