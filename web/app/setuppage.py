"""HTML of the set-up assistant (27.11.2026, setup.py). One glass card like the login page, a row of dots for the
steps, one step per page; static/setup.js sends the forms with fetch and waits while the hub restarts."""
from html import escape as esc

from . import backuppage, i18n, setup
from .icons import icon
from .layout import fill, page
from .ui import info_dot, logged_in_page
from .users import User

CARD = """<section class="glass setup" data-setup data-step="%STEP%" data-failed="%t.setup_failed%">
  <ol class="setup-dots" aria-label="%t.setup_steps%">%DOTS%</ol>
  <h1>%TITLE%</h1>
  <p class="subtitle">%TEXT%%INFO%</p>
  %CONTENT%
</section>"""


def _dots(step: str) -> str:
    shown = ("check", "account", *setup.OWNER_STEPS)
    at = shown.index("check" if step == "restore" else step)
    return "".join(f'<li class="{"done" if i < at else "now" if i == at else ""}"></li>' for i in range(len(shown)))


def _card(lang: str, step: str, title_key: str, text: str, content: str, info: str = "") -> str:
    dot = info_dot(i18n.t(lang, title_key), info) if info else ""
    return fill(CARD, lang, STEP=step, DOTS=_dots(step), TITLE=esc(i18n.t(lang, title_key)), TEXT=esc(text),
                INFO=dot, CONTENT=content)


def _go(lang: str, back: str, next_url: str, next_key: str = "setup_next", skip: bool = False) -> str:
    """The two buttons under a step: back (or skip) and on."""
    left = (f'<button type="button" data-go="{esc(back)}">{esc(i18n.t(lang, "setup_skip" if skip else "back"))}</button>'
            if back else "")
    return (f'<div class="actions">{left}<button class="primary" type="button" data-go="{esc(next_url)}">'
            f'{esc(i18n.t(lang, next_key))}</button></div>')


def _next(step: str) -> str:
    steps = setup.OWNER_STEPS
    return "/setup?step=" + steps[min(steps.index(step) + 1, len(steps) - 1)]


# --- before there is an owner --------------------------------------------------------------------------------------
def check_page(lang: str, runner_seen: float) -> str:
    t = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    rows = []
    for row in setup.checks(runner_seen):
        if row["key"] == "memory":
            value = f'{row["value"]} MB'
        elif row["key"] == "disk":
            value = f'{row["value"]:.1f} GB'.replace(".", "," if lang == "de" else ".")
        elif row["key"] == "storage":
            value = t("setup_storage_card" if row["value"] == "card" else "setup_storage_disk")
        else:
            value = t("setup_runner_ok" if row["state"] == "ok" else "setup_runner_bad")
        if row["state"] == "bad" and row["key"] in ("memory", "disk"):
            value += " · " + t("setup_too_small")
        rows.append(f'<li class="setup-check" data-state="{row["state"]}"><span class="setup-lamp" aria-hidden="true">'
                    f'</span><span class="setup-name">{esc(t("setup_check_" + row["key"]))}</span>'
                    f'<span class="setup-value">{esc(value)}</span></li>')
    content = (f'<ul class="setup-checks">{"".join(rows)}</ul>'
               f'<p class="muted setup-window">{esc(t("setup_window", minutes=setup.minutes_left()))}</p>'
               + _guide(lang, "setup_check_g", 5) +
               f'<div class="actions"><button type="button" data-go="/setup?step=restore">{esc(t("setup_restore"))}</button>'
               f'<button class="primary" type="button" data-go="/setup?step=account">{esc(t("setup_new"))}</button></div>')
    body = _card(lang, "check", "setup_welcome", t("setup_welcome_text"), content)
    return page(t("setup_title"), body, lang, styles=("setup.css",), scripts=("setup.js",))


ACCOUNT = """<form method="post" action="/setup/owner" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
  %ERROR%
  <label>%t.email%<input type="email" name="email" required autofocus autocomplete="username" value="%EMAIL%" placeholder="%t.email_placeholder%"></label>
  <label>%t.password%<input type="password" name="password" required autocomplete="new-password" placeholder="••••••••"></label>
  <label>%t.setup_password_again%<input type="password" name="password2" required autocomplete="new-password" placeholder="••••••••"></label>
  <label class="setting has-select setup-lang"><span class="setting-label">%t.language%</span>
    <select name="language"><option value="de"%DE%>Deutsch</option><option value="en"%EN%>English</option></select>%CHEVRON%</label>
  %GUIDE%
  <div class="actions">
    <button type="button" data-go="/setup">%t.back%</button>
    <button class="primary" type="submit">%t.setup_create%</button>
  </div>
</form>"""


