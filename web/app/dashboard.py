"""HTML of the dashboard: project tiles on pages, page dots and the project dialogs."""
from . import i18n
from .icons import icon
from .layout import esc, fill
from .projects import PAGE_SIZE, Project  # 6 per page: 2 rows x 3 columns
from .users import User

SCRIPTS = ("motion.js", "sortable.js", "dashboard.js", "pages.js")
STYLES = ("dashboard.css",)

DASHBOARD = """<div class="dash">
  <h1 class="greeting" id="greeting" data-morning="%t.greet_morning%" data-noon="%t.greet_noon%"
      data-evening="%t.greet_evening%" data-night="%t.greet_night%" data-name="%NAME%">%t.greet_fallback%, %NAME%</h1>
  <div class="pages" id="pages" data-size="%SIZE%" data-current="%CURRENT%">
    <div class="track" id="track" style="--page:%PAGE_INDEX%">
    %GRIDS%
    </div>
  </div>
  %PAGER%
</div>
<div class="edge edge-left" aria-hidden="true">%EDGE_LEFT%</div>
<div class="edge edge-right" aria-hidden="true">%EDGE_RIGHT%</div>
<dialog class="dialog" id="create-dialog">
  <form method="post" action="/projects" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.new_project%</h2>
    <label>%t.project_name%<input name="name" required maxlength="60" autocomplete="off"></label>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.create%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="delete-dialog">
  <div data-step="1">
    <h2>%t.confirm_delete%</h2>
    <p class="muted" id="delete-name"></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="button" data-yes>%t.yes%</button>
    </div>
  </div>
  <form data-step="2" hidden novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.reauth%</h2>
    <label>%t.email%<input type="email" value="%EMAIL%" readonly autocomplete="username"></label>
    <label>%t.password%<input type="password" name="password" required autocomplete="current-password"></label>
    <p class="error" id="delete-error" role="alert" hidden>%t.wrong_password%</p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="danger-btn" type="submit">%t.delete_now%</button>
    </div>
  </form>
</dialog>"""


def _state(brief, lang: str) -> str:
    """The project's state under its name (statusnote.for_dashboard): lamp, headline and the AI's text."""
    if brief is None:
        return ""
    lamp_label = esc(i18n.t(lang, "status_lamp_" + brief.lamp))
    if brief.title:
        head, text = esc(brief.title), esc(brief.text)
    else:
        head, text = (esc(i18n.t(lang, brief.text)) if brief.text else ""), ""
    return (f'<span class="tile-state"><span class="m-lamp lamp-{brief.lamp}" role="img" aria-label="{lamp_label}"></span>'
            f'<span class="tile-head">{head}</span></span>'
            + (f'<span class="tile-note">{text}</span>' if text else ""))


def _project_tile(project: Project, index: int, lang: str, brief=None) -> str:
    return (
        f'<article class="tile glass" data-id="{project.id}" style="--i:{index}">'
        f'<a class="tile-link" href="/projects/{project.id}" draggable="false">'
        f'<span class="tile-name">{esc(project.name)}</span>{_state(brief, lang)}</a>'
        f'<button class="icon-button tile-delete" type="button" data-id="{project.id}" '
        f'aria-label="{esc(i18n.t(lang, "delete_project"))}">{icon("trash")}</button>'
        "</article>"
    )


def _plus_tile(index: int, lang: str, first_project: bool) -> str:
    hint = f'<span class="plus-hint">{esc(i18n.t(lang, "first_project"))}</span>' if first_project else ""
    return (
        f'<button class="tile plus" id="new-project" type="button" style="--i:{index}" '
        f'aria-label="{esc(i18n.t(lang, "new_project"))}">'
        f'<span class="plus-sign" aria-hidden="true"></span>{hint}</button>'
    )


def _grids(pages: list[list[Project]], first_project: bool, lang: str, briefs: dict | None = None) -> str:
    """One grid of 6 slots per page. All pages are in the document; pages.js slides between them.

    The "+" tile sits on the first page with a free slot (`pages` already ends with an empty
    page when every page is full).
    """
    plus_on = next(n for n, page in enumerate(pages) if len(page) < PAGE_SIZE)
    grids = []
    for n, page in enumerate(pages):
        tiles = [_project_tile(p, i, lang, (briefs or {}).get(p.id)) for i, p in enumerate(page)]
        if n == plus_on:
            tiles.append(_plus_tile(len(tiles), lang, first_project))
        tiles += ['<div class="tile ghost" aria-hidden="true"></div>'] * (PAGE_SIZE - len(tiles))
        grids.append(f'<div class="grid" data-page="{n + 1}">{"".join(tiles)}</div>')
    return "\n    ".join(grids)


def _pager(lang: str, page: int, pages: int) -> str:
    """Page dots and arrows. Always present (hidden for one page): pages.js redraws it while a
    tile is dragged to a new page, using the texts in the data attributes."""

    def arrow(target: int, name: str, label: str) -> str:
        if 1 <= target <= pages:
            return (
                f'<a class="pager-arrow" href="/?page={target}" data-page="{target}" '
                f'aria-label="{esc(label)}">{icon(name)}</a>'
            )
        return f'<span class="pager-arrow off" aria-hidden="true">{icon(name)}</span>'

    dots = "".join(
        f'<a class="dot{" active" if n == page else ""}" href="/?page={n}" data-page="{n}" '
        f'aria-label="{esc(i18n.t(lang, "page_n", n=n))}"{" aria-current=page" if n == page else ""}></a>'
        for n in range(1, pages + 1)
    )
    prev_label, next_label = i18n.t(lang, "page_prev"), i18n.t(lang, "page_next")
    return (
        f'<nav class="pager" id="pager"{" hidden" if pages < 2 else ""} '
        f'aria-label="{esc(i18n.t(lang, "pages_nav"))}" data-label-prev="{esc(prev_label)}" '
        f'data-label-next="{esc(next_label)}" data-label-page="{esc(i18n.t(lang, "page_n", n="{n}"))}">'
        f'{arrow(page - 1, "triangle_left", prev_label)}<span class="dots">{dots}</span>'
        f'{arrow(page + 1, "triangle_right", next_label)}</nav>'
    )


def render(user: User, layout: list[list[Project]], page: int, first_project: bool, briefs: dict | None = None) -> str:
    """Dashboard body. `layout` are the user's pages of projects (see projects.layout).

    When every page is full (or there are no projects) one more page is added for the
    "+" tile. `page` is the page to show (1, 2, ...), limited to the pages that exist.
    """
    lang = user.language
    pages = [list(p) for p in layout]
    if all(len(p) >= PAGE_SIZE for p in pages):
        pages.append([])
    page = min(max(page, 1), len(pages))
    return fill(
        DASHBOARD,
        lang,
        NAME=esc(user.name),
        EMAIL=esc(user.email),
        SIZE=str(PAGE_SIZE),
        CURRENT=str(page),
        PAGE_INDEX=str(page - 1),
        GRIDS=_grids(pages, first_project, lang, briefs),
        PAGER=_pager(lang, page, len(pages)),
        EDGE_LEFT=icon("triangle_left"),
        EDGE_RIGHT=icon("triangle_right"),
    )
