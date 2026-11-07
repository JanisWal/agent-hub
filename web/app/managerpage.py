"""HTML of the Manager view: the second view of the project page (station "Manager").

Janis, 07.11.2026: a click on "Manager" hides the board; the stations on the left stay and the main
window shows the manager's things. Layout from his sketch, three columns. Left: the status and the
devices (tall). Middle: the regular checks and the files (they take the free space). Right, where the
old chat window used to sit: the manager chat (big) above "waiting for you". The project name and
description are not here but in the drop-down at the pencil next to the title (projectpage.title_html).
Nothing here talks to an agent yet: only the status and "waiting for you" are empty, the rest is announced.
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
        CHAT=_soon(lang, "manager_chat", "manager_chat_hint", "m-chat"),
    )
