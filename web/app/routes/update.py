"""Updating the hub from the administration (updates.py, hostjobs.py, runner/hubctl.py `update`). Only the owner: an
update replaces the code of the whole server."""
from fastapi import APIRouter, Depends, Form, Request

from .. import hostjobs, i18n, updates, users
from ..deps import api_user, error, fail, ok, reauth

router = APIRouter()
FAILURES = {"download": "upd_failed_download", "rolled_back": "upd_failed_back", "rollback_failed": "upd_failed_broken"}


def _date(lang: str, day: str) -> str:
    return ".".join(reversed(day.split("-"))) if lang == "de" and len(day) == 10 else day


def _version(lang: str, found: dict | None) -> str:
    if not found:
        return i18n.t(lang, "upd_unknown")
    return f'{_date(lang, found["date"])} ({found["commit"][:7]})'


def view(lang: str, force: bool = False) -> dict:
    """What the row shows: {"text", "available", "running", "failed", "log"}. Texts in the user's language."""
    t = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    current, newest = updates.installed(), updates.latest(force)
    job = hostjobs.state(action="update")
    running = job["state"] in ("waiting", "running")
    available = updates.available(newest, current) and not running
    if running:
        text = t("upd_running")
    elif newest is None:
        text = t("upd_unreachable", version=_version(lang, current))
    elif available:
        text = t("upd_new", version=_version(lang, current), date=_date(lang, newest["date"]))
    else:
        text = t("upd_current", version=_version(lang, current))
    failed = job["state"] == "failed" and not running
    log = job["detail"].get("log") if failed else None
    return {"text": text, "available": available, "running": running,
            "failed": t(FAILURES.get(job["detail"].get("reason"), "upd_failed")) if failed else "",
            "log": "\n".join(log) if isinstance(log, list) else ""}


def _owner(user: users.User):
    return None if user.role == "owner" and updates.allowed() else fail(403)


@router.get("/update/state")
def state(user: users.User = Depends(api_user)):
    return _owner(user) or ok(**view(user.language))


@router.post("/update/check")
def check(user: users.User = Depends(api_user)):
    """Ask the source now, not only once a day."""
    return _owner(user) or ok(**view(user.language, force=True))


@router.post("/update/start")
def start(request: Request, confirm: str = Form(""), user: users.User = Depends(api_user)):
    """Start the update (the owner's password). The hub restarts with the new version; the gate shows the maintenance
    page meanwhile."""
    denied = _owner(user) or reauth(request, user, confirm)
    if denied:
        return denied
    if hostjobs.request("update", {}, user.id) is None:
        return error(user.language, "err_power_busy", 409)
    return ok()
