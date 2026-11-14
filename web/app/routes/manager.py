"""Settings of the manager, changed in the Manager view (Janis, 07.11.2026): model, effort level, how freely it
decides and the switch "web and code together".

They belong to the user (agents.configure, role "chef"), so they hold for everything the manager does, not only
for the chat. Only the fields that are sent change. The answer has all of them as the server has them now: after a
new model the level may have become that model's default (catalog.resolve), and the page shows that.
"""
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
