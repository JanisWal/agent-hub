"""User management for owner and admins, and everybody's own password."""
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import i18n, mailtext, resets, throttle, ui, userspage, users
from ..deps import COOKIE_NAME, api_user, error, fail, ok, page_user, reauth, redirect, session_user

router = APIRouter()

_ADD_ERRORS = {"email": "msg_email", "taken": "err_email_taken"}
_PASSWORD_ERRORS = {"short": "err_pw_rules", "policy": "err_pw_rules", "same": "err_pw_same"}


@router.get("/users", response_class=HTMLResponse)
def users_page(user: users.User = Depends(page_user)):
    if not user.is_admin:
        raise HTTPException(404)
    return ui.logged_in_page(
        user, i18n.t(user.language, "users_title"), userspage.render(user, users.list_users(user)),
        scripts=("users.js",), styles=("users.css",),
    )


@router.post("/users/add")
def add_user(email: str = Form(""), user: users.User = Depends(api_user)):
    """Invite somebody: the account gets a password nobody knows, and a mail with a link lets
    him choose his own. If the mail cannot be sent, the account is removed again."""
    if not user.is_admin:
        return fail(403)
    try:
        account = users.add_user(user, email, secrets.token_urlsafe(24))
    except users.UserError as problem:
        return error(user.language, _ADD_ERRORS[problem.code], 400)
    created = resets.create_token(account.email, resets.INVITE_SECONDS)
    if not (created and mailtext.send_link_mail("invite", account, created[1], resets.INVITE_SECONDS)):
        users.delete_user(user, account.id)
        return error(user.language, "err_mail_failed", 502)
    return ok()


@router.post("/users/{user_id}/reset")
def reset_password(
    request: Request, user_id: int, password: str = Form(""), confirm: str = Form(""),
    user: users.User = Depends(api_user),
):
    """A new start password for somebody; needs the password of the one who asks."""
    if not user.is_admin:
        return fail(403)
    denied = reauth(request, user, confirm)
    if denied:
        return denied
    try:
        users.reset_password(user, user_id, password)
    except PermissionError:
        return error(user.language, "err_forbidden", 403)
    except users.UserError as problem:
        return error(user.language, "err_not_found" if problem.code == "not_found" else "err_start_short", 400)
    return ok()


@router.post("/users/{user_id}/delete")
def delete_user(
    request: Request, user_id: int, confirm: str = Form(""), user: users.User = Depends(api_user)
):
    """Deletes the account and its projects for good; needs the password of the one who asks."""
    if not user.is_admin:
        return fail(403)
    denied = reauth(request, user, confirm)
    if denied:
        return denied
    try:
        users.delete_user(user, user_id)
    except PermissionError:
        return error(user.language, "err_forbidden", 403)
    except users.UserError:
        return error(user.language, "err_not_found", 404)
    return ok()


@router.post("/users/{user_id}/owner")
def make_owner(
    request: Request, user_id: int, confirm: str = Form(""), user: users.User = Depends(api_user)
):
    """The owner hands the ownership over and becomes an admin; needs his password."""
    if user.role != "owner":
        return fail(403)
    denied = reauth(request, user, confirm)
    if denied:
        return denied
    try:
        users.transfer_owner(user, user_id)
    except PermissionError:
        return error(user.language, "err_forbidden", 403)
    except users.UserError as problem:
        if problem.code == "not_ready":
            return error(user.language, "err_owner_not_ready", 400)
        return error(user.language, "err_not_found", 404)
    return ok()


@router.post("/users/{user_id}/admin")
def toggle_admin(user_id: int, value: str = Form(""), user: users.User = Depends(api_user)):
    """Only the owner makes or removes admins."""
    try:
        users.set_admin(user, user_id, value == "1")
    except PermissionError:
        return fail(403)
    except users.UserError:
        return fail(404)
    return ok()


@router.get("/password", response_class=HTMLResponse)
def password_form(user: users.User = Depends(session_user)):
    return userspage.password_page(user)


@router.post("/password", response_class=HTMLResponse)
def change_password(
    request: Request, old: str = Form(""), new: str = Form(""), repeat: str = Form(""),
    user: users.User = Depends(session_user),
):
    lang = user.language

    def answer(status: int, text: str) -> HTMLResponse:
        return HTMLResponse(userspage.password_page(user, text), status_code=status)

    def locked_answer(wait: int) -> HTMLResponse:
        return answer(429, i18n.t(lang, "login_locked", minutes=throttle.minutes(wait)))

    ip = throttle.client_ip(request)
    wait = throttle.seconds_locked(ip)
    if wait:
        return locked_answer(wait)
    if new != repeat:
        return answer(400, i18n.t(lang, "err_pw_mismatch"))
    try:
        users.change_own_password(user, old, new, keep_token=request.cookies.get(COOKIE_NAME))
    except users.UserError as problem:
        if problem.code == "wrong_password":
            throttle.record_failure(ip)
            wait = throttle.seconds_locked(ip)
            return locked_answer(wait) if wait else answer(403, i18n.t(lang, "wrong_password"))
        return answer(400, i18n.t(lang, _PASSWORD_ERRORS[problem.code]))
    return redirect("/")
