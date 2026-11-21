"""HTML of the project page: stations on the left, kanban board and trash on the right."""
from . import agents, aichoice, devices, i18n, managerpage, memory, questions, rolepage, status, statusnote, todos, ui
from .board import KINDS, Item
from .icons import icon
from .layout import esc, fill
from .projects import MAX_DESCRIPTION, MAX_NAME, Project
from .users import User

SCRIPTS = ("motion.js", "segment.js", "sortable.js", "board.js", "stations.js", "titlemenu.js", "chat.js", "picker.js", "manager.js", "splitter.js", "checks.js", "status.js", "devices.js", "devwin.js", "devsetup.js", "upload.js", "tiffthumb.js", "files.js", "filetidy.js", "mvault.js", "roles.js", "todos.js", "waiting.js", "export.js")
STYLES = ("project.css",)

COLUMN_LABEL = {"bug": "col_bug", "minor": "col_minor", "major": "col_major"}

PROJECT = """<div class="project" data-id="%PID%">
  %STATIONS%
  <div class="boardwrap" data-view-panel="board">
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
  %ROLES%
</div>
<dialog class="dialog" id="item-dialog" data-title-new="%t.new_item%" data-title-edit="%t.edit_item%"
        data-btn-new="%t.create%" data-btn-edit="%t.save%">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2 id="item-dialog-title">%t.new_item%</h2>
    <input type="hidden" name="kind" value="bug">
    <label>%t.item_title%<input name="title" required maxlength="200" autocomplete="off"></label>
    <label>%t.item_details%<textarea name="details" rows="5" maxlength="4000" placeholder="%t.item_details_hint%"></textarea></label>
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


# What a card says about its task (Janis, 15.11.2026): the stage, and the buttons of the user's decision.
# Since 19.11.2026 as text pills like accept and reject (Janis): the quieter one left, the stronger one right.
TASK_BUTTONS = {
    "awaiting_approval": (("agent-reject", "agent_reject", "quiet"), ("agent-approve", "agent_approve", "go")),
    "escalated": (("agent-cancel", "agent_cancel", "quiet"), ("agent-reject", "agent_reject", "go")),
}


def _pill(lang: str, action: str, label_key: str, css: str) -> str:
    """A small glass pill with text (Janis, 19.11.2026: accept and reject of a suggestion)."""
    return f'<button class="pill-btn {css}" type="button" data-action="{action}">{esc(i18n.t(lang, label_key))}</button>'


def _title(item: Item, lang: str, extra: str = "") -> str:
    """The bullet of a card; under it who put it there (the manager) and, folded, the context behind it (Janis,
    19.11.2026: a short bullet with the context in the background). A click on the bullet unfolds it (board.js)."""
    who = i18n.t(lang, "card_from_manager") if item.source == "manager" else ""
    if item.status == "proposed":   # a suggestion stands in the same list, marked as one
        who = i18n.t(lang, "card_proposal") + (f" · {who}" if who else "")
    by = f'<small class="card-from">{esc(who)}</small>' if who else ""
    more = f'<span class="card-details" hidden>{esc(item.details)}</span>' if item.details else ""
    return (f'<span class="card-title{" has-details" if item.details else ""}"><span class="card-text">{esc(item.title)}</span>'
            f'{by}{extra}{more}</span>')


DOTS = '<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span>'


def _task_card(item: Item, lang: str, task, report: str, waiting: str | None) -> str:
    """A card whose item is with the agents: its stage under the title (with moving dots while a role works on it,
    Janis 19.11.2026: you should see that it works), the last report behind an "i", and the user's buttons (approve
    or another round; a task that needs him: another round or cancel; else cancel). `data-live`: the board looks
    again every few seconds while such a card is on it (board.js)."""
    key = "task_no_ai" if waiting == "no_ai" else f"task_{task.status}"
    state = esc(i18n.t(lang, key)) + (DOTS if waiting == "running" else "")
    tip = ui.info_dot(i18n.t(lang, "agent_report"), report[:600]) if report else ""
    live = ' data-live="1"' if task.status in agents.ACTIVE and task.status != "awaiting_approval" else ""
    title = _title(item, lang, f'<small class="card-task" data-status="{esc(task.status)}"{live}>{state}{tip}</small>')
    pair = TASK_BUTTONS.get(task.status)
    if pair:
        pills = "".join(_pill(lang, action, key, css) for action, key, css in pair)
        return f'<article class="card with-task proposed-like" data-id="{item.id}">{title}<div class="card-choice">{pills}</div></article>'
    stop = _action_button(lang, "agent-cancel", "agent_cancel", "cross", "quiet no")
    return f'<article class="card with-task" data-id="{item.id}">{title}<div class="card-actions">{stop}</div></article>'


def _card(item: Item, lang: str, tasks: dict | None = None) -> str:
    entry = (tasks or {}).get(item.id)
    if entry is not None and item.status == "open" and entry[0].status in agents.OPEN_STATUSES:
        return _task_card(item, lang, *entry)
    if item.status == "proposed":
        # Text pills (Janis, 19.11.2026, instead of the red and green circles): accepting starts it at once.
        pills = _pill(lang, "reject", "reject", "quiet") + _pill(lang, "accept", "accept", "go")
        return (f'<article class="card proposed" data-id="{item.id}">{_title(item, lang)}'
                f'<div class="card-choice">{pills}</div></article>')
    discard = _action_button(lang, "discard", "discard", "trash", "quiet")
    queued = item.auto and tasks is not None   # it goes to the programmer by itself as soon as there is room
    extra = f'<small class="card-task" data-live="1">{esc(i18n.t(lang, "task_queued"))}</small>' if queued else ""
    start = (_action_button(lang, "agent-start", "agent_start", "play", "quiet start")
             if tasks is not None and not item.auto else "")   # only an item from before or one the user stopped
    origin = f" from-{item.source}" if item.source != "user" else ""
    return f'<article class="card{origin}" data-id="{item.id}">{_title(item, lang, extra)}{start}{discard}</article>'


def _column(kind: str, items: list[Item], lang: str, tasks: dict | None = None) -> str:
    agreed = [i for i in items if i.kind == kind and i.status == "open"]
    proposed = [i for i in items if i.kind == kind and i.status == "proposed"]   # in the same list, below (19.11.2026)
    add = esc(i18n.t(lang, "add_item"))
    return (
        f'<section class="column glass" data-kind="{kind}">'
        f'<header class="column-head"><h2>{esc(i18n.t(lang, COLUMN_LABEL[kind]))}</h2>'
        f'<span class="count">{len(agreed) + len(proposed)}</span>'
        f'<button class="icon-button add" type="button" data-kind="{kind}" aria-label="{add}" title="{add}">'
        f'{icon("plus")}</button></header>'
        f'<div class="cards open-list" data-kind="{kind}">{"".join(_card(i, lang, tasks) for i in agreed + proposed)}</div>'
        f"</section>"
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


# The cycle of an idea, top to bottom (Janis, 07.11.2026); a click swaps the main window (web/app/static/stations.js),
# the stations stay. Since 15.11.2026 every station has a view (the role views: rolepage.py).
VIEWS = (("board", "station_board"), ("manager", "station_manager"),
         *((name, f"station_{name}") for name in rolepage.VIEWS))


def _stations(lang: str, waiting: int = 0) -> str:
    def view(name: str, key: str) -> str:
        current = ' aria-current="page"' if name == "board" else ""
        active = " active" if name == "board" else ""
        # the open entries of "For you"; always there (hidden at 0), so todos.js can swap it
        badge = (f'<span class="station-count" id="me-badge"{"" if waiting else " hidden"}>{waiting}</span>'
                 if name == "me" else "")
        return (
            f'<a class="station{active}" href="#{name}" data-seg data-station="{name}"{current}>'
            f'<span class="station-label">{esc(i18n.t(lang, key))}</span>{badge}</a>'
        )

    # The thumb of the segment slider (segment.js, Janis 14.11.2026): it lies under the open station, juts out to
    # the right, and can be dragged up and down to another station.
    return (
        f'<nav class="stations" aria-label="{esc(i18n.t(lang, "stations"))}">'
        f'<span class="station-thumb" aria-hidden="true"></span>'
        f'{"".join(view(name, key) for name, key in VIEWS)}</nav>'
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
    board = button("archive", "archive", "done") + button("trash", "trash", "trash")
    # The same two buttons for the Manager view (Janis, 14.11.2026): same look and feel, other jobs: the chat archive
    # (an inbox) and the trash of the files. Only one pair is shown at a time (project.css, body.manager-open).
    def manager(view: str, label_key: str, icon_name: str) -> str:
        label = esc(i18n.t(lang, label_key))
        return (
            f'<button class="drawer-extra m-extra" id="m{view}-toggle" type="button" data-mview="{view}" '
            f'aria-pressed="false" aria-controls="mvault" aria-label="{label}" title="{label}">{icon(icon_name)}</button>'
        )
    return board + manager("archive", "chat_archive", "inbox") + manager("trash", "trash", "trash")


def _tasks(user: User, project: Project) -> dict:
    """item id -> (task, last report, waiting reason) for the cards of the board."""
    return {item_id: (task, agents.last_report(user.id, task.id), agents.waiting_reason(user.id, task))
            for item_id, task in agents.tasks_by_item(user.id, project.id).items()}   # waiting: no_ai, running


def render(user: User, project: Project, items: list[Item], regular_checks: list | None = None,
           stored_files: list | None = None, trashed_files: list | None = None) -> str:
    """Project page body with the kanban board and the Manager view (with the regular checks)."""
    lang = user.language
    trashed = [i for i in items if i.status == "trash"]
    archived = [i for i in items if i.status == "archived"]
    live = [i for i in items if i.status not in ("trash", "archived")]
    tasks = _tasks(user, project)
    settings, ais = agents.settings(user.id), (aichoice.default(user.id),)
    current = agents.current_task(user.id, project.id)
    roles = "".join(rolepage.render_role(lang, role, settings, agents.role_runs(user.id, project.id, role),
                                         agents.usage(user.id, project.id, role), ais, current=current)
                    for role in rolepage.ROLES)
    waiting = [(t, agents.last_report(user.id, t.id)) for t in agents.waiting_tasks(user.id, project.id)]
    entries = todos.list_todos(user.id, project.id)
    return fill(
        PROJECT,
        lang,
        PID=str(project.id),
        STATIONS=_stations(lang, sum(1 for t in entries if not t.done)),
        MANAGER=managerpage.render(lang, settings, regular_checks or [], stored_files=stored_files or [],
                                    files_confirm=user.files_confirm, trashed_files=trashed_files or [],
                                    ais=ais, waiting=waiting, versions=memory.versions(user.id, project.id),
                                    assessment=status.assess(user.id, project.id),
                                    device_list=devices.list_devices(user.id, project.id),
                                    note=statusnote.latest(user.id, project.id),
                                    asks=devices.open_requests(user.id, project.id),
                                    open_questions=questions.open_questions(user.id, project.id)),
        ROLES=roles + rolepage.render_me(lang, entries),
        MANAGER_DIALOGS=managerpage.dialogs(lang) + "\n" + rolepage.dialogs(lang),
        TRASH=_trash(trashed, lang),
        ARCHIVE=_archive(archived, lang),
        COLUMNS="\n      ".join(_column(kind, live, lang, tasks) for kind in KINDS),
    )
