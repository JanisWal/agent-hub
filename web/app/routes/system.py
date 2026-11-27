"""The system actions of owner and superadmin (restart and stop the hub; the backup is routes/backup.py) and server settings (upload); the page itself is
/admin, routes/admin.py."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from .. import hostjobs, netaddresses, serversettings, systempage, sysstats, users
from ..deps import api_user, error, fail, ok, reauth

router = APIRouter()


@router.post("/system/power")
def power_action(
    request: Request, action: str = Form(""), confirm: str = Form(""), user: users.User = Depends(api_user)
):
    """Restart or stop the hub (needs the password of the one who asks). Only the hub's own containers, never the server
    (Janis, 27./28.11.2026); the gate shows the maintenance page meanwhile (gate/)."""
    if not user.is_system_admin:
        return fail(403)
    if action not in POWER:
        return fail(400)
    denied = reauth(request, user, confirm)
    if denied:
        return denied
    if hostjobs.request(POWER[action], {}, user.id) is None:
        return error(user.language, "err_power_busy", 409)
    return ok()


POWER = {"reboot": "restart", "poweroff": "stop"}   # the buttons and their host jobs (hubctl)


@router.get("/system/stats")
def stats(user: users.User = Depends(api_user)):
    """Memory, processor, temperature and disk right now, formatted for the page (systempage.meters); the system block
    asks every few seconds while it is visible. Owner and superadmin."""
    if not user.is_system_admin:
        return fail(403)
    return ok(items=systempage.meters(user.language, sysstats.read()))


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


@router.post("/system/limits")
async def limits(request: Request, user: users.User = Depends(api_user)):
    """The settings a small server needs and a big one does not (serversettings.CHOICES): any of them in one form, saved
    as soon as a choice changes. Owner and superadmin; 400 for an unknown name or a value that is no choice."""
    if not user.is_system_admin:
        return fail(403)
    form = await request.form()
    try:
        changes = [(key, int(str(value))) for key, value in form.items()]
        if not changes or any(key not in serversettings.CHOICES for key, _ in changes):
            raise ValueError("name")
        for key, value in changes:
            serversettings.set_choice(key, value, serversettings.CHOICES[key])
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
