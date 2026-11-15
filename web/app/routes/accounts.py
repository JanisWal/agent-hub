"""User management actions for owner and admins (the page itself is /admin, routes/admin.py), and everybody's
own password."""
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from .. import i18n, mailtext, resets, throttle, userspage, users
from ..deps import COOKIE_NAME, api_user, error, fail, ok, reauth, redirect, session_user

router = APIRouter()

_ADD_ERRORS = {"email": "msg_email", "taken": "err_email_taken"}
_PASSWORD_ERRORS = {"short": "err_pw_rules", "policy": "err_pw_rules", "same": "err_pw_same"}


@router.post("/users/add")
def add_user(email: str = Form(""), user: users.User = Depends(api_user)):
    """Invite somebody: the account gets a password nobody knows, and a mail with a link lets
    him choose his own. If the mail cannot be sent, the account is removed again. The address of an account
    deleted in the last users.DELETED_DAYS days brings that account back as it was."""
    if not user.is_admin:
        return fail(403)
    restored = users.is_deleted(email)   # a deleted account with this address comes back (users.add_user)
    try:
        account = users.add_user(user, email, secrets.token_urlsafe(24))
    except users.UserError as problem:
        return error(user.language, _ADD_ERRORS[problem.code], 400)
    created = resets.create_token(account.email, resets.INVITE_SECONDS)
    if not (created and mailtext.send_link_mail("invite", account, created[1], resets.INVITE_SECONDS)):
        users.cancel_invitation(user, account.id, restored)
        return error(user.language, "err_mail_failed", 502)
    return ok()


@router.post("/users/{user_id}/invite")
def resend_invitation(user_id: int, user: users.User = Depends(api_user)):
    """Send the invitation mail again to an account that has not chosen its password yet. The new link replaces
    the old one (`resets.create_token`), and one mail per account and minute at most (the same cooldown as "forgot
    password"). Nothing is removed if the mail fails: the account stays, only the answer says so."""
    if not user.is_admin:
        return fail(403)
    try:
        account = users.pending_invitation(user, user_id)
    except PermissionError:
        return error(user.language, "err_forbidden", 403)
    except users.UserError as problem:
        return error(user.language, "err_not_found" if problem.code == "not_found" else "err_not_pending", 400)
    created = resets.create_token(account.email, resets.INVITE_SECONDS)
    if created is None:
        return error(user.language, "err_invite_wait", 429)
    if not mailtext.send_link_mail("invite", account, created[1], resets.INVITE_SECONDS):
        return error(user.language, "err_mail_resend", 502)
    return ok(message=i18n.t(user.language, "invite_sent"))


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
