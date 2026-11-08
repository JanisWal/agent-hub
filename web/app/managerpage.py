"""HTML of the Manager view: the second view of the project page (station "Manager").

Janis, 07.11.2026: a click on "Manager" hides the board; the stations on the left stay and the main
window shows the manager's things. Layout from his sketch, three columns. Left: the status and the
devices (tall). Middle: the regular checks and the files (they take the free space). Right, where the
old chat window used to sit: the manager chat (big) above "waiting for you". The project name and
description are not here but in the drop-down at the pencil next to the title (projectpage.title_html).
The manager chat works (chat.py); status and "waiting for you" are empty, devices, checks and files announced.
"""
from . import i18n
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
    %FILES%
  </div>
  <div class="mcol">
    %CHAT%
    <section class="mtile glass m-waiting">
      <header><h2>%t.manager_waiting%</h2>%AUTONOMY%<span class="count">0</span></header>
      <p class="muted">%t.manager_waiting_empty%</p>
    </section>
  </div>
</section>"""


# The manager chat (web/app/chat.py, static/chat.js): it replaced the slim single-question window at the right
# edge. Web search and code are always there (no switches, Janis 07.11.2026); the model drop-down is a setting of
# the manager, so it holds for everything the manager does (static/manager.js saves it).
CHAT = """<section class="mtile glass m-chat" id="chat" data-you="%t.chat_you%" data-claude="%t.station_manager%"
             data-waiting="%t.chat_waiting%" data-failed="%t.chat_failed%">
      <header><h2>%t.manager_chat%</h2>%MODEL%</header>
      <div class="m-chat-sub"><p class="muted">%t.manager_chat_hint%</p>%NET%</div>
      <ol class="chat-log" id="chat-log" aria-live="polite"></ol>
      <p class="error" id="chat-error" role="alert" hidden></p>
      <form class="chat-form" id="chat-form" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
        <label><input name="prompt" required maxlength="2000" autocomplete="off" placeholder="%t.chat_placeholder%"></label>
        <button type="submit" id="chat-send">%t.chat_send%</button>
      </form>
    </section>"""

MODELS = (("haiku", "model_haiku"), ("sonnet", "model_sonnet"), ("opus", "model_opus"))
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


def _net_switch(lang: str, current: str) -> str:
    """The switch "web and code together" (on: code has the open internet; off: web search, code offline)."""
    label = esc(i18n.t(lang, "net_together"))
    checked = " checked" if current == "together" else ""
    return (
        f'<label class="m-switch"><input type="checkbox" role="switch" id="manager-net" data-setting="net" '
        f'data-on="together" data-off="apart"{checked}><span class="m-switch-track" aria-hidden="true"></span>'
        f'<span class="m-switch-label">{label}</span></label>'
    )


def render(lang: str, settings: dict) -> str:
    """`settings` is agents.settings(user_id): the manager is the role "chef"."""
    model = _select(lang, "model", "chat_model", MODELS, settings["roles"]["chef"]["model"])
    autonomy = _select(lang, "autonomy", "autonomy", AUTONOMY, settings["autonomy"])
    return fill(
        MANAGER,
        lang,
        DEVICES=_soon(lang, "manager_devices", "manager_devices_hint", "m-grow"),
        CHECKS=_soon(lang, "manager_checks", "manager_checks_hint"),
        FILES=_soon(lang, "manager_files", "manager_files_hint", "m-grow"),
        CHAT=fill(CHAT, lang, MODEL=model, NET=_net_switch(lang, settings["roles"]["chef"]["net"])),
        AUTONOMY=autonomy,
    )