def account_page(lang: str, error_key: str = "", email: str = "") -> str:
    error = f'<p class="error" role="alert">{esc(i18n.t(lang, error_key))}</p>' if error_key else ""
    content = fill(ACCOUNT, lang, ERROR=error, EMAIL=esc(email), CHEVRON=icon("chevron_down"),
                   GUIDE=_guide(lang, "setup_account_g", 3),
                   DE=" selected" if lang == "de" else "", EN=" selected" if lang == "en" else "")
    body = _card(lang, "account", "setup_account", i18n.t(lang, "setup_account_text"), content)
    return page(i18n.t(lang, "setup_title"), body, lang, styles=("setup.css",), scripts=("setup.js",))


def restore_page(lang: str) -> str:
    content = (_guide(lang, "setup_restore_g", 4) + backuppage.restore_part(lang, owner=False)
               + f'<div class="actions"><button type="button" data-go="/setup">{esc(i18n.t(lang, "back"))}</button></div>')
    body = _card(lang, "restore", "rs_title", "", content)
    return page(i18n.t(lang, "setup_title"), body, lang, styles=("setup.css", "backup.css"),
                scripts=("motion.js", "backup.js", "setup.js"))


def closed_page(lang: str) -> str:
    body = (f'<section class="glass setup"><h1>{esc(i18n.t(lang, "setup_closed_title"))}</h1>'
            f'<p class="subtitle">{esc(i18n.t(lang, "setup_closed_text"))}</p></section>')
    return page(i18n.t(lang, "setup_title"), body, lang, styles=("setup.css",))


# --- the owner's steps ---------------------------------------------------------------------------------------------
SETTINGS = """<form class="setup-form" novalidate data-setup-form="%KIND%" data-url="/setup/settings"
      data-probe="/setup/probe/%KIND%" data-restarting="%t.setup_restarting%" data-probing="%PROBING%"
      data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%" data-configured="%CONFIGURED%">
  %FIELDS%
  <p class="error" role="alert" data-error hidden></p>
  <p class="muted setup-probe" role="status" data-probe-note hidden></p>
  <div class="actions">
    <button type="button" data-go="%SKIP%">%t.setup_skip%</button>
    %EXTRA%
    <button class="primary" type="submit">%t.setup_save%</button>
  </div>
  <div class="actions" data-after hidden>
    %AGAIN%
    <button class="primary" type="button" data-go="%NEXT%">%t.setup_next%</button>
  </div>
</form>"""


def _field(label: str, name: str, value: str = "", kind: str = "text", placeholder: str = "", hint: str = "",
           extra: str = "") -> str:
    hint_html = f'<span class="setup-hint" data-hint>{esc(hint)}</span>' if hint else ""
    return (f'<label>{esc(label)}<input type="{kind}" name="{name}" value="{esc(value)}" placeholder="{esc(placeholder)}"'
            f' autocomplete="off" spellcheck="false" maxlength="500"{extra}>{hint_html}</label>')


def _guide(lang: str, prefix: str, steps: int, summary: str = "setup_guide") -> str:
    """A step-by-step guide that folds open (Janis, 27.11.2026: the formats and the way there right in the step;
    28.11.2026: every step has one, together they cover everything from the first page to running the hub)."""
    items = "".join(f"<li>{esc(i18n.t(lang, f'{prefix}_{n}'))}</li>" for n in range(1, steps + 1))
    return (f'<details class="setup-guide"><summary>{esc(i18n.t(lang, summary))}</summary>'
            f'<ol>{items}</ol></details>')


WAYS = ("home", "tunnel", "own")


def current_way() -> str:
    """Which way the hub is reachable now: a tunnel, an own https address, or the home network only."""
    now = setup.current()
    if now["tunnel"]:
        return "tunnel"
    return "own" if now["base_url"].startswith("https://") else "home"


