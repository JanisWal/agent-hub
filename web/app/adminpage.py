"""HTML of the administration page (Janis, 11.11.2026). It replaces the two separate pages "Manage users" and
"System": owner and superadmin see System on the left and Users on the right, an admin sees only Users, in the middle.
Normal users do not get the page at all (the route answers 404). New owner functions (update, backup status)
become further blocks here."""
from . import devices, i18n, systempage, ui, userspage
from .layout import esc, fill
from .users import User

ADMIN = """<div class="admin-wrap %KIND%">
  <a class="link back" href="/">%t.back%</a>
  <h1 class="admin-title">%t.admin_title%</h1>
  <div class="admin-cols">
    %SYSTEM%
    %USERS%
  </div>
</div>"""


def lan_block(user: User) -> str:
    """The owner approves the home network for other users' devices (devices.set_lan, 17.11.2026; static/lan.js)."""
    if user.role != "owner":
        return ""
    lang = user.language
    rows = "".join(
        f'<div class="sys-row lan-row" data-id="{a.device_id}"><div class="sys-main"><span class="sys-name">'
        f'{esc(a.device)} · {esc(a.hostname)}{" · " + esc(a.ip) if a.ip else ""}</span>'
        f'<small class="muted">{esc(a.user)} · {esc(a.project)}</small></div>'
        f'<button type="button" class="sys-btn" data-lan="{0 if a.lan_ok else 1}">'
        f'{esc(i18n.t(lang, "admin_lan_revoke" if a.lan_ok else "admin_lan_allow"))}</button></div>'
        for a in devices.approvals(user.id))
    body = rows or f'<p class="muted lan-empty">{esc(i18n.t(lang, "admin_devices_empty"))}</p>'
    return (f'<section class="sys-wrap lan-wrap" data-allow="{esc(i18n.t(lang, "admin_lan_allow"))}" '
            f'data-revoke="{esc(i18n.t(lang, "admin_lan_revoke"))}"><header class="sys-head"><h2>'
            f'{esc(i18n.t(lang, "admin_devices"))}</h2>{ui.info_dot(i18n.t(lang, "admin_devices"), i18n.t(lang, "admin_devices_info"))}'
            f'</header><div class="sys-list glass">{body}</div></section>')


def render(user: User, accounts: list[User]) -> str:
    """Body of /admin for an owner or an admin (the route refuses everybody else)."""
    owner = user.is_system_admin
    return fill(
        ADMIN, user.language,
        KIND="two" if owner else "one",
        SYSTEM=(systempage.render(user) + lan_block(user)) if owner else "",
        USERS=userspage.render(user, accounts),
    )
