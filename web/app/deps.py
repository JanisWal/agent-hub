"""Shared by all routes: who is logged in, and the kinds of answers we send.

Pages redirect to /login when nobody is logged in, fetch() endpoints answer 401. The exceptions
are turned into those answers in main.py, so a route just asks for its user. Somebody who still
has a start password (given by an admin) may only reach /password until he has chosen his own.
"""
import os

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import i18n, throttle, users

COOKIE_NAME = "session"
# Set HUB_SECURE_COOKIE=1 in production (HTTPS via the Cloudflare tunnel).
COOKIE_SECURE = os.environ.get("HUB_SECURE_COOKIE") == "1"


class LoginRequired(Exception):
    """A page was asked for without a login: send the visitor to /login."""


class ApiLoginRequired(Exception):
    """A fetch() endpoint was called without a login: answer 401."""


class PasswordChangeRequired(Exception):
    """The user still has a start password: send him to /password first."""


def _user(request: Request) -> users.User | None:
    return users.get_user(request.cookies.get(COOKIE_NAME))


def session_user(request: Request) -> users.User:
    """Dependency: the logged-in user, even with a start password (used by /password only)."""
    user = _user(request)
    if user is None:
        raise LoginRequired
    return user


def page_user(request: Request) -> users.User:
    """Dependency for pages: the logged-in user, or a redirect to /login (or /password)."""
    user = session_user(request)
    if user.must_change:
        raise PasswordChangeRequired
    return user


def api_user(request: Request) -> users.User:
    """Dependency for fetch() endpoints: the logged-in user, or 401."""
    user = _user(request)
    if user is None or user.must_change:
        raise ApiLoginRequired
    return user


def redirect(url: str) -> RedirectResponse:
    """303 so that the browser follows a POST with a GET."""
    return RedirectResponse(url, status_code=303)


def ok(**extra) -> dict:
    return {"ok": True, **extra}


def error(lang: str, text_key: str, status: int) -> JSONResponse:
    """Failure with a message in the user's language (`text_key` is a key in i18n.py)."""
    return JSONResponse({"ok": False, "message": i18n.t(lang, text_key)}, status_code=status)


def locked(lang: str, seconds: int) -> JSONResponse:
    """429 for fetch() endpoints, with the message in the user's language."""
    message = i18n.t(lang, "login_locked", minutes=throttle.minutes(seconds))
    return JSONResponse({"ok": False, "message": message}, status_code=429)


def fail(status: int) -> JSONResponse:
    return JSONResponse({"ok": False}, status_code=status)


def reauth(request: Request, user: users.User, password: str) -> JSONResponse | None:
    """Ask a logged-in user for his password again before something serious (delete, reset).

    None if the password is right, else the answer to send: 403 wrong, 429 if the IP is locked.
    Counts wrong passwords like the login does.
    """
    ip = throttle.client_ip(request)
    wait = throttle.seconds_locked(ip)
    if wait:
        return locked(user.language, wait)
    if users.verify_password(user.id, password):
        return None
    throttle.record_failure(ip)
    wait = throttle.seconds_locked(ip)
    return locked(user.language, wait) if wait else error(user.language, "wrong_password", 403)
