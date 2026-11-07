"""Forgotten password: ask for a link by e-mail, then choose a new password with it."""
from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse

from .. import mailtext, resetpages, resets, throttle, users
from ..deps import redirect

router = APIRouter()


@router.get("/forgot", response_class=HTMLResponse)
def forgot_form() -> str:
    return resetpages.forgot_page()


@router.post("/forgot", response_class=HTMLResponse)
def forgot(request: Request, background: BackgroundTasks, email: str = Form("")):
    """Always the same answer. The mail goes out after the answer, so the time it takes does not
    show whether the address has an account either. Every request counts for the IP (same limit as
    wrong passwords, own counter), so nobody can use the form to flood a mailbox or use up the
    mail quota of the service."""
    key = "forgot:" + throttle.client_ip(request)
    wait = throttle.seconds_locked(key)
    if wait:
        return HTMLResponse(resetpages.forgot_page("login_locked", minutes=throttle.minutes(wait)), status_code=429)
    throttle.record_failure(key)
    if "@" not in email or len(email) > users.MAX_EMAIL_LENGTH:
        return HTMLResponse(resetpages.forgot_page("msg_email"), status_code=400)
    created = resets.create_token(email)
    if created:
        user, token = created
        background.add_task(mailtext.send_link_mail, "reset", user, token, resets.TOKEN_SECONDS)
    return resetpages.sent_page()


@router.get("/reset/{token}", response_class=HTMLResponse)
def reset_form(token: str):
    user = resets.user_for_token(token)
    if user is None:
        return HTMLResponse(resetpages.invalid_page(), status_code=400)
    return resetpages.reset_page(token, user.language)


@router.post("/reset/{token}", response_class=HTMLResponse)
def reset(token: str, new: str = Form(""), repeat: str = Form("")):
    user = resets.user_for_token(token)
    if user is None:
        return HTMLResponse(resetpages.invalid_page(), status_code=400)
    if new != repeat:
        return HTMLResponse(resetpages.reset_page(token, user.language, "err_pw_mismatch"), status_code=400)
    try:
        if not resets.consume(token, new):
            return HTMLResponse(resetpages.invalid_page(), status_code=400)
    except users.UserError:
        return HTMLResponse(resetpages.reset_page(token, user.language, "err_pw_rules"), status_code=400)
    return redirect("/login")
