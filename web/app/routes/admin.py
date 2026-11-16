"""The administration page for owner and admins, and the old addresses that lead to it."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from .. import adminpage, i18n, ui, users
from ..deps import page_user, redirect

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
def admin_page(user: users.User = Depends(page_user)):
    if not user.is_admin:
        raise HTTPException(404)
    users.purge_deleted()   # accounts deleted long ago go for good, also while no runner is asking
    return ui.logged_in_page(
        user, i18n.t(user.language, "admin_title"), adminpage.render(user, users.list_users(user)),
        scripts=("users.js", "system.js"), styles=("users.css", "system.css", "admin.css"),
    )


@router.get("/users")
def users_old_address(user: users.User = Depends(page_user)):
    """The page that used to be here moved into /admin."""
    if not user.is_admin:
        raise HTTPException(404)
    return redirect("/admin")


@router.get("/system")
def system_old_address(user: users.User = Depends(page_user)):
    if not user.is_system_admin:
        raise HTTPException(404)
    return redirect("/admin")
