"""HTML of the Manager view: the second view of the project page (station "Manager").

Janis, 07.11.2026: a click on "Manager" hides the board; the stations on the left stay and the main
window shows the manager's things. Layout from his sketch, three columns. Left: the status and the
devices (tall). Middle: the regular checks and the files (they take the free space). Right, where the
old chat window used to sit: the manager chat (big) above "waiting for you". The project name and
description are not here but in the drop-down at the pencil next to the title (projectpage.title_html).
The manager chat works (chat.py); "waiting for you" lists the decisions (approvals, tasks that need the user; Janis
16.11.2026); the status is an assessment counted from the data (status.py), the devices are a list with an encrypted key (devices.py).
"""
import time

from urllib.parse import urlsplit

from . import agents, catalog, checks, devicepage, files as filestore, i18n, serversettings, status as statusmod, statusnote, ui, vault
from .icons import icon
from .layout import esc, fill

MANAGER = """<section class="manager" id="manager-view" data-view-panel="manager" data-settings-url="/manager/settings" aria-label="%t.station_manager%" hidden>
  %MVAULT%
  <div class="mcol">
    %STATUS%
    <div class="m-split" data-split="status-devices" role="separator" aria-orientation="horizontal" tabindex="0" aria-label="%t.split_label%"></div>
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
    %WAITING_TILE%
  </div>
</section>"""


