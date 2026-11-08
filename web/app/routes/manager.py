"""Settings of the manager, changed in the Manager view (Janis, 07.11.2026): the model and how freely it decides.

They belong to the user (agents.configure, role "chef"), so they hold for everything the manager does, not only
for the chat. Only the fields that are sent change.
"""
from fastapi import APIRouter, Depends, Form

from .. import agents, users
from ..deps import api_user, fail, ok

router = APIRouter()


@router.post("/manager/settings")
def manager_settings(model: str = Form(""), autonomy: str = Form(""), net: str = Form(""),
                     user: users.User = Depends(api_user)):
    try:
        agents.configure(user.id, "chef", model=model or None, autonomy=autonomy or None, net=net or None)
    except ValueError:
        return fail(400)
    current = agents.settings(user.id)
    manager = current["roles"]["chef"]
    return ok(model=manager["model"], autonomy=current["autonomy"], net=manager["net"])
