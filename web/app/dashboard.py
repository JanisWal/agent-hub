"""HTML of the dashboard: settings drawer, project tiles, pager, quota bar."""
from . import i18n
from .layout import esc as _e
from .layout import fill
from .projects import PAGE_SIZE, Project  # 6 per page: 2 rows x 3 columns
from .users import User

# Linked AI accounts (name, connected). The real state comes with the runner (phase 2).
SERVICES = (("Claude", False), ("ChatGPT", False))

CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
ARROW_LEFT = '<svg class="drawer-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>'
GEAR = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/>'
    '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06'
    "a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4"
    "a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82"
    " 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82"
    "l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3"
    "a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0"
    " 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2"
    'h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>'
)
TRASH = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>'
)
TRIANGLE_LEFT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-8 6 8 6z"/></svg>'
TRIANGLE_RIGHT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l8 6-8 6z"/></svg>'


def validation_attrs(lang: str) -> str:
    """Texts for the inline form validation in theme.js."""
    required = _e(i18n.t(lang, "msg_required"))
    email = _e(i18n.t(lang, "msg_email"))
    return f'data-msg-required="{required}" data-msg-email="{email}"'


# Closed: only the gear and the arrow show at the top right. Open: the box slides out of
# the corner and the handle rides along on its left edge (see theme.css).
SETTINGS_BAR = """<div class="drawer" id="settings">
  <button class="drawer-handle" id="settings-toggle" type="button"
          aria-expanded="false" aria-controls="settings-panel" aria-label="%L_TOGGLE%">%GEAR%%ARROW%</button>
  <div class="drawer-box glass" id="settings-panel">
    <form method="post" action="/settings" novalidate %VALIDATION%>
      <label class="setting">
        <span class="setting-label">%L_NAME%</span>
        <input name="display_name" maxlength="40" value="%NAME_VALUE%" placeholder="%NAME_SHOWN%" autocomplete="nickname">
      </label>
      <label class="setting has-select">
        <span class="setting-label">%L_LANGUAGE%</span>
        <select name="language">
          <option value="de" %DE%>Deutsch</option>
          <option value="en" %EN%>English</option>
        </select>%CHEVRON%
      </label>
      %SERVICES%
      <button class="primary save" type="submit">%L_SAVE%</button>
    </form>
    <form method="post" action="/logout"><button class="link" type="submit">%L_LOGOUT%</button></form>
  </div>
</div>"""


def _service_rows(lang: str) -> str:
    rows = []
    for name, connected in SERVICES:
        status = _e(i18n.t(lang, "connected" if connected else "not_connected"))
        action = (
            ""
            if connected
            else f'<button class="link inline" type="button" disabled title="{_e(i18n.t(lang, "coming_soon"))}">'
            f'{_e(i18n.t(lang, "connect"))}</button>'
        )
        rows.append(
            f'<div class="setting service{" on" if connected else ""}">'
            f'<span class="setting-label">{name}</span>'
            f'<span class="service-line"><span class="status">{status}</span>{action}</span></div>'
        )
    return "\n      ".join(rows)


def settings_bar(user: User) -> str:
    """Settings drawer for the top right corner of every logged-in page."""
    lang = user.language
    return fill(
        SETTINGS_BAR,
        L_TOGGLE=_e(i18n.t(lang, "settings_toggle")),
        GEAR=GEAR,
        ARROW=ARROW_LEFT,
        VALIDATION=validation_attrs(lang),
        L_NAME=_e(i18n.t(lang, "display_name")),
        NAME_VALUE=_e(user.display_name or ""),
        NAME_SHOWN=_e(user.name),
        L_LANGUAGE=_e(i18n.t(lang, "language")),
        DE="selected" if lang == "de" else "",
        EN="selected" if lang == "en" else "",
        CHEVRON=CHEVRON,
        SERVICES=_service_rows(lang),
        L_SAVE=_e(i18n.t(lang, "save")),
        L_LOGOUT=_e(i18n.t(lang, "logout")),
    )


