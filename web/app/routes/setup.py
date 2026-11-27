"""The set-up assistant (setup.py, setuppage.py): before there is an owner, in the home network only and for a short
time; afterwards the owner's steps (reaching the hub, mail, backup, AI)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import db, hostjobs, i18n, mailtext, setup, setuppage, users
from ..deps import COOKIE_NAME, api_user, cookie_secure, fail, ok, redirect
from . import runner as runner_routes

router = APIRouter()


def _lang(request: Request) -> str:
    return i18n.from_header(request.headers.get("accept-language"))


def started() -> bool:
    """True once this hub was set up with the assistant (the owner was made there): only then does the start page
    send the owner back to the assistant until it is finished. A hub from before (or from a backup of one) never."""
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM server_settings WHERE key = 'setup.started'").fetchone() is not None


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, step: str = ""):
    if users.owner_exists():
        user = users.get_user(request.cookies.get(COOKIE_NAME))
        if user is None or user.must_change:
            return redirect("/login")
        if user.role != "owner":
            raise HTTPException(404)
        if step not in setup.OWNER_STEPS:
            step = "access"
        return setuppage.owner_page(user, step, _here(request))
    if setup.via_tunnel(request) or not setup.from_home(request):
        raise HTTPException(404)   # never from the internet
    lang = _lang(request)
    if not setup.open_for(request):
        return HTMLResponse(setuppage.closed_page(lang), status_code=403)
    if step == "account":
        return setuppage.account_page(lang)
    if step == "restore":
        return setuppage.restore_page(lang)
    return setuppage.check_page(lang, runner_routes.SEEN["at"])


@router.post("/setup/owner", response_class=HTMLResponse)
def make_owner(request: Request, email: str = Form(""), password: str = Form(""), password2: str = Form(""),
               language: str = Form("de")):
    """The first account: the owner. Logs him in and goes on with the assistant."""
    if not setup.open_for(request):
        raise HTTPException(404)
    lang = language if language in i18n.LANGS else _lang(request)
    problem = ("setup_password_differ" if password != password2
               else "err_pw_rules" if users.password_problem(password) else "")
    if not problem:
        try:
            user = users.create_user(email, password, role="owner")
        except users.UserError as error:
            problem = {"taken": "err_email_taken", "owner_exists": "setup_failed"}.get(error.code, "msg_email")
    if problem:
        return HTMLResponse(setuppage.account_page(lang, problem, email), status_code=400)
    users.set_profile(user.id, "", lang)
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO server_settings (key, value) VALUES ('setup.started', '1')")
    response = redirect("/setup?step=access")
    response.set_cookie(COOKIE_NAME, users.create_session(user.id), max_age=users.SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=cookie_secure(request))
    return response


def _here(request: Request) -> str:
    """The address this page was opened at, as a suggestion for the public address (never stored by itself)."""
    if setup.via_tunnel(request):
        return ""
    host = request.headers.get("host", "")
    return f"http://{host}" if host and all(c.isalnum() or c in ".:-[]" for c in host) else ""


def _owner(user: users.User):
    return None if user.role == "owner" else fail(403)


@router.post("/setup/settings")
def save_settings(kind: str = Form(""), base_url: str = Form(""), tunnel_token: str = Form(""),
                  resend_key: str = Form(""), mail_from: str = Form(""), user: users.User = Depends(api_user),
                  way: str = Form("")):
    """Reaching the hub (way, address, tunnel token) or mail (key, sender) into .env (a host job; the hub restarts).
    Empty secret fields keep what is saved. 400 with `field` for a value that can not be right.
    Ways (27.11.2026): "home" (the server's address, http or https; a tunnel set before goes), "tunnel" (https and a
    token, unless one is saved), "own" (an own https address behind an own proxy; a tunnel set before goes)."""
    denied = _owner(user)
    if denied:
        return denied
    way = way if isinstance(way, str) else ""   # called directly (tests), a default is a Form object
    values = {}
    if kind == "access":
        base_url, token = base_url.strip().rstrip("/"), tunnel_token.strip()
        if base_url and (not base_url.startswith(("https://", "http://")) or len(base_url) > 200
                         or any(c in base_url for c in " \"'<>")):
            return _bad("base_url")
        if way in ("tunnel", "own") and not base_url.startswith("https://"):
            return _bad("base_url")   # from the internet only encrypted
        if way == "home" and not base_url:
            return _bad("base_url")
        if token and (len(token) < 40 or not token.isascii() or " " in token):
            return _bad("tunnel_token")
        if way == "tunnel" and not token and not setup.current()["tunnel"]:
            return _bad("tunnel_token")
        values["HUB_BASE_URL"] = base_url
        if token and way in ("", "tunnel"):
            values["TUNNEL_TOKEN"] = token
        if way in ("home", "own"):
            values["TUNNEL_TOKEN"] = ""   # the tunnel stops
    elif kind == "mail":
        mail_from = mail_from.strip()
        if mail_from and ("@" not in mail_from or len(mail_from) > 200 or "\n" in mail_from):
            return _bad("mail_from")
        values["MAIL_FROM"] = mail_from
        if resend_key.strip():
            if not resend_key.strip().startswith("re_") or len(resend_key.strip()) > 200:
                return _bad("resend_key")
            values["RESEND_API_KEY"] = resend_key.strip()
    else:
        return fail(400)
    job = hostjobs.request("settings", {"values": values}, user.id)
    if job is None:
        return fail(409)
    return ok(job=job)


def _bad(field: str):
    from fastapi.responses import JSONResponse
    return JSONResponse({"ok": False, "field": field}, status_code=400)


@router.get("/setup/job/{job_id}")
def job_state(job_id: int, user: users.User = Depends(api_user)):
    """How a host job of the owner is doing (the page asks while the hub restarts)."""
    if not user.is_system_admin:
        return fail(403)
    state = hostjobs.state(job_id=job_id)
    return ok(state=state["state"], reason=state["detail"].get("reason", ""))


@router.post("/setup/probe/access")
def probe_access(user: users.User = Depends(api_user)):
    denied = _owner(user)
    if denied:
        return denied
    address = setup.current()["base_url"]
    found = setup.reachable(address)
    text = i18n.t(user.language, "setup_reachable" if found else "setup_not_reachable", address=address)
    return ok(found=found, text=text)


@router.post("/setup/probe/mail")
def probe_mail(user: users.User = Depends(api_user)):
    denied = _owner(user)
    if denied:
        return denied
    sent, reason = mailtext.send_test_mail(user)
    lang = user.language
    if sent:
        text = i18n.t(lang, "setup_mail_sent", email=user.email)
    elif reason in ("no_address", "not_configured", "network"):
        text = i18n.t(lang, f"setup_mail_{reason}")
    else:   # what Resend said, e.g. that the domain is not verified yet
        text = i18n.t(lang, "setup_mail_refused", reason=reason)
    return ok(found=sent, text=text)


@router.post("/setup/finish")
def finish(user: users.User = Depends(api_user)):
    denied = _owner(user)
    if denied:
        return denied
    setup.finish()
    return ok()