# The manager chat (web/app/chat.py, static/chat.js): it replaced the slim single-question window at the right
# edge. Web search and code are always there (no switches, Janis 07.11.2026); model and effort level (two drop-downs,
# ui.model_picker) are settings of the manager, so they hold for everything the manager does (manager.js saves them).
CHAT = """<section class="mtile glass m-chat" id="chat" data-you="%t.chat_you%" data-claude="%t.station_manager%"
             data-waiting="%WAITING%" data-ai="%AI%" data-failed="%t.chat_failed%" data-memory="%t.chat_memory_saved%"
             data-thoughts="%t.chat_thoughts%"
             data-fail-auth="%t.chat_fail_auth%" data-fail-timeout="%t.chat_fail_timeout%"
             data-fail-steps="%t.chat_fail_steps%" data-fail-limit="%t.chat_fail_limit%" data-fail-server="%t.chat_fail_server%" data-fail-other="%t.chat_fail_other%"
             data-fallback="%FALLBACK%">
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


def _when(lang: str, moment: int | None, now: int) -> str:
    """How long ago, roughly: "just now", minutes, hours, days."""
    if moment is None:
        return i18n.t(lang, "status_never")
    seconds = max(0, now - moment)
    if seconds < 120:
        return i18n.t(lang, "status_ago_now")
    if seconds < 3600:
        return i18n.t(lang, "status_ago_min", n=seconds // 60)
    if seconds < 86400:
        return i18n.t(lang, "status_ago_hours", n=seconds // 3600)
    return i18n.t(lang, "status_ago_days", n=seconds // 86400)


def _status_tile(lang: str, a: statusmod.Assessment | None, now: int, note: statusnote.Note | None = None) -> str:
    """The state of the project: the written status of the AI (statusnote.py) as headline and one or two sentences,
    else the counted wording (status.py); the lamp (the AI's level, never below what the hub counted), the progress,
    the numbers and what explains an amber or red lamp. The round arrow asks for a new written status."""
    lamp = statusnote.lamp(a.lamp if a else "none", note)
    again = esc(i18n.t(lang, "status_again"))
    head = (f'<header><h2>{esc(i18n.t(lang, "manager_status"))}</h2>'
            f'{ui.info_dot(i18n.t(lang, "manager_status"), i18n.t(lang, "status_hint"))}'
            f'<button class="icon-button card-btn status-again" type="button" id="status-again" aria-label="{again}" '
            f'data-tip="{again}" data-wait="{esc(i18n.t(lang, "status_again_wait"))}" '
            f'data-none="{esc(i18n.t(lang, "status_again_none"))}" data-queued="{esc(i18n.t(lang, "status_again_queued"))}" data-note="{note.created_at if note else 0}">{icon("refresh")}</button>'
            f'<span class="m-lamp lamp-{lamp}" role="img" aria-label="{esc(i18n.t(lang, "status_lamp_" + lamp))}" '
            f'data-tip="{esc(i18n.t(lang, "status_lamp_" + lamp))}"></span></header>')
    say = '<p class="muted status-say" id="status-say" role="status" aria-live="polite"></p>'
    if a is None or (a.total == 0 and a.last_activity is None and note is None):
        return (f'<section class="mtile glass m-status" id="status">{head}'
                f'<p class="muted">{esc(i18n.t(lang, "status_empty"))}</p>{say}</section>')
    facts = "".join(
        f'<div><dt>{esc(i18n.t(lang, key))}</dt><dd>{value}</dd></div>'
        for key, value in (("status_planned", a.planned), ("status_in_progress", a.in_progress),
                           ("status_waiting", a.waiting), ("status_done", a.done)))
    extra = [i18n.t(lang, key, n=n) for key, n in (("status_proposals", a.proposals), ("status_todos", a.todos_open),
                                                    ("status_checks_due", a.checks_due)) if n]
    reasons = "".join(f'<li>{esc(i18n.t(lang, "status_reason_" + code))}</li>' for code in a.reasons)
    if note is not None and note.title:
        headline = esc(note.title)
        when = esc(i18n.t(lang, "status_written", when=_when(lang, note.created_at, now)))
    else:
        headline = esc(i18n.t(lang, "status_activity_" + a.activity))
        when = esc(i18n.t(lang, "status_last", when=_when(lang, a.last_activity, now)))
    # the longer text of the AI comes last and is folded away at first (Janis, 17.11.2026): the splitter below the
    # tile shows it; at its highest point the tile shows everything but this text (splitter.js, class split-extra)
    written = f'<p class="status-note split-extra">{esc(note.text)}</p>' if note is not None and note.text else ""
    return (
        f'<section class="mtile glass m-status{" has-extra" if written else ""}" id="status">{head}'
        f'<p class="status-line"><strong>{headline}</strong><small>{when}</small></p>'
        f'<div class="status-progress"><progress max="100" value="{a.progress}" aria-label="{esc(i18n.t(lang, "status_progress", n=a.progress))}"></progress>'
        f'<span>{esc(i18n.t(lang, "status_progress", n=a.progress))}</span></div>'
        f'<dl class="status-facts">{facts}</dl>'
        + (f'<ul class="status-reasons">{reasons}</ul>' if reasons else "")
        + (f'<p class="muted status-extra">{esc(" · ".join(extra))}</p>' if extra else "")
        + say + written + '</section>'
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


MVAULT_DIALOGS = """<dialog class="dialog danger" id="mvault-confirm" data-purge="%t.files_trash_confirm_one%"
        data-empty="%t.files_trash_confirm_all%" data-day="%t.chat_archive_confirm%">
  <h2 id="mvault-confirm-text"></h2>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="mvault-confirm-yes">%t.yes%</button>
  </div>
</dialog>
<dialog class="dialog archive-day" id="archive-dialog" aria-labelledby="archive-dialog-title">
  <div class="viewer-head">
    <h2 id="archive-dialog-title"></h2>
    <button class="icon-button card-btn" type="button" data-close aria-label="%t.close%" title="%t.close%">%CROSS%</button>
  </div>
  <ol class="chat-log archive-log" id="archive-dialog-log"></ol>
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
    return fill(MVAULT_DIALOGS, lang, CROSS=icon("cross")) + "\n" + devicepage.dialogs(lang) + "\n" + fill(CHECK_DIALOGS, lang, MAX_TEXT=str(checks.MAX_TEXT), CYCLES=options, DAYS=days,
                CHEVRON=icon("chevron_down")) + "\n" + fill(FILE_DIALOGS, lang, AREAS=areas, CHEVRON=icon("chevron_down"),
                                                         DOWNLOAD=icon("download"), CROSS=icon("cross"), PENCIL=icon("pencil"),
                                                         MANY=esc(i18n.t(lang, "files_confirm_delete_many", n="{n}")),
                                                         PREV=icon("arrow_left"), NEXT=icon("chevron_right")) \
        + "\n" + _tidy_dialog(lang)


# Structure the folders automatically (autofolders.py, static/filetidy.js; Janis 18.11.2026): the switch, the three
# dots while the AI works, then the new tree with "Apply". The texts for the tree come as data attributes.
TIDY_DIALOG = """<dialog class="dialog tidy-dialog" id="file-tidy-dialog" %DATA%>
  <h2>%t.files_tidy%</h2>
  <div class="tidy-step" data-step="start">
    <div class="tidy-switch"><label class="check-line"><input type="checkbox" id="file-tidy-contents"><span>%t.tidy_contents%</span></label>%INFO%</div>
  </div>
  <p class="tidy-step tidy-working muted" data-step="working" hidden>%t.tidy_working%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p>
  <div class="tidy-step" data-step="plan" hidden>
    <p class="muted tidy-note" id="file-tidy-note"></p>
    <p class="tidy-summary" id="file-tidy-summary"></p>
    <ul class="tidy-tree" id="file-tidy-tree"></ul>
  </div>
  <p class="error" role="alert" id="file-tidy-error" hidden></p>
  <div class="actions">
    <button type="button" id="file-tidy-cancel">%t.cancel%</button>
    <button class="primary" type="button" id="file-tidy-go">%t.tidy_start%</button>
  </div>
</dialog>"""


def _tidy_dialog(lang: str) -> str:
    keys = {"start": "tidy_start", "apply": "tidy_apply", "discard": "tidy_discard", "cancel": "cancel",
            "close-label": "files_close", "summary": "tidy_summary", "nothing": "tidy_nothing", "failed": "tidy_failed",
            "fail-auth": "chat_fail_auth", "fail-limit": "chat_fail_limit", "moved-tag": "tidy_moved_tag",
            "new-tag": "tidy_new_tag", "done": "tidy_done", "err-net": "err_network"}
    data = " ".join(f'data-{name}="{esc(i18n.t(lang, key, n="{n}", moved="{moved}", folders="{folders}"))}"'
                    for name, key in keys.items())
    return fill(TIDY_DIALOG, lang, DATA=data, INFO=ui.info_dot(i18n.t(lang, "tidy_contents"), i18n.t(lang, "tidy_contents_tip")))


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
TAB_ICON = {"all": "folder", "memory": "note", "code": "code", "media": "photo", "documents": "file", "links": "link"}
KIND_ICON = {"link": "link", "image": "photo", "video": "film", "audio": "music", "code": "code", "text": "note",
             "photo": "photo", "pdf": "file", "other": "file", "folder": "folder"}

FILE_DIALOGS = """<dialog class="dialog" id="file-dialog" data-title-link="%t.files_new_link%" data-title-edit="%t.files_edit%"
        data-title-edit-link="%t.files_edit_link%" data-title-folder="%t.files_new_folder%"
        data-title-edit-folder="%t.files_edit_folder%" data-btn-new="%t.create%" data-btn-edit="%t.save%">
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
<dialog class="dialog danger" id="file-confirm" data-text-file="%t.files_confirm_delete%" data-text-link="%t.files_confirm_delete_link%"
        data-text-folder="%t.files_confirm_delete_folder%" data-text-many="%MANY%">
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


def _day(lang: str, moment: int) -> str:
    """The date a file was added, for the column of the explorer."""
    return time.strftime("%d.%m.%Y" if lang == "de" else "%Y-%m-%d", time.localtime(moment))


def _file_row(lang: str, item: filestore.StoredFile, where: list[str] | None = None, inside: int = 0) -> str:
    """One file, link or folder: a small bordered card with a rounded square with the type symbol, a preview next to it
    only where there is something to see (a small picture of an image or video, the icon of a website), the name with
    its ending (a click downloads the file, opens the link, opens the editor of a text, or opens the folder), pencil
    and bin. `where`: the folders above it (shown under the name in a label tab, and as the column "Folder" there in
    the explorer); `inside`: what a folder holds. `data-cat` is the label ('' for a folder). The size and date columns
    show only in the explorer (the enlarged tile); files.js shows and hides rows by `data-parent` and `data-cat`."""
    kind = item.kind
    edit_label, delete_label = esc(i18n.t(lang, "files_edit")), esc(i18n.t(lang, "files_delete"))
    preview, size = "", ""
    if kind == "folder":
        size = i18n.t(lang, "files_folder_none" if not inside else "files_folder_one" if inside == 1 else "files_folder_many",
                      n=inside)
        href, sub, target = "#", esc(size), ""
    elif kind == "link":
        icon_url = esc(_origin(item.url or "") + "/favicon.ico")
        preview = (f'<img class="file-preview file-favicon" src="{icon_url}" alt="" loading="lazy" decoding="async" '
                   f'referrerpolicy="no-referrer" draggable="false">')
        href, sub, target = esc(item.url or ""), esc(item.url or ""), ' target="_blank" rel="noopener noreferrer"'
    else:
        if kind in ("image", "video", "photo"):   # every picture gets a small preview (Janis, 14.11.2026)
            if filestore.has_thumb(item):
                preview = (f'<img class="file-preview" src="/files/{item.id}/thumb" alt="" loading="lazy" '
                           f'decoding="async" draggable="false">')
            else:   # files.js makes the small picture once, in the browser
                preview = f'<span class="file-preview file-pending" data-need-thumb="{kind}"></span>'
        size = _size(lang, item.size)
        href, sub, target = f"/files/{item.id}?download=1", esc(size), ""
    place = f'<span class="file-where"> · {esc(" › ".join(where))}</span>' if where else ""
    folder_col = esc(" › ".join(where)) if where else "–"
    return (
        f'<li class="file-row{" folder" if kind == "folder" else ""}" draggable="true" data-id="{item.id}" '
        f'data-cat="{item.category}" data-kind="{kind}" data-parent="{item.parent_id or ""}" '
        f'data-folder="{1 if kind == "folder" else 0}" '
        f'data-name="{esc(item.name)}" data-url="{esc(item.url or "")}" data-editable="{1 if item.editable else 0}" data-readable="{1 if item.readable else 0}">'
        f'<span class="file-tile">{icon(KIND_ICON[kind])}</span>{preview}'
        f'<a class="file-text" href="{href}"{target} draggable="false"><span class="check-title">{esc(item.name)}</span>'
        f'<small>{sub}{place}</small></a>'
        f'<span class="file-place">{folder_col}</span>'
        f'<span class="file-size">{esc(size if kind != "link" else "")}</span>'
        f'<span class="file-time">{esc(_day(lang, item.created_at))}</span>'
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
    """The files of the project (Janis, 12.11.2026; one folder tree and labels since 18.11.2026, `file-tags`): the tabs
    "All" (the folder tree, folder by folder, with the path line and a back arrow) and one per label (every file with
    that label, flat, its folder named under it). In the enlarged tile the explorer: the tree of folders on the left,
    each opened on its own, the columns on the right. One list holds every row; files.js shows the ones of the tab and
    folder chosen. The plus uploads (or adds a link in the Links tab), the folder circle makes a folder; files can also
    be dragged onto the tile. static/files.js does the rest."""
    inside: dict[int, int] = {}
    for f in items:
        if f.parent_id is not None:
            inside[f.parent_id] = inside.get(f.parent_id, 0) + 1
    tabs = []
    for category, key in (("all", "files_all"), *FILE_TABS):
        name = esc(i18n.t(lang, key))
        count = sum(not f.is_folder and category in ("all", f.category) for f in items)
        tabs.append(   # symbol when the tile is narrow, name when it is wide (CSS container query), always one row
            f'<button class="file-tab" type="button" role="tab" data-seg data-cat="{category}" data-name="{name}" title="{name}" '
            f'aria-label="{name}" aria-selected="false">{icon(TAB_ICON[category])}'
            f'<span class="file-tab-label">{name}</span><span class="file-count">{count}</span></button>'
        )
    hints = "".join(f'<li class="file-empty muted" data-hint="{c}" hidden>{esc(i18n.t(lang, "files_hint_" + c))}</li>'
                    for c in ("all", *(c for c, _ in FILE_TABS)))
    body = "".join(_file_row(lang, f, filestore.folder_path(items, f), inside.get(f.id, 0)) for f in items) + hints
    attrs = " ".join(f'data-{name}="{esc(i18n.t(lang, key, n="{n}", name="{name}"))}"' for name, key in (
        ("add-file", "files_add_file"), ("add-link", "files_add_link"), ("err-net", "files_err_net"),
        ("eta-s", "files_eta_s"), ("eta-m", "files_eta_m"), ("eta-h", "files_eta_h"), ("drop-to", "files_drop_to"),
        ("starting", "files_starting"), ("waiting", "files_waiting"), ("expand", "files_expand"), ("collapse", "files_collapse"),
        ("note-no-ask", "files_note_no_ask"), ("note-ask", "files_note_ask"), ("delete-selected", "files_delete_selected"),
        ("drop", "files_drop"), ("marked", "files_marked"), ("zip-name", "files_zip_name"),
        ("download-marked", "files_download_marked"), ("all", "files_all"), ("folder-empty", "files_folder_empty"),
        ("back", "files_back"), ("moved", "files_moved"), ("move-to", "files_move_to"), ("new-folder", "files_new_folder"),
        ("label-to", "files_label_to"), ("labelled", "files_labelled"), ("open-folder", "files_open_folder")))
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
        f'<button class="icon-button m-add file-full-only" id="file-tidy" type="button" aria-label="{esc(i18n.t(lang, "files_tidy"))}" '
        f'data-tip="{esc(i18n.t(lang, "files_tidy"))}">{icon("folder_auto")}</button>'
        f'<button class="icon-button m-add file-full-only" id="file-folder-add" type="button" aria-label="{esc(i18n.t(lang, "files_new_folder"))}" '
        f'data-tip="{esc(i18n.t(lang, "files_new_folder"))}">{icon("folder_plus")}</button>'
        f'<button class="icon-button m-add" id="file-add" type="button">{icon("plus")}</button></span></header>'
        f'<div class="file-tabs" role="tablist"><span class="file-thumb" aria-hidden="true"></span>{"".join(tabs)}</div>'
        f'<p class="error" id="file-error" role="alert" hidden></p>'
        f'<div class="file-body"><nav class="file-tree" aria-label="{esc(i18n.t(lang, "files_folders"))}"></nav>'
        f'<div class="file-main"><nav class="file-crumbs" hidden></nav>'
        f'<div class="file-cols" aria-hidden="true"><span>{esc(i18n.t(lang, "files_col_name"))}</span>'
        f'<span class="col-place">{esc(i18n.t(lang, "files_col_folder"))}</span>'
        f'<span>{esc(i18n.t(lang, "files_col_size"))}</span><span>{esc(i18n.t(lang, "files_col_added"))}</span></div>'
        f'<div class="file-scroll"><ul class="file-uploads" id="file-uploads" hidden></ul>'
        f'<ul class="file-list">{body}</ul></div></div></div>'
        f'<template id="file-icons"><span data-icon="folder">{icon("folder")}</span><span data-icon="back">{icon("arrow_left")}</span>'
        f'<span data-icon="chevron">{icon("chevron_right")}</span>'
        + "".join(f'<span data-icon="{c}">{icon(TAB_ICON[c])}</span>' for c, _ in FILE_TABS) + '</template>'
        f'<input type="file" id="file-picker" multiple hidden>{_upload_template(lang)}'
        f'<p class="file-status" id="file-status" role="status" aria-live="polite"></p></section>'
    )


def _net_switch(lang: str, current: str) -> str:
    """"Web and code together" as a small round glass button with a globe, as high as the capsule next to it, so title,
    switch and capsule fit in one row (Janis, 14.11.2026). Pressed, it is red like the armed trash circle of the files:
    code then has the open internet (the bolder choice); not pressed, web search and code without internet. Its name
    is the label for screen readers, the tip says both states."""
    label, tip = esc(i18n.t(lang, "net_together")), esc(i18n.t(lang, "net_together_tip"))
    pressed = "true" if current == "together" else "false"
    return (
        f'<button type="button" class="m-pill m-globe" id="manager-net" data-setting="net" data-on="together" data-off="apart" '
        f'aria-pressed="{pressed}" aria-label="{label}" data-tip="{label}. {tip}">{icon("globe")}</button>'
    )


# The trash of the files and the chat archive (Janis, 14.11.2026): the two round buttons next to the gear, the same as
# trash and archive of the board, but for the Manager view (static/mvault.js). Opened, the list takes the place of the
# tiles. Neither is ever given to the manager: the trash is out of every file list, the archive out of the chat context.
MVAULT = """<section class="vault glass m-vault" id="mvault" hidden>
    <div class="vault-view" data-mview="trash" hidden>
      <h2>%t.trash%%TRASH_INFO%</h2>
      <div id="mvault-trash">%TRASH_LIST%</div>
    </div>
    <div class="vault-view" data-mview="archive" hidden>
      <h2>%t.chat_archive%%ARCHIVE_INFO%</h2>
      <p class="muted" id="chat-archive-empty" hidden>%t.chat_archive_empty%</p>
      <ul class="trash-list" id="chat-archive" data-questions="%QUESTIONS%" data-question="%t.chat_archive_one%"
          data-delete="%t.chat_archive_delete%" data-you="%t.chat_you%" data-claude="%t.station_manager%"
          data-failed="%t.chat_failed%" data-fail-auth="%t.chat_fail_auth%" data-fail-timeout="%t.chat_fail_timeout%"
          data-fail-steps="%t.chat_fail_steps%" data-fail-limit="%t.chat_fail_limit%" data-fail-server="%t.chat_fail_server%" data-fail-other="%t.chat_fail_other%"></ul>
      <h2 class="versions-head">%t.versions_title%%VERSIONS_INFO%</h2>
      <div id="mvault-versions">%VERSIONS%</div>
    </div>
  </section>"""


def _versions_list(lang: str, versions: list) -> str:
    """Earlier versions of the memory files (memory.versions), newest first: name, when, who replaced it. A click opens
    the text (mvault.js fetches it); the round arrow puts it back (the current text becomes a version itself)."""
    if not versions:
        return f'<p class="muted">{esc(i18n.t(lang, "versions_empty"))}</p>'
    restore = esc(i18n.t(lang, "versions_restore"))
    form = "%d.%m.%Y %H:%M" if lang == "de" else "%Y-%m-%d %H:%M"
    rows = "".join(
        f'<li class="version-row" data-id="{v.id}"><details class="r-run"><summary>'
        f'<span class="r-title">{esc(v.name)}</span>'
        f'<button class="icon-button card-btn" type="button" data-mversion="restore" aria-label="{restore}" '
        f'title="{restore}">{icon("undo")}</button>'
        f'<small class="r-facts">{esc(time.strftime(form, time.localtime(v.created_at)))} · '
        f'{esc(i18n.t(lang, "versions_by_" + v.author))}</small></summary>'
        f'<div class="r-report version-text"></div></details></li>'
        for v in versions
    )
    return f'<ol class="r-runs">{rows}</ol>'


def _trash_list(lang: str, trashed: list) -> str:
    """The files in the trash: name, label ("Folders" for a folder) and the days left, a restore and a delete-for-good button. The buttons carry
    data-ftrash, not data-action (that one belongs to the board's trash, board.js)."""
    if not trashed:
        return f'<p class="muted">{esc(i18n.t(lang, "files_trash_empty"))}</p>'
    restore, purge = esc(i18n.t(lang, "restore")), esc(i18n.t(lang, "delete_now"))
    rows = "".join(
        f'<li class="trash-row" data-id="{item.id}"><span class="trash-title">{esc(item.name)}'
        f'<small>{esc(i18n.t(lang, dict(FILE_TABS).get(item.category, "files_folders")))} · {esc(i18n.t(lang, "files_trash_left", n=left))}</small></span>'
        f'<button class="icon-button card-btn" type="button" data-ftrash="restore" aria-label="{restore}" title="{restore}">{icon("undo")}</button>'
        f'<button class="icon-button card-btn no" type="button" data-ftrash="purge" aria-label="{purge}" title="{purge}">{icon("cross")}</button></li>'
        for item, left in trashed
    )
    return (f'<ul class="trash-list">{rows}</ul>'
            f'<button class="link inline" type="button" data-ftrash="empty">{esc(i18n.t(lang, "trash_empty"))}</button>')


MAX_REPORT_SHOWN = 8000   # characters of the last report shown on a waiting card


def _device_asks(lang: str, asks: list) -> str:
    """The manager's requests for device actions (devices.request_action): each waits for yes or no, here."""
    return "".join(
        f'<li class="dev-ask" data-request="{r.id}"><div class="dev-ask-text"><strong>'
        f'{esc(i18n.t(lang, "dev_ask_title", action=i18n.t(lang, "dev_action_" + r.action), device=r.device))}</strong>'
        + (f'<small>{esc(r.reason)}</small>' if r.reason else "") +
        f'</div><span class="dev-ask-btns"><button type="button" class="icon-button card-btn yes" data-answer="yes" '
        f'aria-label="{esc(i18n.t(lang, "yes"))}" data-tip="{esc(i18n.t(lang, "yes"))}">{icon("check")}</button>'
        f'<button type="button" class="icon-button card-btn no" data-answer="no" aria-label="{esc(i18n.t(lang, "dev_ask_no"))}" '
        f'data-tip="{esc(i18n.t(lang, "dev_ask_no"))}">{icon("cross")}</button></span></li>'
        for r in asks)


def _pill(lang: str, label_key: str, css: str, **data) -> str:
    attrs = " ".join(f'data-{k}="{esc(v)}"' for k, v in data.items())
    return f'<button class="pill-btn {css}" type="button" {attrs}>{esc(i18n.t(lang, label_key))}</button>'


# The buttons of a task that waits for the user, left the quieter one (Janis, 19.11.2026: decide right in the tile).
TASK_PILLS = {
    "awaiting_approval": (("agent_reject", "quiet", "reject"), ("agent_approve", "go", "approve")),
    "escalated": (("agent_cancel", "quiet", "cancel"), ("agent_reject", "go", "reject")),
}


def _question_row(lang: str, q) -> str:
    who = i18n.t(lang, "w_asks_chef") if q.role == "chef" else i18n.t(lang, "w_asks_role", role=i18n.t(lang, f"station_{q.role}"))
    options = "".join(f'<button class="pill-btn quiet" type="button" data-reply="{esc(o)}">{esc(o)}</button>'
                      for o in q.options)   # a suggested answer: one click sends it
    return (
        f'<li class="w-item w-ask" data-question="{q.id}"><small class="w-who">{esc(who)}</small>'
        f'<p class="w-text">{esc(q.text)}</p>'
        + (f'<div class="w-options">{options}</div>' if options else "") +
        f'<div class="w-reply"><input class="w-input" type="text" maxlength="1000" autocomplete="off" '
        f'placeholder="{esc(i18n.t(lang, "w_own_answer"))}" aria-label="{esc(i18n.t(lang, "w_own_answer"))}">'
        f'{_pill(lang, "w_send", "go", send="1")}</div></li>'
    )


def _task_row(lang: str, task, report: str) -> str:
    pills = "".join(_pill(lang, key, css, decide=decision) for key, css, decision in TASK_PILLS.get(task.status, ()))
    return (
        f'<li class="w-item w-task" data-task="{task.id}"><div class="w-head"><span class="w-title">{esc(task.title)}</span>'
        f'<span class="r-result {"go" if task.status == "awaiting_approval" else "stop"}">'
        f'{esc(i18n.t(lang, f"task_{task.status}"))}</span></div>'
        f'<details class="w-report"><summary>{esc(i18n.t(lang, "w_report"))}</summary>'
        f'<div class="r-report">{esc(report[:MAX_REPORT_SHOWN].strip() or i18n.t(lang, "role_no_report"))}</div></details>'
        f'<div class="w-reply"><input class="w-input" type="text" maxlength="1000" autocomplete="off" '
        f'placeholder="{esc(i18n.t(lang, "w_note"))}" aria-label="{esc(i18n.t(lang, "w_note"))}">'
        f'<span class="w-btns">{pills}</span></div></li>'
    )


def _waiting_tile(lang: str, autonomy: str, waiting: list[tuple[agents.Task, str]], asks: list | None = None,
                  open_questions: list | None = None) -> str:
    """ "Waiting for you" (Janis, 16.11.2026: decisions, not work; 19.11.2026: you decide and answer right here): the
    questions of the manager and the roles (a button per suggested answer and a free field, questions.py), the tasks
    that wait for approval or need the user (the last report folded, a field for a remark to the programmer, the
    decision as pills) and the manager's requests for device actions. static/waiting.js sends and swaps the tile."""
    asks, open_questions = asks or [], open_questions or []
    items = "".join(_question_row(lang, q) for q in open_questions) + "".join(_task_row(lang, t, r) for t, r in waiting)
    devices_html = _device_asks(lang, asks)
    body = ((f'<ul class="dev-asks">{devices_html}</ul>' if devices_html else "")
            + (f'<div class="r-scroll"><ol class="w-items">{items}</ol></div>' if items else "")) \
        or f'<p class="muted">{esc(i18n.t(lang, "manager_waiting_empty"))}</p>'
    return (f'<section class="mtile glass m-waiting" id="waiting" data-err-net="{esc(i18n.t(lang, "err_network"))}"><header><h2>{esc(i18n.t(lang, "manager_waiting"))}</h2>'
            f'{autonomy}<span class="count">{len(waiting) + len(asks) + len(open_questions)}</span></header>{body}'
            f'<p class="error" role="alert" id="waiting-error" hidden></p></section>')


def render(lang: str, settings: dict, regular_checks: list | None = None, now: int | None = None,
           stored_files: list | None = None, files_confirm: bool = True, trashed_files: list | None = None,
           ais: tuple[str, ...] = ("claude",), waiting: list | None = None, versions: list | None = None,
           assessment: statusmod.Assessment | None = None, device_list: list | None = None,
           note: statusnote.Note | None = None, asks: list | None = None, open_questions: list | None = None) -> str:
    """`settings` is agents.settings(user_id): the manager is the role "chef". `regular_checks` are the
    project's checks (checks.list_checks). `ais`: the providers the user has connected (their models are offered).
    `waiting`: (task, last report) of agents.waiting_tasks, the decisions of "waiting for you"."""
    chef = settings["roles"]["chef"]
    model = ui.model_picker(lang, "manager", chef["model"], chef.get("effort", ""),
                            label_model="chat_model", label_effort="chat_effort", providers=ais)
    autonomy = _select(lang, "autonomy", "autonomy", AUTONOMY, settings["autonomy"])
    return fill(
        MANAGER,
        lang,
        STATUS=_status_tile(lang, assessment, int(now if now is not None else time.time()), note),
        DEVICES=devicepage.tile(lang, device_list or []),
        CHECKS=_checks_tile(lang, regular_checks or [], int(now if now is not None else time.time())),
        FILES=_files_tile(lang, stored_files or [], files_confirm),
        # "Claude answers": the name of the AI in use comes from its provider (catalog.py), never from the code; chat.js
        # puts in the AI of the chosen model (data-ai of the option), so "{name}" stays in the text here
        CHAT=fill(CHAT, lang, MODEL=model, SEND=icon("arrow_up"),
                  WAITING=esc(i18n.t(lang, "chat_waiting", name="{name}")), FALLBACK=esc(i18n.t(lang, "chat_fallback", name="{name}", other="{other}")), AI=esc(catalog.provider(catalog.provider_of(chef["model"])).name), NET=_net_switch(lang, settings["roles"]["chef"]["net"]),
                  INFO=ui.info_dot(i18n.t(lang, "manager_chat"), i18n.t(lang, "manager_chat_hint"))),
        WAITING_TILE=_waiting_tile(lang, autonomy, waiting or [], asks, open_questions),
        MVAULT=fill(MVAULT, lang, TRASH_LIST=_trash_list(lang, trashed_files or []),
                    TRASH_INFO=ui.info_dot(i18n.t(lang, "trash"), i18n.t(lang, "files_trash_hint", n=filestore.TRASH_DAYS)),
                    ARCHIVE_INFO=ui.info_dot(i18n.t(lang, "chat_archive"), i18n.t(lang, "chat_archive_hint")),
                    QUESTIONS=esc(i18n.t(lang, "chat_archive_many", n="{n}")),
                    VERSIONS=_versions_list(lang, versions or []),
                    VERSIONS_INFO=ui.info_dot(i18n.t(lang, "versions_title"), i18n.t(lang, "versions_hint"))),
    )
