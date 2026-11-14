"""HTML of the Manager view: the second view of the project page (station "Manager").

Janis, 07.11.2026: a click on "Manager" hides the board; the stations on the left stay and the main
window shows the manager's things. Layout from his sketch, three columns. Left: the status and the
devices (tall). Middle: the regular checks and the files (they take the free space). Right, where the
old chat window used to sit: the manager chat (big) above "waiting for you". The project name and
description are not here but in the drop-down at the pencil next to the title (projectpage.title_html).
The manager chat works (chat.py); status and "waiting for you" are empty, devices, checks and files announced.
"""
import time

from urllib.parse import urlsplit

from . import checks, files as filestore, i18n, serversettings, ui
from .icons import icon
from .layout import esc, fill

MANAGER = """<section class="manager" id="manager-view" aria-label="%t.station_manager%" hidden>
  <div class="mcol">
    <section class="mtile glass m-status">
      <header><h2>%t.manager_status%</h2><span class="m-lamp" title="%t.manager_status_none%"></span></header>
      <p class="muted">%t.manager_status_empty%</p>
    </section>
    %DEVICES%
  </div>
  <div class="mcol">
    %CHECKS%
    <div class="m-split" data-split="checks-files" role="separator" aria-orientation="horizontal" tabindex="0" aria-label="%t.split_label%"></div>
    %FILES%
  </div>
  <div class="mcol">
    %CHAT%
    <div class="m-split" data-split="chat-waiting" role="separator" aria-orientation="horizontal" tabindex="0" aria-label="%t.split_label%"></div>
    <section class="mtile glass m-waiting">
      <header><h2>%t.manager_waiting%</h2>%AUTONOMY%<span class="count">0</span></header>
      <p class="muted">%t.manager_waiting_empty%</p>
    </section>
  </div>
</section>"""


# The manager chat (web/app/chat.py, static/chat.js): it replaced the slim single-question window at the right
# edge. Web search and code are always there (no switches, Janis 07.11.2026); model and effort level (two drop-downs,
# ui.model_picker) are settings of the manager, so they hold for everything the manager does (manager.js saves them).
CHAT = """<section class="mtile glass m-chat" id="chat" data-you="%t.chat_you%" data-claude="%t.station_manager%"
             data-waiting="%t.chat_waiting%" data-failed="%t.chat_failed%" data-memory="%t.chat_memory_saved%"
             data-fail-auth="%t.chat_fail_auth%" data-fail-timeout="%t.chat_fail_timeout%"
             data-fail-steps="%t.chat_fail_steps%" data-fail-other="%t.chat_fail_other%">
      <header><h2>%t.manager_chat%</h2>%INFO%<span class="m-chat-tools">%NET%%MODEL%</span></header>
      <ol class="chat-log" id="chat-log" aria-live="polite"></ol>
      <p class="error" id="chat-error" role="alert" hidden></p>
      <form class="chat-form" id="chat-form" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
        <label><textarea name="prompt" id="chat-input" rows="1" required maxlength="2000" autocomplete="off"
          placeholder="%t.chat_placeholder%" aria-label="%t.chat_placeholder%"></textarea></label>
        <button class="icon-button chat-send" type="submit" id="chat-send" aria-label="%t.chat_send%">%SEND%</button>
      </form>
    </section>"""

AUTONOMY = (("auto", "autonomy_auto"), ("major", "autonomy_major"), ("all", "autonomy_all"))


def _select(lang: str, name: str, label_key: str, options: tuple, current: str) -> str:
    """A setting of the manager as a drop-down in our own style (core.js `.has-select` builds the list)."""
    label = esc(i18n.t(lang, label_key))
    items = "".join(
        f'<option value="{value}"{" selected" if value == current else ""}>{esc(i18n.t(lang, key))}</option>'
        for value, key in options
    )
    return (
        f'<label class="m-select has-select"><select name="{name}" data-setting="{name}" id="manager-{name}" '
        f'aria-label="{label}">{items}</select>{icon("chevron_down")}</label>'   # no title: its tip would cover the list
    )


