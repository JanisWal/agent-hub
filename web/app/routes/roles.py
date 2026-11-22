"""Settings of the programmer, tester and reviewer, changed in their views of the project page (15.11.2026): on or off
(not the programmer), "web and code together", model and effort level.

Like the manager's (routes/manager.py) they belong to the user (agents.configure), not to a project. Only the fields
that are sent change; the answer has all of them as the server has them now.
"""
from fastapi import APIRouter, Depends, Form

from .. import agents, rolepage, users
from ..deps import api_user, fail, ok

router = APIRouter()


@router.post("/roles/{role}/settings")
def role_settings(role: str, enabled: str = Form(""), model: str = Form(""), net: str = Form(""),
                  effort: str = Form(""), provider: str = Form("-"), user: users.User = Depends(api_user)):
    if role not in rolepage.ROLES or enabled not in ("", "0", "1"):
        return fail(400)
    try:
        agents.configure(user.id, role, enabled=None if enabled == "" else enabled == "1", model=model or None,
                         net=net or None, effort=effort or None, provider=None if provider == "-" else provider)
    except ValueError:
        return fail(400)
    mine = agents.settings(user.id)["roles"][role]
    return ok(enabled="1" if mine["enabled"] else "0", model=mine["model"], effort=mine["effort"], net=mine["net"],
              provider=mine["provider"])
