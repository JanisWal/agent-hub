"""The owner's system page: restart or shut down the Pi."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import i18n, power, systempage, ui, users
from ..deps import api_user, error, fail, ok, page_user, reauth

router = APIRouter()


@router.get("/system", response_class=HTMLResponse)
def system_page(user: users.User = Depends(page_user)):
    if user.role != "owner":
        raise HTTPException(404)
    return ui.logged_in_page(
        user, i18n.t(user.language, "system_title"), systempage.render(user),
        scripts=("system.js",), styles=("system.css",),
    )


@router.post("/system/power")
def power_action(
    request: Request, action: str = Form(""), confirm: str = Form(""), user: users.User = Depends(api_user)
):
    """Restart or shut down; needs the owner's password."""
    if user.role != "owner":
        return fail(403)
    if action not in power.ACTIONS:
        return fail(400)
    denied = reauth(request, user, confirm)
    if denied:
        return denied
    try:
        started = power.request_action(user, action)
    except PermissionError:
        return fail(403)
    return ok() if started else error(user.language, "err_power_busy", 409)
