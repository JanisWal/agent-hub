"""Shared by all routes: who is logged in, and the three kinds of answers we send.

Pages redirect to /login when nobody is logged in, fetch() endpoints answer 401. The two
exceptions are turned into those answers in main.py, so a route just asks for its user.
"""
import os

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import users

COOKIE_NAME = "session"
# Set HUB_SECURE_COOKIE=1 in production (HTTPS via the Cloudflare tunnel).
COOKIE_SECURE = os.environ.get("HUB_SECURE_COOKIE") == "1"


class LoginRequired(Exception):
    """A page was asked for without a login: send the visitor to /login."""


class ApiLoginRequired(Exception):
    """A fetch() endpoint was called without a login: answer 401."""


def _user(request: Request) -> users.User | None:
    return users.get_user(request.cookies.get(COOKIE_NAME))


def page_user(request: Request) -> users.User:
    """Dependency for pages: the logged-in user, or a redirect to /login."""
    user = _user(request)
    if user is None:
        raise LoginRequired
    return user


def api_user(request: Request) -> users.User:
    """Dependency for fetch() endpoints: the logged-in user, or 401."""
    user = _user(request)
    if user is None:
        raise ApiLoginRequired
    return user


def redirect(url: str) -> RedirectResponse:
    """303 so that the browser follows a POST with a GET."""
    return RedirectResponse(url, status_code=303)


def ok(**extra) -> dict:
    return {"ok": True, **extra}


def fail(status: int) -> JSONResponse:
    return JSONResponse({"ok": False}, status_code=status)