def _soon(lang: str, title: str, hint: str, css: str = "") -> str:
    """A tile that is announced but not built: title, one line, and the "later" tag."""
    later = esc(i18n.t(lang, "coming_soon"))
    return (
        f'<section class="mtile glass m-soon {css}"><header><h2>{esc(i18n.t(lang, title))}</h2>'
        f'<span class="m-tag">{later}</span></header>'
        f'<p class="muted">{esc(i18n.t(lang, hint))}</p></section>'
    )


CYCLES = (("daily", "cycle_daily"), ("weekly", "cycle_weekly"), ("monthly", "cycle_monthly"),
          ("quarterly", "cycle_quarterly"))

CHECK_DIALOGS = """<dialog class="dialog" id="check-dialog" data-title-new="%t.checks_new%" data-title-edit="%t.checks_edit%"
        data-btn-new="%t.create%" data-btn-edit="%t.save%">
  <form method="post" action="" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2 id="check-dialog-title">%t.checks_new%</h2>
    <label>%t.checks_text%<input name="text" required maxlength="%MAX_TEXT%" autocomplete="off" placeholder="%t.checks_placeholder%"></label>
    <label class="setting has-select">
      <span class="setting-label">%t.checks_cycle%</span>
      <select name="cycle">%CYCLES%</select>
      %CHEVRON%
    </label>
    <div class="setting check-days" id="check-days" role="group" aria-label="%t.checks_days%">
      <span class="setting-label">%t.checks_days%</span>
      <div class="check-days-row">%DAYS%</div>
    </div>
    <p class="error" role="alert" id="check-days-error" hidden>%t.checks_days_none%</p>
    <button class="link" type="button" id="check-dialog-done" hidden>%t.checks_mark_done%</button>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit" id="check-dialog-button">%t.create%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="check-confirm">
  <h2>%t.checks_confirm_delete%</h2>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="check-confirm-yes">%t.yes%</button>
  </div>
</dialog>"""


def dialogs(lang: str) -> str:
    """The dialogs of the Manager view. They sit outside the view: a modal dialog inside a hidden element
    would not show (projectpage puts them next to the other dialogs)."""
    options = "".join(
        f'<option value="{value}">{esc(i18n.t(lang, key))}</option>' for value, key in CYCLES
    )
    days = "".join(   # seven circles with two letters; the box is hidden and the circle shows the state
        f'<label class="check-day"><input type="checkbox" name="day" value="{n}" checked '
        f'aria-label="{esc(i18n.t(lang, f"day_full_{n}"))}">'
        f'<span aria-hidden="true">{esc(i18n.t(lang, f"day_short_{n}"))}</span></label>'
        for n in range(7)
    )
    areas = "".join(
        f'<option value="{value}">{esc(i18n.t(lang, key))}</option>' for value, key in FILE_TABS if value != "links"
    )
    return fill(CHECK_DIALOGS, lang, MAX_TEXT=str(checks.MAX_TEXT), CYCLES=options, DAYS=days,
                CHEVRON=icon("chevron_down")) + "\n" + fill(FILE_DIALOGS, lang, AREAS=areas, CHEVRON=icon("chevron_down"),
                                                         DOWNLOAD=icon("download"), CROSS=icon("cross"), PENCIL=icon("pencil"),
                                                         MANY=esc(i18n.t(lang, "files_confirm_delete_many", n="{n}")),
                                                         PREV=icon("arrow_left"), NEXT=icon("chevron_right"))


