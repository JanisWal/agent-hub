"""Login, logout and the user's own settings."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from .. import i18n, throttle, ui, users
from ..deps import COOKIE_NAME, COOKIE_SECURE, api_user, fail, ok, page_user, redirect

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form() -> str:
    return ui.login_page()


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(""), password: str = Form("")):
    ip = throttle.client_ip(request)
    wait = throttle.seconds_locked(ip)  # checked first: a locked IP gets no answer about the password
    if wait:
        return HTMLResponse(ui.login_page(locked_minutes=throttle.minutes(wait)), status_code=429)
    user = users.check_login(email, password)
    if user is None:
        throttle.record_failure(ip)
        wait = throttle.seconds_locked(ip)
        if wait:
            return HTMLResponse(ui.login_page(locked_minutes=throttle.minutes(wait)), status_code=429)
        return HTMLResponse(ui.login_page(failed=True), status_code=401)
    response = redirect("/")
    response.set_cookie(
        COOKIE_NAME,
        users.create_session(user.id),
        max_age=users.SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return response


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        users.delete_session(token)
    response = redirect("/login")
    response.delete_cookie(COOKIE_NAME)
    return response


@router.post("/theme")
def save_theme(value: str = Form(""), user: users.User = Depends(api_user)):
    """The page tells us which style (light or dark) it shows, so mails can use the same one.
    The browser still keeps its own choice in localStorage; this is only a copy for the server."""
    try:
        users.set_theme(user.id, value)
    except ValueError:
        return fail(400)
    return ok()


@router.post("/settings")
def save_settings(
    user: users.User = Depends(page_user),
    display_name: str = Form(""),
    language: str = Form("de"),
):
    if language not in i18n.LANGS:
        language = user.language
    try:
        users.set_profile(user.id, display_name, language)
    except ValueError:
        pass  # name too long: keep the old settings
    return redirect("/")
