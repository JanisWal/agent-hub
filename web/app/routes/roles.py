"""Settings of the programmer, tester and reviewer, changed in their views of the project page (15.11.2026): "web and
code together", model, effort level and the AI of the role. Every role is always on (22.11.2026).

Like the manager's (routes/manager.py) they belong to the user (agents.configure), not to a project. Only the fields
that are sent change; the answer has all of them as the server has them now.
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form
from fastapi.responses import Response

from .. import agents, i18n, rolepage, users
from ..deps import api_user, fail, ok

router = APIRouter()


@router.post("/roles/{role}/settings")
def role_settings(role: str, model: str = Form(""), net: str = Form(""), effort: str = Form(""),
                  provider: str = Form("-"), user: users.User = Depends(api_user)):
    if role not in rolepage.ROLES:
        return fail(400)
    try:
        agents.configure(user.id, role, model=model or None, net=net or None, effort=effort or None,
                         provider=None if provider == "-" else provider)
    except ValueError:
        return fail(400)
    mine = agents.settings(user.id)["roles"][role]
    return ok(model=mine["model"], effort=mine["effort"], net=mine["net"], provider=mine["provider"])


@router.post("/projects/{project_id}/review-focus")
def review_focus(project_id: int, text: str = Form(""), user: users.User = Depends(api_user)):
    """What the reviewer of this project looks at (Janis, 22.11.2026), saved as it is typed or dropped as a file;
    "" = the default."""
    return ok() if agents.set_review_focus(user.id, project_id, text) else fail(404)


@router.get("/projects/{project_id}/review-focus.md")
def review_focus_file(project_id: int, user: users.User = Depends(api_user)):
    """The same text as a Markdown file, to keep it or use it in another project."""
    text = agents.review_focus(user.id, project_id)
    if text is None:
        return fail(404)
    name = i18n.t(user.language, "r_focus_file")
    return Response((text + "\n") if text else "", media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
