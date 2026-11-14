"""HTML of the project page: stations on the left, kanban board and trash on the right."""
from . import agents, i18n, managerpage
from .board import KINDS, Item
from .icons import icon
from .layout import esc, fill
from .projects import MAX_DESCRIPTION, MAX_NAME, Project
from .users import User

SCRIPTS = ("motion.js", "segment.js", "sortable.js", "board.js", "stations.js", "titlemenu.js", "chat.js", "picker.js", "manager.js", "splitter.js", "checks.js", "upload.js", "tiffthumb.js", "files.js")
STYLES = ("project.css",)

COLUMN_LABEL = {"bug": "col_bug", "minor": "col_minor", "major": "col_major"}

PROJECT = """<div class="project" data-id="%PID%">
  %STATIONS%
  <div class="boardwrap">
    <section class="vault glass" id="vault" hidden>
      <div class="vault-view" data-view="trash" hidden>
        <h2>%t.trash%</h2>
        %TRASH%
      </div>
      <div class="vault-view" data-view="archive" hidden>
        <h2>%t.archive%</h2>
        %ARCHIVE%
      </div>
    </section>
    <div class="board" id="board">
      %COLUMNS%
    </div>
  </div>
  %MANAGER%
</div>
<dialog class="dialog" id="item-dialog" data-title-new="%t.new_item%" data-title-edit="%t.edit_item%"
        data-btn-new="%t.create%" data-btn-edit="%t.save%">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2 id="item-dialog-title">%t.new_item%</h2>
    <input type="hidden" name="kind" value="bug">
    <label>%t.item_title%<input name="title" required maxlength="200" autocomplete="off"></label>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit" id="item-dialog-button">%t.create%</button>
    </div>
  </form>
</dialog>
%MANAGER_DIALOGS%
<dialog class="dialog danger" id="confirm-dialog" data-msg-item="%t.confirm_delete_item%" data-msg-empty="%t.confirm_empty_trash%">
  <h2 id="confirm-text"></h2>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="confirm-yes">%t.yes%</button>
  </div>
</dialog>"""


def _action_button(lang: str, action: str, label_key: str, icon_name: str, css: str = "") -> str:
    label = esc(i18n.t(lang, label_key))
    return (
        f'<button class="icon-button card-btn {css}" type="button" data-action="{action}" '
        f'aria-label="{label}" title="{label}">{icon(icon_name)}</button>'
    )


def _card(item: Item, lang: str) -> str:
    title = f'<span class="card-title">{esc(item.title)}</span>'
    if item.status == "proposed":
        # Green and red buttons (Janis, 07.11.2026): "go" takes the suggestion over, "stop" rejects it.
        buttons = _action_button(lang, "reject", "reject", "cross", "stop") + _action_button(
            lang, "accept", "accept", "check", "go"
        )
        return f'<article class="card proposed" data-id="{item.id}">{title}<div class="card-actions">{buttons}</div></article>'
    discard = _action_button(lang, "discard", "discard", "trash", "quiet")
    origin = " from-claude" if item.source == "claude" else ""
    return f'<article class="card{origin}" data-id="{item.id}">{title}{discard}</article>'


def _column(kind: str, items: list[Item], lang: str) -> str:
    agreed = [i for i in items if i.kind == kind and i.status == "open"]
    proposed = [i for i in items if i.kind == kind and i.status == "proposed"]
    suggestions = ""
    if proposed:
        suggestions = (
            f'<p class="group-label">{esc(i18n.t(lang, "claude_suggestions"))}</p>'
            f'<div class="cards proposed-list">{"".join(_card(i, lang) for i in proposed)}</div>'
        )
    add = esc(i18n.t(lang, "add_item"))
    return (
        f'<section class="column glass" data-kind="{kind}">'
        f'<header class="column-head"><h2>{esc(i18n.t(lang, COLUMN_LABEL[kind]))}</h2>'
        f'<span class="count">{len(agreed) + len(proposed)}</span>'
        f'<button class="icon-button add" type="button" data-kind="{kind}" aria-label="{add}" title="{add}">'
        f'{icon("plus")}</button></header>'
        f'<div class="cards open-list" data-kind="{kind}">{"".join(_card(i, lang) for i in agreed)}</div>'
        f"{suggestions}</section>"
    )


def _trash(items: list[Item], lang: str) -> str:
    if not items:
        return f'<p class="muted">{esc(i18n.t(lang, "trash_is_empty"))}</p>'
    rows = "".join(
        f'<li class="trash-row" data-id="{i.id}"><span class="trash-title">{esc(i.title)}'
        f'<small>{esc(i18n.t(lang, COLUMN_LABEL[i.kind]))}</small></span>'
        f'{_action_button(lang, "restore", "restore", "undo")}'
        f'{_action_button(lang, "delete", "delete_now", "cross", "no")}</li>'
        for i in items
    )
    return (
        f'<ul class="trash-list">{rows}</ul>'
        f'<button class="link inline" type="button" id="trash-empty">{esc(i18n.t(lang, "trash_empty"))}</button>'
    )


