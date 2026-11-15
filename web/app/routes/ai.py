"""Connections of the logged-in user to AIs with an API key (ai_link.py, Mistral), as the settings drawer uses them.

Every route works on the logged-in user's own connection: the user comes from the session, there is no user id in
any request. The key is handed to the runner once and never stored here (ai_link.submit_key).
"""
from fastapi import APIRouter, Depends, Form

from .. import ai_link, aichoice, users
from ..deps import api_user, fail, ok

router = APIRouter(prefix="/ai")


@router.post("/default")
def make_default(provider: str = Form(""), user: users.User = Depends(api_user)):
    """Make one of the user's own connected AIs his standard (aichoice.py); 400 for anything else."""
    return ok(standard=aichoice.default(user.id)) if aichoice.set_default(user.id, provider) else fail(400)


def _provider(provider: str) -> str | None:
    return provider if provider in ai_link.PROVIDERS else None


@router.get("/{provider}/status")
def status(provider: str, user: users.User = Depends(api_user)):
    if not _provider(provider):
        return fail(404)
    return ok(status=ai_link.status(user.id, provider))


@router.post("/{provider}/connect")
def connect(provider: str, key: str = Form(""), user: users.User = Depends(api_user)):
    """The key the user pasted: 400 if it does not look like one, 409 while an earlier one is being checked."""
    if not _provider(provider):
        return fail(404)
    try:
        accepted = ai_link.submit_key(user.id, provider, key)
    except ValueError:
        return fail(400)
    return ok(status=ai_link.status(user.id, provider)) if accepted else fail(409)


@router.post("/{provider}/disconnect")
def disconnect(provider: str, user: users.User = Depends(api_user)):
    """Remove the connection (the runner deletes the saved key)."""
    if not _provider(provider):
        return fail(404)
    ai_link.disconnect(user.id, provider)
    return ok()
