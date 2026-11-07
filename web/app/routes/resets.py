"""Forgotten password: ask for a link by e-mail, then choose a new password with it."""
from fastapi import APIRouter, BackgroundTasks, Form
from fastapi.responses import HTMLResponse

from .. import i18n, mail, resetpages, resets, users
from ..deps import redirect

router = APIRouter()


def send_reset_mail(user: users.User, token: str) -> bool:
    """The mail with the reset link, in the user's language. False if it could not be sent."""
    base = mail.base_url()
    if not base:
        mail.log.warning("reset mail not sent: HUB_BASE_URL is not set")
        return False
    link = f"{base}/reset/{token}"
    minutes = resets.TOKEN_SECONDS // 60
    return mail.send_mail(
        user.email,
        i18n.t(user.language, "mail_reset_subject"),
        i18n.t(user.language, "mail_reset_body", name=user.name, link=link, minutes=minutes),
    )


@router.get("/forgot", response_class=HTMLResponse)
def forgot_form() -> str:
    return resetpages.forgot_page()


@router.post("/forgot", response_class=HTMLResponse)
def forgot(background: BackgroundTasks, email: str = Form("")):
    """Always the same answer. The mail goes out after the answer, so the time it takes does not
    show whether the address has an account either."""
    if "@" not in email:
        return HTMLResponse(resetpages.forgot_page("msg_email"), status_code=400)
    created = resets.create_token(email)
    if created:
        background.add_task(send_reset_mail, *created)
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
