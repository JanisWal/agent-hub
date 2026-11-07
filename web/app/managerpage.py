"""HTML of the Manager view: the second view of the project page (station "Manager").

Janis, 07.11.2026: a click on "Manager" hides the board; the stations on the left stay and the
main window shows the manager's things. This first step has the working settings (name and
description) and shows where the status, the actions waiting for the user, the chat, the files,
the devices and the regular checks will live. Nothing here talks to an agent yet.
"""
from . import i18n
from .layout import esc, fill
from .projects import MAX_DESCRIPTION, MAX_NAME, Project

# (key of the title, key of the one-line hint) of the tiles that are not built yet.
SOON = (
    ("manager_chat", "manager_chat_hint"),
    ("manager_files", "manager_files_hint"),
    ("manager_devices", "manager_devices_hint"),
    ("manager_checks", "manager_checks_hint"),
)

MANAGER = """<section class="manager" id="manager-view" aria-label="%t.station_manager%" hidden>
  <section class="mtile glass m-status">
    <header><h2>%t.manager_status%</h2><span class="m-lamp" title="%t.manager_status_none%"></span></header>
    <p class="muted">%t.manager_status_empty%</p>
  </section>
  <section class="mtile glass m-waiting">
    <header><h2>%t.manager_waiting%</h2><span class="count">0</span></header>
    <p class="muted">%t.manager_waiting_empty%</p>
  </section>
  %SOON%
  <section class="mtile glass m-settings">
    <header><h2>%t.manager_settings%</h2></header>
    <form method="post" action="/projects/%PID%/settings" novalidate
          data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
      <label>%t.project_name%<input name="name" required maxlength="%MAX_NAME%" autocomplete="off" value="%NAME%"></label>
      <label>%t.project_description%<textarea name="description" maxlength="%MAX_DESCRIPTION%" rows="4"
        placeholder="%t.project_description_placeholder%">%DESCRIPTION%</textarea></label>
      <div class="actions"><button class="primary" type="submit">%t.save%</button></div>
    </form>
  </section>
</section>"""


def _soon(lang: str) -> str:
    """A tile that is announced but not built: title, one line, and the "later" tag."""
    later = esc(i18n.t(lang, "coming_soon"))
    return "".join(
        f'<section class="mtile glass m-soon"><header><h2>{esc(i18n.t(lang, title))}</h2>'
        f'<span class="m-tag">{later}</span></header>'
        f'<p class="muted">{esc(i18n.t(lang, hint))}</p></section>'
        for title, hint in SOON
    )


def render(project: Project, lang: str) -> str:
    return fill(
        MANAGER,
        lang,
        PID=str(project.id),
        NAME=esc(project.name),
        DESCRIPTION=esc(project.description),
        MAX_NAME=str(MAX_NAME),
        MAX_DESCRIPTION=str(MAX_DESCRIPTION),
        SOON=_soon(lang),
    )
