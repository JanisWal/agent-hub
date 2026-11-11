"""The owner's system actions: restart or shut down the Pi (the page itself is /admin, routes/admin.py)."""
from fastapi import APIRouter, Depends, Form, Request

from .. import power, users
from ..deps import api_user, error, fail, ok, reauth

router = APIRouter()


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
