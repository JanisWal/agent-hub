"""HTML of the project page: stations on the left, kanban board and trash on the right."""
from . import i18n
from .board import Item
from .dashboard import TRASH, validation_attrs
from .layout import esc as _e
from .layout import fill
from .projects import Project
from .users import User

COLUMNS = (("bug", "col_bug"), ("minor", "col_minor"), ("major", "col_major"))


def _icon(path: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{path}</svg>'


PLUS = _icon('<path d="M12 5v14M5 12h14"/>')
CHECK = _icon('<path d="M5 12.5l5 5 9-10"/>')
CROSS = _icon('<path d="M6 6l12 12M18 6L6 18"/>')
UNDO = _icon('<path d="M9 14L4 9l5-5"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>')
BACK = _icon('<path d="M15 6l-6 6 6 6"/>')


def _action_button(action: str, label: str, icon: str, extra_class: str = "") -> str:
    return (
        f'<button class="icon-button card-btn {extra_class}" type="button" '
        f'data-action="{action}" aria-label="{_e(label)}" title="{_e(label)}">{icon}</button>'
    )


def _card(item: Item, lang: str) -> str:
    title = f'<span class="card-title">{_e(item.title)}</span>'
    if item.status == "proposed":
        buttons = _action_button("accept", i18n.t(lang, "accept"), CHECK, "ok") + _action_button(
            "reject", i18n.t(lang, "reject"), CROSS, "no"
        )
        return f'<article class="card proposed" data-id="{item.id}">{title}<div class="card-actions">{buttons}</div></article>'
    discard = _action_button("discard", i18n.t(lang, "discard"), TRASH, "quiet")
    return f'<article class="card" data-id="{item.id}">{title}{discard}</article>'


def _column(kind: str, label_key: str, items: list[Item], lang: str) -> str:
    mine = [i for i in items if i.kind == kind]
    agreed = [i for i in mine if i.status == "open"]
    proposed = [i for i in mine if i.status == "proposed"]
    suggestions = ""
    if proposed:
        suggestions = (
            f'<p class="group-label">{_e(i18n.t(lang, "claude_suggestions"))}</p>'
            f'<div class="cards proposed-list">{"".join(_card(i, lang) for i in proposed)}</div>'
        )
    label = _e(i18n.t(lang, label_key))
    return (
        f'<section class="column glass" data-kind="{kind}">'
        f'<header class="column-head"><h2>{label}</h2><span class="count">{len(agreed) + len(proposed)}</span>'
        f'<button class="icon-button add" type="button" data-kind="{kind}" '
        f'aria-label="{_e(i18n.t(lang, "add_item"))}" title="{_e(i18n.t(lang, "add_item"))}">{PLUS}</button></header>'
        f'<div class="cards open-list" data-kind="{kind}">{"".join(_card(i, lang) for i in agreed)}</div>'
        f"{suggestions}</section>"
    )


def _trash_row(item: Item, lang: str) -> str:
    kind_label = dict(COLUMNS)[item.kind]
    restore = _action_button("restore", i18n.t(lang, "restore"), UNDO)
    delete = _action_button("delete", i18n.t(lang, "delete_now"), CROSS, "no")
    return (
        f'<li class="trash-row" data-id="{item.id}"><span class="trash-title">{_e(item.title)}'
        f'<small>{_e(i18n.t(lang, kind_label))}</small></span>{restore}{delete}</li>'
    )


def _trash(items: list[Item], lang: str) -> str:
    if not items:
        return f'<p class="muted">{_e(i18n.t(lang, "trash_is_empty"))}</p>'
    rows = "".join(_trash_row(i, lang) for i in items)
    return (
        f'<ul class="trash-list">{rows}</ul>'
        f'<button class="link inline" type="button" id="trash-empty">{_e(i18n.t(lang, "trash_empty"))}</button>'
    )


def _stations(lang: str) -> str:
    soon = _e(i18n.t(lang, "coming_soon"))
    off = "".join(
        f'<span class="station off" aria-disabled="true" title="{soon}">{_e(i18n.t(lang, key))}</span>'
        for key in ("station_agents", "station_files", "station_docs")
    )
    return (
        f'<nav class="stations glass" aria-label="{_e(i18n.t(lang, "stations"))}">'
        f'<a class="station back" href="/">{BACK}{_e(i18n.t(lang, "back_to_projects"))}</a>'
        f'<a class="station active" href="#" aria-current="page">{_e(i18n.t(lang, "station_board"))}</a>'
        f"{off}</nav>"
    )


PROJECT = """<div class="project" data-id="%PID%">
  %STATIONS%
  <div class="boardwrap">
    <header class="board-head">
      <h1>%NAME%</h1>
      <button class="icon-button trash-toggle" id="trash-toggle" type="button" aria-expanded="false"
              aria-controls="trash" aria-label="%L_TRASH%" title="%L_TRASH%">%TRASH_ICON%<span class="count">%TRASH_COUNT%</span></button>
    </header>
    <section class="trash glass" id="trash" hidden>
      <h2>%L_TRASH%</h2>
      %TRASH%
    </section>
    <div class="board">
      %COLUMNS%
    </div>
  </div>
</div>
<dialog class="dialog" id="item-dialog" data-title-new="%L_NEW_ITEM%" data-title-edit="%L_EDIT_ITEM%"
        data-btn-new="%L_CREATE%" data-btn-edit="%L_SAVE%">
  <form method="post" action="" novalidate %VALIDATION%>
    <h2 id="item-dialog-title">%L_NEW_ITEM%</h2>
    <input type="hidden" name="kind" value="bug">
    <label>%L_ITEM_TITLE%<input name="title" required maxlength="200" autocomplete="off"></label>
    <div class="actions">
      <button type="button" data-close>%L_CANCEL%</button>
      <button class="primary" type="submit" id="item-dialog-button">%L_CREATE%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="confirm-dialog" data-msg-item="%MSG_ITEM%" data-msg-empty="%MSG_EMPTY%">
  <h2 id="confirm-text"></h2>
  <div class="actions">
    <button type="button" data-close autofocus>%L_CANCEL%</button>
    <button class="danger-btn" type="button" id="confirm-yes">%L_YES%</button>
  </div>
</dialog>"""


def render(user: User, project: Project, items: list[Item]) -> str:
    """Project page body with the kanban board."""
    lang = user.language
    trashed = [i for i in items if i.status == "trash"]
    live = [i for i in items if i.status != "trash"]
    columns = "\n      ".join(_column(kind, key, live, lang) for kind, key in COLUMNS)
    return fill(
        PROJECT,
        PID=str(project.id),
        STATIONS=_stations(lang),
        NAME=_e(project.name),
        L_TRASH=_e(i18n.t(lang, "trash")),
        TRASH_ICON=TRASH,
        TRASH_COUNT=str(len(trashed)),
        TRASH=_trash(trashed, lang),
        COLUMNS=columns,
        VALIDATION=validation_attrs(lang),
        L_NEW_ITEM=_e(i18n.t(lang, "new_item")),
        L_EDIT_ITEM=_e(i18n.t(lang, "edit_item")),
        L_ITEM_TITLE=_e(i18n.t(lang, "item_title")),
        L_CREATE=_e(i18n.t(lang, "create")),
        L_SAVE=_e(i18n.t(lang, "save")),
        L_CANCEL=_e(i18n.t(lang, "cancel")),
        L_YES=_e(i18n.t(lang, "yes")),
        MSG_ITEM=_e(i18n.t(lang, "confirm_delete_item")),
        MSG_EMPTY=_e(i18n.t(lang, "confirm_empty_trash")),
    )
