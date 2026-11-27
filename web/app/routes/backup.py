"""Backup and putting a backup back (backups.py, hostjobs.py, runner/hubctl.py).

The backup itself is for owner and superadmin; the recovery key and putting a backup back are the owner's (they decide
over everything on the server). Before there is an owner the set-up assistant may put a backup back (setup.open_for:
home network, short time).
"""
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import backuppage, backups, hostjobs, i18n, serversettings, setup, users
from ..deps import COOKIE_NAME, api_user, error, fail, ok, reauth

router = APIRouter()
PIECE_MAX = 16 * 1024 * 1024   # the page sends 8 MB pieces; under the tunnel's limit per request


def _system(user: users.User):
    return None if user.is_system_admin else fail(403)


# --- the backup ----------------------------------------------------------------------------------------------------
@router.post("/backup/key")
def make_key(request: Request, confirm: str = Form(""), user: users.User = Depends(api_user)):
    """A new recovery key; the secret half comes back once. Replacing a key asks for the password."""
    if user.role != "owner":
        return fail(403)
    if backups.recipient():
        denied = reauth(request, user, confirm)
        if denied:
            return denied
    text = backups.new_key()
    made = backuppage.key_part(user.language)   # the state line for after
    return ok(key=text, name=f"agent-hub-key-{time.strftime('%Y-%m-%d')}.txt", part=made)


@router.post("/backup/hour")
def set_hour(value: int = Form(-1), user: users.User = Depends(api_user)):
    denied = _system(user)
    if denied:
        return denied
    try:
        serversettings.set_choice("backup_hour", value, serversettings.CHOICES["backup_hour"])
    except ValueError:
        return fail(400)
    return ok()


@router.post("/backup/now")
def backup_now(user: users.User = Depends(api_user)):
    denied = _system(user)
    if denied:
        return denied
    recipient = backups.recipient()
    if not recipient:
        return error(user.language, "bk_failed_no_key", 409)
    if hostjobs.request("backup", {"recipient": recipient}, user.id) is None:
        return error(user.language, "bk_busy", 409)
    return ok()


@router.get("/backup/state")
def backup_state(user: users.User = Depends(api_user)):
    """The newest backup job and the list, for the page while a backup runs."""
    denied = _system(user)
    if denied:
        return denied
    return ok(job=backuppage.job_text(user.language), list=backuppage.list_rows(user.language, user.role == "owner"))


@router.post("/backup/download")
def ask_download(request: Request, name: str = Form(""), confirm: str = Form(""), user: users.User = Depends(api_user)):
    """The password, then a one-time address for the file (valid a minute)."""
    denied = _system(user) or reauth(request, user, confirm)
    if denied:
        return denied
    token = backups.issue_download(name)
    return ok(url=f"/backup/file?t={token}") if token else fail(404)


@router.get("/backup/file")
def download(t: str = "", user: users.User = Depends(api_user)):
    if not user.is_system_admin:
        raise HTTPException(404)
    path = backups.redeem_download(t)
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


# --- putting a backup back -----------------------------------------------------------------------------------------
def restorer(request: Request) -> users.User | None:
    """Dependency: who may put a backup back. The set-up before there is an owner (None), or the owner; 404 else."""
    if setup.open_for(request):
        return None
    user = users.get_user(request.cookies.get(COOKIE_NAME))
    if user is not None and user.role == "owner" and not user.must_change:
        return user
    raise HTTPException(404)


def _lang(request: Request, user: users.User | None) -> str:
    return user.language if user else i18n.from_header(request.headers.get("accept-language"))


@router.post("/restore/upload")
async def upload(request: Request, offset: int = 0, total: int = 0, user: users.User | None = Depends(restorer)):
    """The next piece of the backup file (raw bytes). "more" or "done"; 409 with `reason` when it must start again."""
    piece = await request.body()
    if len(piece) > PIECE_MAX or offset < 0:
        return fail(413)
    if hostjobs.busy():
        return JSONResponse({"ok": False, "reason": "busy"}, status_code=409)
    try:
        return ok(state=backups.receive(offset, piece, total))
    except ValueError as problem:
        return JSONResponse({"ok": False, "reason": str(problem), "have": backups.received()}, status_code=409)


