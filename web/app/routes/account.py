"""The own account (accountpage.py): the page, and deleting the account (everybody but the owner)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import accountpage, i18n, ui, users
from ..deps import COOKIE_NAME, api_user, error, page_user, reauth

router = APIRouter()


@router.get("/account", response_class=HTMLResponse)
def account_page(user: users.User = Depends(page_user)):
    return ui.logged_in_page(user, i18n.t(user.language, "account_title"), accountpage.render(user),
                             scripts=("account.js",), styles=("system.css", "admin.css", "account.css"))


@router.post("/account/delete")
def delete_account(request: Request, confirm: str = Form(""), user: users.User = Depends(api_user)):
    """Delete the own account (locked now, gone after 30 days, users.delete_self); needs the own password."""
    denied = reauth(request, user, confirm)
    if denied:
        return denied
    try:
        users.delete_self(user)
    except users.UserError:
        return error(user.language, "account_delete_owner", 409)
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)   # this browser forgets the login, too
    return response