def _project_tile(project: Project, index: int, lang: str) -> str:
    return (
        f'<article class="tile glass" data-id="{project.id}" style="--i:{index}">'
        f'<a class="tile-link" href="/projects/{project.id}" draggable="false">'
        f'<span class="tile-name">{_e(project.name)}</span></a>'
        f'<button class="icon-button tile-delete" type="button" data-id="{project.id}" '
        f'aria-label="{_e(i18n.t(lang, "delete_project"))}">{TRASH}</button>'
        "</article>"
    )


def _plus_tile(index: int, lang: str, first_project: bool) -> str:
    hint = (
        f'<span class="plus-hint">{_e(i18n.t(lang, "first_project"))}</span>'
        if first_project
        else ""
    )
    return (
        f'<button class="tile plus" id="new-project" type="button" style="--i:{index}" '
        f'aria-label="{_e(i18n.t(lang, "new_project"))}">'
        f'<span class="plus-sign" aria-hidden="true"></span>{hint}</button>'
    )


def _ghost_tile() -> str:
    return '<div class="tile ghost" aria-hidden="true"></div>'


def _pager(lang: str, page: int, pages: int) -> str:
    """Page dots and arrows. Always present (hidden for one page): dashboard.js redraws
    it while a tile is dragged to a new page, using the texts in the data attributes."""

    def arrow(target: int, icon: str, label: str) -> str:
        if 1 <= target <= pages:
            return (
                f'<a class="pager-arrow" href="/?page={target}" data-page="{target}" '
                f'aria-label="{_e(label)}">{icon}</a>'
            )
        return f'<span class="pager-arrow off" aria-hidden="true">{icon}</span>'

    dots = "".join(
        f'<a class="dot{" active" if n == page else ""}" href="/?page={n}" data-page="{n}" '
        f'aria-label="{_e(i18n.t(lang, "page_n", n=n))}"'
        f'{" aria-current=page" if n == page else ""}></a>'
        for n in range(1, pages + 1)
    )
    return (
        f'<nav class="pager" id="pager"{" hidden" if pages < 2 else ""} '
        f'aria-label="{_e(i18n.t(lang, "pages_nav"))}" '
        f'data-label-prev="{_e(i18n.t(lang, "page_prev"))}" '
        f'data-label-next="{_e(i18n.t(lang, "page_next"))}" '
        f'data-label-page="{_e(i18n.t(lang, "page_n", n="{n}"))}">'
        f'{arrow(page - 1, TRIANGLE_LEFT, i18n.t(lang, "page_prev"))}'
        f'<span class="dots">{dots}</span>'
        f'{arrow(page + 1, TRIANGLE_RIGHT, i18n.t(lang, "page_next"))}</nav>'
    )


def _grids(pages: list[list[Project]], first_project: bool, lang: str) -> str:
    """One grid of 6 slots per page. All pages are in the page; dashboard.js slides between them.

    The "+" tile sits on the first page with a free slot (pages are laid out so that
    `pages` already ends with an empty page when every page is full).
    """
    plus_on = next(n for n, page in enumerate(pages) if len(page) < PAGE_SIZE)
    grids = []
    for n, page in enumerate(pages):
        tiles = [_project_tile(p, i, lang) for i, p in enumerate(page)]
        if n == plus_on:
            tiles.append(_plus_tile(len(tiles), lang, first_project))
        while len(tiles) < PAGE_SIZE:
            tiles.append(_ghost_tile())
        grids.append(f'<div class="grid" data-page="{n + 1}">{"".join(tiles)}</div>')
    return "\n    ".join(grids)