@router.post("/restore/check")
def check(request: Request, key: str = Form(""), user: users.User | None = Depends(restorer), source: str = Form("")):
    """Open the uploaded backup, or one of the server's own backups (`source`, its name in the list; 27.11.2026),
    with the recovery key (a host job); nothing changes yet."""
    source = source if isinstance(source, str) else ""   # called directly (tests), a default is a Form object
    line = backups.key_line(key)
    if not line:
        return JSONResponse({"ok": False, "reason": "bad_key"}, status_code=400)
    payload = {"identity": line}
    if source:
        if user is None or not any(item["name"] == source for item in backups.listing()):
            return JSONResponse({"ok": False, "reason": "no_upload"}, status_code=409)
        payload["source"] = source
    elif not backups.uploaded():
        return JSONResponse({"ok": False, "reason": "no_upload"}, status_code=409)
    job = hostjobs.request("restore-check", payload, user.id if user else None)
    return ok(job=job) if job else JSONResponse({"ok": False, "reason": "busy"}, status_code=409)


def _summary(found: dict, lang: str) -> dict:
    counts = found.get("counts") or {}
    created = str(found.get("created", ""))[:16].replace("T", " ")
    if lang == "de" and len(created) >= 10:
        created = ".".join(reversed(created[:10].split("-"))) + created[10:]
    return {"created": created, "owner": found.get("owner", ""), "users": counts.get("users", 0),
            "projects": counts.get("projects", 0), "files": counts.get("files", 0),
            "size": backuppage.size_text(lang, int(found.get("size", 0))), "tunnel": bool(found.get("tunnel"))}


@router.get("/restore/state")
def state(request: Request, job: int = 0, user: users.User | None = Depends(restorer)):
    """Where putting a backup back stands: pick (no file), key (file there), checking, summary, failed (`reason`)."""
    lang = _lang(request, user)
    if job:
        current = hostjobs.state(job_id=job)
        if current["state"] in ("waiting", "running"):
            return ok(stage="checking")
        if current["state"] == "failed":
            return ok(stage="failed", reason=current["detail"].get("reason", ""), upload=backups.uploaded())
    found = backups.summary()
    if found:
        return ok(stage="summary", summary=_summary(found, lang), newer=backups.newer_than_us(found))
    return ok(stage="key" if backups.uploaded() else "pick")


@router.post("/restore/apply")
def apply(request: Request, confirm: str = Form(""), user: users.User | None = Depends(restorer)):
    """Put the checked backup in place of everything (the owner with his password). The hub restarts."""
    if user is not None:
        denied = reauth(request, user, confirm)
        if denied:
            return denied
    found = backups.summary()
    if not found:
        return JSONResponse({"ok": False, "reason": "not_checked"}, status_code=409)
    if backups.newer_than_us(found):
        return JSONResponse({"ok": False, "reason": "newer"}, status_code=409)
    backups.clear_restore_result()
    job = hostjobs.request("restore-apply", {}, user.id if user else None)
    return ok(job=job) if job else JSONResponse({"ok": False, "reason": "busy"}, status_code=409)


@router.post("/restore/cancel")
def cancel(user: users.User | None = Depends(restorer)):
    backups.forget_restore()
    return ok()


@router.get("/restore/done")
def done():
    """How the last put-back ended, for the page that waits while the hub restarts (it may have no login any more: the
    accounts came with the backup). Only "ok" or a reason, nothing of the data; only within an hour."""
    result = backups.restore_result()
    if not result or time.time() - float(result.get("at", 0)) > 3600:
        return ok(done=None)
    if not result.get("ok"):
        hostjobs.end_open("restore-apply", result.get("reason", "apply"))
    return ok(done=bool(result.get("ok")), reason=result.get("reason", ""))
