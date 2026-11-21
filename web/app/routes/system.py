"""The system actions of owner and superadmin (restart, shut down, manual backup) and server settings (upload); the page itself is
/admin, routes/admin.py."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from .. import netaddresses, power, serversettings, systempage, users
from ..deps import api_user, error, fail, ok, reauth

router = APIRouter()


@router.post("/system/power")
def power_action(
    request: Request, action: str = Form(""), confirm: str = Form(""), user: users.User = Depends(api_user)
):
    """Restart or shut down (needs the password of the one who asks), or start a backup (harmless: no password)."""
    if not user.is_system_admin:
        return fail(403)
    if action not in power.ACTIONS:
        return fail(400)
    if action != "backup":
        denied = reauth(request, user, confirm)
        if denied:
            return denied
    try:
        started = power.request_action(user, action)
    except PermissionError:
        return fail(403)
    return ok() if started else error(user.language, "err_power_busy", 409)


@router.post("/system/upload")
def upload_settings(parallel: int = Form(0), request_mb: int = Form(0), user: users.User = Depends(api_user)):
    """How uploads are cut, for the whole server (serversettings.py); saved as soon as a choice changes."""
    if not user.is_system_admin:
        return fail(403)
    try:
        serversettings.set_upload(parallel, request_mb)
    except ValueError:
        return fail(400)
    return ok()


@router.post("/system/ai")
def ai_settings(value: int = Form(-1), user: users.User = Depends(api_user)):
    """How many AI runs may go at the same time, for the whole server (serversettings.ai_parallel)."""
    if not user.is_system_admin:
        return fail(403)
    try:
        serversettings.set_ai_parallel(value)
    except ValueError:
        return fail(400)
    return ok()


def _owner_only(user: users.User):
    return None if user.role == "owner" else fail(403)


@router.post("/system/addresses")
def address_add(address: str = Form(""), user_id: str = Form("", alias="user"), note: str = Form(""),
                user: users.User = Depends(api_user)):
    """List an address of the server's network for further AIs (netaddresses.py): all accounts ("") or one. Only the
    owner (it opens his network). 400 with `field` (address, user, full); the list comes back as HTML."""
    denied = _owner_only(user)
    if denied:
        return denied
    try:
        netaddresses.add(address, int(user_id) if user_id.strip() else None, note)
    except ValueError as problem:
        field = str(problem) if str(problem) in ("address", "user", "full") else "user"
        return JSONResponse({"ok": False, "field": field}, status_code=400)
    return ok(list=systempage.address_list(user.language))


@router.post("/system/addresses/{entry_id}/remove")
def address_remove(entry_id: int, user: users.User = Depends(api_user)):
    """Take an address off the list; holds from the next job on."""
    denied = _owner_only(user)
    if denied:
        return denied
    netaddresses.remove(entry_id)
    return ok(list=systempage.address_list(user.language))


@router.get("/system/backup")
def backup_status(user: users.User = Depends(api_user)):
    """How the latest manual backup is doing: none, running, ok or failed (the page asks until it is over)."""
    if not user.is_system_admin:
        return fail(403)
    return ok(state=power.backup_state())