def access_content(lang: str, here: str = "") -> str:
    """Three ways (Janis, 27.11.2026): home network only (skip-able, the server's address), the Cloudflare tunnel as the
    recommended way, or an own public address (a server with a public IP and an own certificate)."""
    t = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    now, way = setup.current(), current_way()
    rows = []
    for name in WAYS:
        badge = f'<span class="setup-badge">{esc(t("setup_way_best"))}</span>' if name == "tunnel" else ""
        rows.append(f'<label class="setup-way"><input type="radio" name="way" value="{name}"'
                    f'{" checked" if name == way else ""} data-hint-text="{esc(t(f"setup_{name}_hint"))}"'
                    f' data-placeholder="{"https://hub.deine-domain.de" if lang == "de" and name != "home" else "https://hub.your-domain.com" if name != "home" else esc(here or "http://192.168.1.20:8080")}">'
                    f'<span class="setup-way-title">{esc(t(f"setup_way_{name}"))}{badge}</span>'
                    f'<span class="setup-way-text">{esc(t(f"setup_way_{name}_text"))}</span></label>')
    address = now["base_url"] or (here if way == "home" else "")
    token_hint = t("setup_token_kept") if now["tunnel"] else t("setup_token_hint")
    fields = (f'<div class="setup-ways" role="radiogroup">{"".join(rows)}</div>'
              f'<div data-way="home" hidden>{_guide(lang, "setup_home_g", 2)}</div>'
              f'<div data-way="tunnel" hidden>{_guide(lang, "setup_tunnel", 7)}</div>'
              f'<div data-way="own" hidden>{_guide(lang, "setup_own", 4)}</div>'
              + _field(t("setup_address"), "base_url", address, "url", "", t(f"setup_{way}_hint"), ' data-address')
              + f'<div data-way="tunnel" hidden>'
              + _field(t("setup_token"), "tunnel_token", "", "password", "eyJ…", token_hint) + '</div>'
              + f'<input type="hidden" name="here" value="{esc(here)}">')
    again = f'<button type="button" data-probe-again>{esc(t("setup_probe_again"))}</button>'
    return fill(SETTINGS, lang, KIND="access", FIELDS=fields, SKIP=_next("access"), NEXT=_next("access"),
                PROBING=esc(t("setup_probe_wait")), CONFIGURED="1" if now["base_url"] else "", EXTRA="", AGAIN=again)


def mail_content(lang: str) -> str:
    t = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    now = setup.current()
    fields = (_guide(lang, "setup_mail", 7)
              + _field(t("setup_mail_key"), "resend_key", "", "password", "re_…",
                       t("setup_token_kept") if now["mail_key"] else t("setup_mail_key_hint"))
              + _field(t("setup_mail_from"), "mail_from", now["mail_from"], "text", t("setup_mail_from_hint"),
                       t("setup_mail_from_format")))
    if not now["base_url"]:
        fields = f'<p class="muted">{esc(t("setup_mail_no_address"))}</p>' + fields
    test = f'<button type="button" data-probe-again>{esc(t("setup_mail_test"))}</button>'
    return fill(SETTINGS, lang, KIND="mail", FIELDS=fields, SKIP=_next("mail"), NEXT=_next("mail"),
                PROBING=esc(t("setup_mail_test")), CONFIGURED="1" if now["mail_key"] and now["mail_from"] else "",
                EXTRA="", AGAIN=test)


def owner_page(user: User, step: str, here: str = "") -> str:
    lang = user.language
    t = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    if step == "access":
        body = _card(lang, step, "setup_access", t("setup_access_text"), access_content(lang, here))
    elif step == "mail":
        body = _card(lang, step, "setup_mail", t("setup_mail_text"), mail_content(lang))
    elif step == "backup":
        content = (_guide(lang, "setup_backup_g", 4) + backuppage.key_part(lang, setup=True)
                   + f'<div class="bk-line">{backuppage.hour_field(lang)}{backuppage.now_part(lang)}</div>'
                   + _go(lang, _next("backup"), _next("backup"), skip=True))
        body = _card(lang, step, "setup_backup", t("setup_backup_text"), content)
    elif step == "ai":
        content = (_guide(lang, "setup_ai_g", 5) +
                   f'<button class="primary setup-ai" type="button" data-open-drawer>{esc(t("setup_ai_open"))}</button>'
                   f'<div class="actions"><button type="button" data-go="{_next("ai")}">{esc(t("setup_next"))}</button></div>')
        body = _card(lang, step, "setup_ai", t("setup_ai_text"), content)
    else:
        content = (_guide(lang, "setup_done_g", 5, "setup_guide_next") +
                   f'<div class="actions"><button class="primary" type="button" data-setup-finish data-url="/setup/finish">'
                   f'{esc(t("setup_finish"))}</button></div>')
        body = _card(lang, "done", "setup_done", t("setup_done_text"), content)
    # A way out (Janis, 27.11.2026): opened again from the administration it leads back there; during the first set-up
    # it finishes the assistant for now (everything can be set later).
    back = (f'<a class="link setup-back" href="/admin">{esc(t("setup_back"))}</a>' if setup.is_done() else
            f'<button class="link setup-back" type="button" data-setup-finish data-url="/setup/finish">{esc(t("setup_later"))}</button>')
    body = body.replace('<ol class="setup-dots"', back + '<ol class="setup-dots"', 1)
    return logged_in_page(user, t("setup_title"), body, styles=("setup.css", "backup.css"),
                          scripts=("motion.js", "backup.js", "setup.js"))