DIALOGS = """<dialog class="dialog" id="create-dialog">
  <form method="post" action="/projects" novalidate %VALIDATION%>
    <h2>%L_NEW%</h2>
    <label>%L_PROJECT_NAME%<input name="name" required maxlength="60" autocomplete="off"></label>
    <div class="actions">
      <button type="button" data-close>%L_CANCEL%</button>
      <button class="primary" type="submit">%L_CREATE%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="delete-dialog">
  <div data-step="1">
    <h2>%L_CONFIRM%</h2>
    <p class="muted" id="delete-name"></p>
    <div class="actions">
      <button type="button" data-close autofocus>%L_CANCEL%</button>
      <button class="danger-btn" type="button" data-yes>%L_YES%</button>
    </div>
  </div>
  <form data-step="2" hidden novalidate %VALIDATION%>
    <h2>%L_REAUTH%</h2>
    <label>%L_EMAIL%<input type="email" value="%EMAIL%" readonly autocomplete="username"></label>
    <label>%L_PASSWORD%<input type="password" name="password" required autocomplete="current-password"></label>
    <p class="error" id="delete-error" role="alert" hidden>%L_WRONG%</p>
    <div class="actions">
      <button type="button" data-close>%L_CANCEL%</button>
      <button class="danger-btn" type="submit">%L_DELETE_NOW%</button>
    </div>
  </form>
</dialog>"""

DASHBOARD = """<div class="dash">
  <h1 class="greeting" id="greeting" data-morning="%G_MORNING%" data-noon="%G_NOON%"
      data-evening="%G_EVENING%" data-name="%NAME%">%G_FALLBACK%, %NAME%</h1>
  <div class="pages" id="pages" data-size="%SIZE%" data-current="%CURRENT%">
    <div class="track" id="track" style="--page:%PAGE_INDEX%">
    %GRIDS%
    </div>
  </div>
  %PAGER%
  <div class="quota">
    <div class="quota-label"><span>%L_QUOTA%</span><span>%L_QUOTA_NONE%</span></div>
    <div class="quota-bar" role="progressbar" aria-label="%L_QUOTA%"
         aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div>
  </div>
</div>
<div class="edge edge-left" aria-hidden="true">%EDGE_LEFT%</div>
<div class="edge edge-right" aria-hidden="true">%EDGE_RIGHT%</div>
%DIALOGS%"""


def render(user: User, layout: list[list[Project]], page: int, first_project: bool) -> str:
    """Dashboard body. `layout` are the user's pages of projects (see projects.layout).

    When every page is full (or there are no projects) one more page is added for the
    "+" tile. `page` is the page to show (1, 2, ...), limited to the pages that exist.
    """
    lang = user.language
    pages = [list(p) for p in layout]
    if all(len(p) >= PAGE_SIZE for p in pages):
        pages.append([])
    page = min(max(page, 1), len(pages))

    dialogs = fill(
        DIALOGS,
        VALIDATION=validation_attrs(lang),
        L_NEW=_e(i18n.t(lang, "new_project")),
        L_PROJECT_NAME=_e(i18n.t(lang, "project_name")),
        L_CANCEL=_e(i18n.t(lang, "cancel")),
        L_CREATE=_e(i18n.t(lang, "create")),
        L_CONFIRM=_e(i18n.t(lang, "confirm_delete")),
        L_YES=_e(i18n.t(lang, "yes")),
        L_REAUTH=_e(i18n.t(lang, "reauth")),
        L_EMAIL=_e(i18n.t(lang, "email")),
        L_PASSWORD=_e(i18n.t(lang, "password")),
        EMAIL=_e(user.email),
        L_WRONG=_e(i18n.t(lang, "wrong_password")),
        L_DELETE_NOW=_e(i18n.t(lang, "delete_now")),
    )
    return fill(
        DASHBOARD,
        G_MORNING=_e(i18n.t(lang, "greet_morning")),
        G_NOON=_e(i18n.t(lang, "greet_noon")),
        G_EVENING=_e(i18n.t(lang, "greet_evening")),
        G_FALLBACK=_e(i18n.t(lang, "greet_fallback")),
        NAME=_e(user.name),
        SIZE=str(PAGE_SIZE),
        CURRENT=str(page),
        PAGE_INDEX=str(page - 1),
        GRIDS=_grids(pages, first_project, lang),
        PAGER=_pager(lang, page, len(pages)),
        EDGE_LEFT=TRIANGLE_LEFT,
        EDGE_RIGHT=TRIANGLE_RIGHT,
        L_QUOTA=_e(i18n.t(lang, "quota_title")),
        L_QUOTA_NONE=_e(i18n.t(lang, "quota_none")),
        DIALOGS=dialogs,
    )
