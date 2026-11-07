"""HTML of the project page: stations on the left, kanban board and trash on the right."""
from . import i18n
from .board import KINDS, Item
from .icons import icon
from .layout import esc, fill
from .projects import Project
from .users import User

SCRIPTS = ("motion.js", "sortable.js", "board.js")
STYLES = ("project.css",)

COLUMN_LABEL = {"bug": "col_bug", "minor": "col_minor", "major": "col_major"}

PROJECT = """<div class="project" data-id="%PID%">
  %STATIONS%
  <div class="boardwrap">
    <header class="board-head">
      <h1>%NAME%</h1>
      <button class="icon-button trash-toggle" id="trash-toggle" type="button" aria-expanded="false"
              aria-controls="trash" aria-label="%t.trash%" title="%t.trash%">%TRASH_ICON%<span class="count">%TRASH_COUNT%</span></button>
    </header>
    <section class="trash glass" id="trash" hidden>
      <h2>%t.trash%</h2>
      %TRASH%
    </section>
    <div class="board">
      %COLUMNS%
    </div>
  </div>
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
        buttons = _action_button(lang, "accept", "accept", "check", "ok") + _action_button(
            lang, "reject", "reject", "cross", "no"
        )
        return f'<article class="card proposed" data-id="{item.id}">{title}<div class="card-actions">{buttons}</div></article>'
    discard = _action_button(lang, "discard", "discard", "trash", "quiet")
    return f'<article class="card" data-id="{item.id}">{title}{discard}</article>'


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


def _stations(lang: str) -> str:
    soon = esc(i18n.t(lang, "coming_soon"))
    off = "".join(
        f'<span class="station off" aria-disabled="true" title="{soon}">{esc(i18n.t(lang, key))}</span>'
        for key in ("station_agents", "station_files", "station_docs")
    )
    return (
        f'<nav class="stations glass" aria-label="{esc(i18n.t(lang, "stations"))}">'
        f'<a class="station back" href="/">{icon("arrow_left")}{esc(i18n.t(lang, "back_to_projects"))}</a>'
        f'<a class="station active" href="#" aria-current="page">{esc(i18n.t(lang, "station_board"))}</a>'
        f"{off}</nav>"
    )


def render(user: User, project: Project, items: list[Item]) -> str:
    """Project page body with the kanban board."""
    lang = user.language
    trashed = [i for i in items if i.status == "trash"]
    live = [i for i in items if i.status != "trash"]
    return fill(
        PROJECT,
        lang,
        PID=str(project.id),
        STATIONS=_stations(lang),
        NAME=esc(project.name),
        TRASH_ICON=icon("trash"),
        TRASH_COUNT=str(len(trashed)),
        TRASH=_trash(trashed, lang),
        COLUMNS="\n      ".join(_column(kind, live, lang) for kind in KINDS),
    )
