"""HTML of the logged-in pages: settings bar, dashboard with project tiles, pager, quota bar."""
import html

from . import i18n
from .layout import fill
from .projects import Project
from .users import User

PAGE_SIZE = 6  # 2 rows x 3 columns

CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
TRASH = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>'
)
TRIANGLE_LEFT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-8 6 8 6z"/></svg>'
TRIANGLE_RIGHT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l8 6-8 6z"/></svg>'


def _e(text: str) -> str:
    """Escape for HTML text and attribute values."""
    return html.escape(text, quote=True)


def _validation_attrs(lang: str) -> str:
    """Texts for the inline form validation in theme.js."""
    required = _e(i18n.t(lang, "msg_required"))
    email = _e(i18n.t(lang, "msg_email"))
    return f'data-msg-required="{required}" data-msg-email="{email}"'


SETTINGS_BAR = """<div class="settings" id="settings">
  <button class="settings-toggle" id="settings-toggle" type="button"
          aria-expanded="false" aria-controls="settings-panel" aria-label="%L_TOGGLE%">
    <span class="settings-name">%NAME%</span>%CHEVRON%
  </button>
  <div class="settings-panel glass" id="settings-panel" hidden>
    <form method="post" action="/settings" novalidate %VALIDATION%>
      <label>%L_NAME%<input name="display_name" maxlength="40" value="%NAME_VALUE%" autocomplete="nickname"></label>
      <fieldset class="lang">
        <legend>%L_LANGUAGE%</legend>
        <label class="seg"><input type="radio" name="language" value="de" %DE%><span>Deutsch</span></label>
        <label class="seg"><input type="radio" name="language" value="en" %EN%><span>English</span></label>
      </fieldset>
      <button class="save" type="submit">%L_SAVE%</button>
    </form>
    <div class="settings-links">
      <button class="link" type="button" disabled title="%L_SOON%">%L_CLAUDE%</button>
      <button class="link" type="button" disabled title="%L_SOON%">%L_CHATGPT%</button>
      <form method="post" action="/logout"><button class="link" type="submit">%L_LOGOUT%</button></form>
    </div>
  </div>
</div>"""


def settings_bar(user: User) -> str:
    """Quiet, collapsible settings bar for the top right of every logged-in page."""
    lang = user.language
    return fill(
        SETTINGS_BAR,
        L_TOGGLE=_e(i18n.t(lang, "settings_toggle")),
        NAME=_e(user.name),
        CHEVRON=CHEVRON,
        VALIDATION=_validation_attrs(lang),
        L_NAME=_e(i18n.t(lang, "display_name")),
        NAME_VALUE=_e(user.display_name or ""),
        L_LANGUAGE=_e(i18n.t(lang, "language")),
        DE="checked" if lang == "de" else "",
        EN="checked" if lang == "en" else "",
        L_SAVE=_e(i18n.t(lang, "save")),
        L_SOON=_e(i18n.t(lang, "coming_soon")),
        L_CLAUDE=_e(i18n.t(lang, "connect_claude")),
        L_CHATGPT=_e(i18n.t(lang, "connect_chatgpt")),
        L_LOGOUT=_e(i18n.t(lang, "logout")),
    )


def _project_tile(project: Project, index: int, lang: str) -> str:
    return (
        f'<article class="tile glass" draggable="true" data-id="{project.id}" style="--i:{index}">'
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
    if pages < 2:
        return ""

    def arrow(target: int, icon: str, label: str) -> str:
        if 1 <= target <= pages:
            return f'<a class="pager-arrow" href="/?page={target}" aria-label="{_e(label)}">{icon}</a>'
        return f'<span class="pager-arrow off" aria-hidden="true">{icon}</span>'

    dots = "".join(
        f'<a class="dot{" active" if n == page else ""}" href="/?page={n}" '
        f'aria-label="{_e(i18n.t(lang, "page_n", n=n))}"'
        f'{" aria-current=page" if n == page else ""}></a>'
        for n in range(1, pages + 1)
    )
    return (
        f'<nav class="pager" aria-label="{_e(i18n.t(lang, "pages_nav"))}">'
        f'{arrow(page - 1, TRIANGLE_LEFT, i18n.t(lang, "page_prev"))}'
        f'<span class="dots">{dots}</span>'
        f'{arrow(page + 1, TRIANGLE_RIGHT, i18n.t(lang, "page_next"))}</nav>'
    )


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
  <div class="grid" id="grid">
    %TILES%
  </div>
  %PAGER%
  <div class="quota">
    <div class="quota-label"><span>%L_QUOTA%</span><span>%L_QUOTA_NONE%</span></div>
    <div class="quota-bar" role="progressbar" aria-label="%L_QUOTA%"
         aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div>
  </div>
</div>
%DIALOGS%"""


def render(user: User, projects: list[Project], page: int, pages: int, first_project: bool) -> str:
    """Dashboard body. `projects` are the ones of this page (at most PAGE_SIZE)."""
    lang = user.language
    tiles = [_project_tile(p, i, lang) for i, p in enumerate(projects)]
    if len(projects) < PAGE_SIZE:
        tiles.append(_plus_tile(len(tiles), lang, first_project))
    while len(tiles) < PAGE_SIZE:
        tiles.append(_ghost_tile())

    dialogs = fill(
        DIALOGS,
        VALIDATION=_validation_attrs(lang),
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
        TILES="\n    ".join(tiles),
        PAGER=_pager(lang, page, pages),
        L_QUOTA=_e(i18n.t(lang, "quota_title")),
        L_QUOTA_NONE=_e(i18n.t(lang, "quota_none")),
        DIALOGS=dialogs,
    )


PROJECT_PAGE = """<section class="glass">
  <h1>%NAME%</h1>
  <p class="subtitle">%SOON%</p>
  <a class="link" href="/">%BACK%</a>
</section>"""


def project_page(user: User, project: Project) -> str:
    """Placeholder project view; the kanban board comes later."""
    lang = user.language
    return fill(
        PROJECT_PAGE,
        NAME=_e(project.name),
        SOON=_e(i18n.t(lang, "project_soon")),
        BACK=_e("← " + i18n.t(lang, "back")),
    )