def _archive(items: list[Item], lang: str) -> str:
    """The archive: what the agents finished. Same look as the trash, but nothing to delete."""
    if not items:
        return f'<p class="muted">{esc(i18n.t(lang, "archive_is_empty"))}</p>'
    rows = "".join(
        f'<li class="trash-row" data-id="{i.id}"><span class="trash-title">{esc(i.title)}'
        f'<small>{esc(i18n.t(lang, COLUMN_LABEL[i.kind]))}</small></span>'
        f'{_action_button(lang, "restore", "restore", "undo")}</li>'
        for i in items
    )
    return f'<ul class="trash-list">{rows}</ul>'


# The cycle of an idea, top to bottom (Janis, 07.11.2026). The board and the manager exist so far;
# a click swaps the main window (web/app/static/stations.js), the stations stay.
VIEWS = (("board", "station_board"), ("manager", "station_manager"))
STATION_KEYS = ("station_programmer", "station_tester", "station_reviewer", "station_me")


def _stations(lang: str) -> str:
    soon = esc(i18n.t(lang, "coming_soon"))

    def view(name: str, key: str) -> str:
        current = ' aria-current="page"' if name == "board" else ""
        active = " active" if name == "board" else ""
        return (
            f'<a class="station{active}" href="#{name}" data-seg data-station="{name}"{current}>'
            f'<span class="station-label">{esc(i18n.t(lang, key))}</span></a>'
        )

    off = "".join(
        f'<span class="station off" data-seg aria-disabled="true" title="{soon}">'
        f'<span class="station-label">{esc(i18n.t(lang, key))}</span></span>'
        for key in STATION_KEYS
    )
    # The thumb of the segment slider (segment.js, Janis 14.11.2026): it lies under the open station, juts out to
    # the right, and can be dragged up and down to another station.
    return (
        f'<nav class="stations" aria-label="{esc(i18n.t(lang, "stations"))}">'
        f'<span class="station-thumb" aria-hidden="true"></span>'
        f'{"".join(view(name, key) for name, key in VIEWS)}{off}</nav>'
    )


def back_html(lang: str) -> str:
    """The way back to the dashboard, right of the brand in the top bar."""
    label = esc(i18n.t(lang, "back_to_projects"))
    return f'<a class="topbar-back" href="/" aria-label="{label}" title="{label}">{icon("arrow_left")}</a>'


TITLE_MENU = """<div class="title-wrap">
  <h1 class="project-title" title="%NAME%">%NAME%</h1>
  <button class="icon-button title-edit" id="title-edit" type="button" aria-haspopup="true" aria-expanded="false"
          aria-controls="title-menu" aria-label="%t.edit_project%" title="%t.edit_project%">%PENCIL%</button>
  <form class="title-menu glass" id="title-menu" method="post" action="/projects/%PID%/settings" novalidate hidden
        data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <label>%t.project_name%<input name="name" required maxlength="%MAX_NAME%" autocomplete="off" value="%NAME%"></label>
    <label>%t.project_description%<textarea name="description" maxlength="%MAX_DESCRIPTION%" rows="4"
      placeholder="%t.project_description_placeholder%">%DESCRIPTION%</textarea></label>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.save%</button>
    </div>
  </form>
</div>"""


def title_html(project: Project, lang: str = "de") -> str:
    """The project name for the top bar (golden section, see layout.page `top_center`), with the pencil
    that opens the drop-down for name and description (Janis, 07.11.2026)."""
    return fill(
        TITLE_MENU,
        lang,
        PID=str(project.id),
        NAME=esc(project.name),
        DESCRIPTION=esc(project.description),
        MAX_NAME=str(MAX_NAME),
        MAX_DESCRIPTION=str(MAX_DESCRIPTION),
        PENCIL=icon("pencil"),
    )


def drawer_buttons(lang: str) -> str:
    """Trash and archive: two identical round buttons next to the gear, they slide with the drawer."""
    def button(view: str, label_key: str, icon_name: str) -> str:
        label = esc(i18n.t(lang, label_key))
        return (
            f'<button class="drawer-extra" id="{view}-toggle" type="button" data-view="{view}" '
            f'aria-pressed="false" aria-controls="vault" aria-label="{label}" title="{label}">{icon(icon_name)}</button>'
        )
    return button("archive", "archive", "done") + button("trash", "trash", "trash")


def render(user: User, project: Project, items: list[Item], regular_checks: list | None = None,
           stored_files: list | None = None) -> str:
    """Project page body with the kanban board and the Manager view (with the regular checks)."""
    lang = user.language
    trashed = [i for i in items if i.status == "trash"]
    archived = [i for i in items if i.status == "archived"]
    live = [i for i in items if i.status not in ("trash", "archived")]
    return fill(
        PROJECT,
        lang,
        PID=str(project.id),
        STATIONS=_stations(lang),
        MANAGER=managerpage.render(lang, agents.settings(user.id), regular_checks or [], stored_files=stored_files or [],
                                    files_confirm=user.files_confirm),
        MANAGER_DIALOGS=managerpage.dialogs(lang),
        TRASH=_trash(trashed, lang),
        ARCHIVE=_archive(archived, lang),
        COLUMNS="\n      ".join(_column(kind, live, lang) for kind in KINDS),
    )
