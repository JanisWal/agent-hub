"""HTML of the administration page (Janis, 11.11.2026). It replaces the two separate pages "Manage users" and
"System": the owner sees System on the left and Users on the right, an admin sees only Users, in the middle.
Normal users do not get the page at all (the route answers 404). New owner functions (update, backup status)
become further blocks here."""
from . import systempage, userspage
from .layout import fill
from .users import User

ADMIN = """<div class="admin-wrap %KIND%">
  <a class="link back" href="/">%t.back%</a>
  <h1 class="admin-title">%t.admin_title%</h1>
  <div class="admin-cols">
    %SYSTEM%
    %USERS%
  </div>
</div>"""


def render(user: User, accounts: list[User]) -> str:
    """Body of /admin for an owner or an admin (the route refuses everybody else)."""
    owner = user.role == "owner"
    return fill(
        ADMIN, user.language,
        KIND="two" if owner else "one",
        SYSTEM=systempage.render(user) if owner else "",
        USERS=userspage.render(user, accounts),
    )
