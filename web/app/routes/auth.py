"""Login, logout and the user's own settings."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from .. import i18n, ui, users
from ..deps import COOKIE_NAME, COOKIE_SECURE, page_user, redirect

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form() -> str:
    return ui.login_page()


@router.post("/login", response_class=HTMLResponse)
def login(email: str = Form(""), password: str = Form("")):
    user = users.check_login(email, password)
    if user is None:
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