def _ago(lang: str, last_done: int, now: int) -> str:
    days = max(0, (now - last_done) // checks.DAY)
    if days == 0:
        return i18n.t(lang, "checks_done_today")
    if days == 1:
        return i18n.t(lang, "checks_done_yesterday")
    return i18n.t(lang, "checks_done_days", n=days)


def _check_row(lang: str, check: checks.Check, now: int) -> str:
    cycle = i18n.t(lang, "cycle_" + check.cycle)
    if check.cycle == "daily" and check.days != checks.ALL_DAYS:   # "Mo, Mi, Fr" instead of "Täglich"
        cycle = ", ".join(i18n.t(lang, f"day_short_{n}") for n in checks.day_numbers(check.days))
    due = check.is_due(now)
    state = i18n.t(lang, "checks_due") if due else _ago(lang, check.last_done, now)
    edit_label = esc(i18n.t(lang, "checks_edit"))
    delete_label = esc(i18n.t(lang, "checks_delete"))
    flag = " due" if due else ""
    return (
        f'<li class="check-row{flag}" data-id="{check.id}" data-cycle="{check.cycle}" data-days="{check.days}">'
        f'<span class="check-text"><span class="check-title">{esc(check.text)}</span>'
        f'<small>{esc(cycle)} · {esc(state)}</small></span>'
        f'<button class="icon-button card-btn" type="button" data-check="edit" aria-label="{edit_label}" '
        f'title="{edit_label}">{icon("pencil")}</button>'
        f'<button class="icon-button card-btn no" type="button" data-check="delete" aria-label="{delete_label}" '
        f'title="{delete_label}">{icon("trash")}</button></li>'
    )


def _checks_tile(lang: str, regular: list, now: int) -> str:
    """The regular checks: a list with the plus in the header (Janis, 07.11.2026); due ones are marked."""
    add = esc(i18n.t(lang, "checks_add"))
    if regular:
        body = f'<ul class="check-list">{"".join(_check_row(lang, c, now) for c in regular)}</ul>'
    else:
        body = f'<p class="muted">{esc(i18n.t(lang, "manager_checks_hint"))}</p>'
    return (
        f'<section class="mtile glass m-checks" id="checks"><header><h2>{esc(i18n.t(lang, "manager_checks"))}</h2>'
        f'<span class="count">{len(regular)}</span>'
        f'<button class="icon-button m-add" id="check-add" type="button" aria-label="{add}" title="{add}">'
        f'{icon("plus")}</button></header>{body}</section>'
    )


FILE_TABS = (("memory", "files_tab_memory"), ("code", "files_tab_code"), ("media", "files_tab_media"),
             ("documents", "files_tab_documents"), ("links", "files_tab_links"))
TAB_ICON = {"memory": "note", "code": "code", "media": "photo", "documents": "file", "links": "link"}
KIND_ICON = {"link": "link", "image": "photo", "video": "film", "audio": "music", "code": "code", "text": "note",
             "other": "file"}

FILE_DIALOGS = """<dialog class="dialog" id="file-dialog" data-title-link="%t.files_new_link%" data-title-edit="%t.files_edit%"
        data-title-edit-link="%t.files_edit_link%" data-btn-new="%t.create%" data-btn-edit="%t.save%">
  <form method="post" action="" novalidate>
    <h2>%t.files_edit%</h2>
    <label>%t.files_name%<input name="name" maxlength="120" autocomplete="off"></label>
    <label id="file-url-box" hidden>%t.files_url%<input name="url" maxlength="2000" autocomplete="off" inputmode="url" placeholder="https://"></label>
    <label class="setting has-select" id="file-area-box">
      <span class="setting-label">%t.files_area%</span>
      <select name="category">%AREAS%</select>
      %CHEVRON%
    </label>
    <p class="error" role="alert" id="file-dialog-error" hidden></p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit" id="file-dialog-button">%t.save%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="file-confirm" data-text-file="%t.files_confirm_delete%" data-text-link="%t.files_confirm_delete_link%" data-text-many="%MANY%">
  <h2>%t.files_confirm_delete%</h2>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="file-confirm-yes">%t.yes%</button>
  </div>
</dialog>
<dialog class="dialog" id="file-same" data-one="%t.files_same_one%" data-many="%t.files_same_many%">
  <h2>%t.files_same_title%</h2>
  <p class="muted" id="file-same-text"></p>
  <ul class="file-same-list" id="file-same-list"></ul>
  <div class="actions three">
    <button type="button" data-same="skip">%t.files_same_skip%</button>
    <button type="button" data-same="replace">%t.files_same_replace%</button>
    <button class="primary" type="button" data-same="keep" autofocus>%t.files_same_keep%</button>
  </div>
</dialog>
<dialog class="dialog viewer reader" id="file-reader">
  <div class="viewer-head">
    <h2 id="file-reader-title"></h2>
    <button class="icon-button card-btn" type="button" id="file-reader-edit" aria-label="%t.files_edit_text%" title="%t.files_edit_text%">%PENCIL%</button>
    <button class="icon-button card-btn" type="button" id="file-reader-download" aria-label="%t.files_download%" title="%t.files_download%">%DOWNLOAD%</button>
    <button class="icon-button card-btn" type="button" data-close aria-label="%t.files_close%" title="%t.files_close%">%CROSS%</button>
  </div>
  <div class="reader-body" id="file-reader-body"></div>
  <textarea class="reader-edit" id="file-reader-text" spellcheck="false" hidden></textarea>
  <p class="error" role="alert" id="file-reader-error" hidden></p>
  <div class="actions" id="file-reader-actions" hidden>
    <button type="button" id="file-reader-cancel">%t.cancel%</button>
    <button class="primary" type="button" id="file-reader-save">%t.save%</button>
  </div>
</dialog>
<dialog class="dialog viewer" id="file-viewer">
  <div class="viewer-head">
    <h2 id="file-viewer-title"></h2>
    <button class="icon-button card-btn" type="button" id="file-viewer-download" aria-label="%t.files_download%" title="%t.files_download%">%DOWNLOAD%</button>
    <button class="icon-button card-btn" type="button" data-close aria-label="%t.files_close%" title="%t.files_close%">%CROSS%</button>
  </div>
  <div class="viewer-body" id="file-viewer-body"></div>
  <button class="icon-button viewer-nav prev" type="button" id="file-viewer-prev" aria-label="%t.files_prev%" title="%t.files_prev%" hidden>%PREV%</button>
  <button class="icon-button viewer-nav next" type="button" id="file-viewer-next" aria-label="%t.files_next%" title="%t.files_next%" hidden>%NEXT%</button>
</dialog>"""


def _size(lang: str, size: int) -> str:
    """File size for people: 1,4 MB (a decimal comma in German)."""
    value, unit = float(size), "B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            break
        value /= 1024
    text = f"{value:.0f}" if unit == "B" or value >= 100 else f"{value:.1f}"
    return (text.replace(".", ",") if lang == "de" else text) + " " + unit


def _origin(url: str) -> str:
    """Scheme, host and port of an address: the icon of a link is the site's own /favicon.ico, which the browser
    loads itself (nothing is fetched by the server; a missing icon simply does not show)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    host = f"[{host}]" if ":" in host else host
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        port = ""
    return f"{parts.scheme}://{host}{port}"


def _file_row(lang: str, item: filestore.StoredFile) -> str:
    """One file or link: a small bordered card with a rounded square with the type symbol, a preview next to it only
    where there is something to see (a small picture of an image or video, the icon of a website), the name with
    its ending (a click downloads the file, opens the link, or opens the editor of a text), pencil and bin."""
    kind = item.kind
    edit_label, delete_label = esc(i18n.t(lang, "files_edit")), esc(i18n.t(lang, "files_delete"))
    preview = ""
    if kind == "link":
        icon_url = esc(_origin(item.url or "") + "/favicon.ico")
        preview = (f'<img class="file-preview file-favicon" src="{icon_url}" alt="" loading="lazy" decoding="async" '
                   f'referrerpolicy="no-referrer" draggable="false">')
        href, sub, target = esc(item.url or ""), esc(item.url or ""), ' target="_blank" rel="noopener noreferrer"'
    else:
        if kind in ("image", "video"):
            if filestore.has_thumb(item):
                preview = (f'<img class="file-preview" src="/files/{item.id}/thumb" alt="" loading="lazy" '
                           f'decoding="async" draggable="false">')
            else:   # files.js makes the small picture once, in the browser
                preview = f'<span class="file-preview file-pending" data-need-thumb="{kind}"></span>'
        href, sub, target = f"/files/{item.id}?download=1", esc(_size(lang, item.size)), ""
    return (
        f'<li class="file-row" draggable="true" data-id="{item.id}" data-cat="{item.category}" data-kind="{kind}" '
        f'data-name="{esc(item.name)}" data-url="{esc(item.url or "")}" data-editable="{1 if item.editable else 0}">'
        f'<span class="file-tile">{icon(KIND_ICON[kind])}</span>{preview}'
        f'<a class="file-text" href="{href}"{target} draggable="false"><span class="check-title">{esc(item.name)}</span><small>{sub}</small></a>'
        f'<button class="icon-button card-btn" type="button" data-file="edit" aria-label="{edit_label}" '
        f'title="{edit_label}">{icon("pencil")}</button>'
        f'<button class="icon-button card-btn no" type="button" data-file="delete" aria-label="{delete_label}" '
        f'title="{delete_label}">{icon("trash")}</button></li>'
    )


def _upload_template(lang: str) -> str:
    """One row of the upload list (files.js copies it for every file): name, speed and time left, a cross to
    cancel, and the thin bar."""
    cancel = esc(i18n.t(lang, "cancel"))
    return (
        '<template id="file-up-template"><li class="file-up"><span class="file-up-name"></span>'
        '<span class="file-up-meta"></span>'
        f'<button class="icon-button card-btn file-up-x" type="button" aria-label="{cancel}" title="{cancel}">{icon("cross")}</button>'
        '<span class="file-bar"><i></i></span></li></template>'
    )


def _files_tile(lang: str, items: list, files_confirm: bool = True) -> str:
    """The files of the project in five areas as tabs (Janis, 12.11.2026). The plus uploads (or adds a link in
    the Links tab); files can also be dragged onto the tile. static/files.js does the rest."""
    tabs, panels = [], []
    for category, key in FILE_TABS:
        mine = [f for f in items if f.category == category]
        name = esc(i18n.t(lang, key))
        tabs.append(   # symbol when the tile is narrow, name when it is wide (CSS container query), always one row
            f'<button class="file-tab" type="button" role="tab" data-seg data-cat="{category}" data-name="{name}" title="{name}" '
            f'aria-label="{name}" aria-selected="false">{icon(TAB_ICON[category])}'
            f'<span class="file-tab-label">{name}</span><span class="file-count">{len(mine)}</span></button>'
        )
        body = "".join(_file_row(lang, f) for f in mine) or \
            f'<li class="file-empty muted">{esc(i18n.t(lang, "files_hint_" + category))}</li>'
        panels.append(f'<ul class="file-list" data-cat="{category}" hidden>{body}</ul>')
    attrs = " ".join(f'data-{name}="{esc(i18n.t(lang, key, n="{n}", name="{name}"))}"' for name, key in (
        ("add-file", "files_add_file"), ("add-link", "files_add_link"), ("err-net", "files_err_net"),
        ("eta-s", "files_eta_s"), ("eta-m", "files_eta_m"), ("eta-h", "files_eta_h"), ("drop-to", "files_drop_to"),
        ("starting", "files_starting"), ("waiting", "files_waiting"), ("expand", "files_expand"), ("collapse", "files_collapse"),
        ("note-no-ask", "files_note_no_ask"), ("note-ask", "files_note_ask"), ("delete-selected", "files_delete_selected"),
        ("drop", "files_drop"), ("marked", "files_marked"), ("zip-name", "files_zip_name"),
        ("download-marked", "files_download_marked")))
    parallel = serversettings.upload()[0]           # how uploads are cut: the owner's choice for the whole server
    attrs += (f' data-block="{filestore.BLOCK_SIZE}" data-parallel="{parallel}" data-max-request="{filestore.max_request()}"'
              f' data-confirm-delete="{1 if files_confirm else 0}"')
    return (
        f'<section class="mtile glass m-files m-grow" id="files" {attrs}>'
        f'<header><h2>{esc(i18n.t(lang, "manager_files"))}</h2><span class="file-area" aria-hidden="true"></span>'
        f'<span class="file-tools">'
        f'<button class="icon-button card-btn file-dl" id="file-download" type="button" tabindex="-1" aria-hidden="true">'
        f'{icon("download")}</button>'                     # shown while files are marked (files.js)
        f'<button class="icon-button m-add file-trash-mode" id="file-trash-mode" type="button" aria-pressed="false" '
        f'aria-label="{esc(i18n.t(lang, "files_ask_toggle"))}" title="{esc(i18n.t(lang, "files_ask_toggle"))}">{icon("trash")}</button>'
        f'<button class="icon-button m-add file-expand" id="file-expand" type="button" aria-pressed="false" '
        f'aria-label="{esc(i18n.t(lang, "files_expand"))}" title="{esc(i18n.t(lang, "files_expand"))}">'
        f'{icon("expand", "ic-expand")}{icon("collapse", "ic-collapse")}</button>'
        f'<button class="icon-button m-add" id="file-add" type="button">{icon("plus")}</button></span></header>'
        f'<div class="file-tabs" role="tablist"><span class="file-thumb" aria-hidden="true"></span>{"".join(tabs)}</div>'
        f'<p class="error" id="file-error" role="alert" hidden></p>'
        f'<div class="file-scroll"><ul class="file-uploads" id="file-uploads" hidden></ul>'
        f'{"".join(panels)}</div><input type="file" id="file-picker" multiple hidden>{_upload_template(lang)}'
        f'<p class="file-status" id="file-status" role="status" aria-live="polite"></p></section>'
    )


def _net_switch(lang: str, current: str) -> str:
    """"Web and code together" as a pill that looks like the drop-downs next to it (Janis, 14.11.2026). Pressed, it is
    red like the armed trash circle of the files: code then has the open internet (the bolder choice); not pressed,
    web search and code without internet. The tip says both."""
    label, tip = esc(i18n.t(lang, "net_together")), esc(i18n.t(lang, "net_together_tip"))
    pressed = "true" if current == "together" else "false"
    return (
        f'<button type="button" class="m-pill" id="manager-net" data-setting="net" data-on="together" data-off="apart" '
        f'aria-pressed="{pressed}" aria-label="{label}" data-tip="{tip}">{esc(i18n.t(lang, "net_pill"))}</button>'
    )


def render(lang: str, settings: dict, regular_checks: list | None = None, now: int | None = None,
           stored_files: list | None = None, files_confirm: bool = True) -> str:
    """`settings` is agents.settings(user_id): the manager is the role "chef". `regular_checks` are the
    project's checks (checks.list_checks)."""
    chef = settings["roles"]["chef"]
    model = ui.model_picker(lang, "manager", chef["model"], chef.get("effort", ""),
                            label_model="chat_model", label_effort="chat_effort")
    autonomy = _select(lang, "autonomy", "autonomy", AUTONOMY, settings["autonomy"])
    return fill(
        MANAGER,
        lang,
        DEVICES=_soon(lang, "manager_devices", "manager_devices_hint", "m-grow"),
        CHECKS=_checks_tile(lang, regular_checks or [], int(now if now is not None else time.time())),
        FILES=_files_tile(lang, stored_files or [], files_confirm),
        CHAT=fill(CHAT, lang, MODEL=model, SEND=icon("arrow_up"), NET=_net_switch(lang, settings["roles"]["chef"]["net"]),
                  INFO=ui.info_dot(i18n.t(lang, "manager_chat"), i18n.t(lang, "manager_chat_hint"))),
        AUTONOMY=autonomy,
    )
