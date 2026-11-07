"""HTML of the Manager view: the second view of the project page (station "Manager").

Janis, 07.11.2026: a click on "Manager" hides the board; the stations on the left stay and the main
window shows the manager's things. Layout from his sketch, three columns. Left: the status and the
devices (tall). Middle: the regular checks and the files (they take the free space). Right, where the
old chat window used to sit: the manager chat (big) above "waiting for you". The project name and
description are not here but in the drop-down at the pencil next to the title (projectpage.title_html).
The manager chat works (chat.py); status and "waiting for you" are empty, devices, checks and files announced.
"""
from . import i18n
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
      <header><h2>%t.manager_waiting%</h2><span class="count">0</span></header>
      <p class="muted">%t.manager_waiting_empty%</p>
    </section>
  </div>
</section>"""


# The manager chat (web/app/chat.py, static/chat.js): it replaced the slim single-question window at the right
# edge. The model is picked per question in the drop-down next to the Web and Code switches.
CHAT = """<section class="mtile glass m-chat" id="chat" data-you="%t.chat_you%" data-claude="%t.station_manager%"
             data-waiting="%t.chat_waiting%" data-failed="%t.chat_failed%">
      <header><h2>%t.manager_chat%</h2></header>
      <p class="muted">%t.manager_chat_hint%</p>
      <ol class="chat-log" id="chat-log" aria-live="polite"></ol>
      <p class="error" id="chat-error" role="alert" hidden></p>
      <div class="chat-modes" id="chat-modes" role="group" aria-label="%t.manager_chat%">
        <button class="chat-mode" type="button" data-mode="web" aria-pressed="true" title="%t.chat_mode_web_title%">%t.chat_mode_web%</button>
        <button class="chat-mode" type="button" data-mode="code" aria-pressed="false" title="%t.chat_mode_code_title%">%t.chat_mode_code%</button>
        <label class="chat-model">
          <select id="chat-model" name="model" aria-label="%t.chat_model%" title="%t.chat_model%">
            <option value="haiku">%t.model_haiku%</option>
            <option value="sonnet" selected>%t.model_sonnet%</option>
            <option value="opus">%t.model_opus%</option>
          </select></label>
      </div>
      <form class="chat-form" id="chat-form" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
        <label><input name="prompt" required maxlength="2000" autocomplete="off" placeholder="%t.chat_placeholder%"></label>
        <button type="submit" id="chat-send">%t.chat_send%</button>
      </form>
    </section>"""


def _soon(lang: str, title: str, hint: str, css: str = "") -> str:
    """A tile that is announced but not built: title, one line, and the "later" tag."""
    later = esc(i18n.t(lang, "coming_soon"))
    return (
        f'<section class="mtile glass m-soon {css}"><header><h2>{esc(i18n.t(lang, title))}</h2>'
        f'<span class="m-tag">{later}</span></header>'
        f'<p class="muted">{esc(i18n.t(lang, hint))}</p></section>'
    )


def render(lang: str) -> str:
    return fill(
        MANAGER,
        lang,
        DEVICES=_soon(lang, "manager_devices", "manager_devices_hint", "m-grow"),
        CHECKS=_soon(lang, "manager_checks", "manager_checks_hint"),
        FILES=_soon(lang, "manager_files", "manager_files_hint", "m-grow"),
        CHAT=fill(CHAT, lang),
    )
