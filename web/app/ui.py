"""Parts shared by several pages: the login page, the logged-in frame with its settings drawer, the model picker."""
import json

from . import catalog, i18n
from .icons import icon
from .layout import esc, fill, page
from .users import User

from . import ai_link, aichoice, claude_link, db, usage


def info_dot(label: str, text: str) -> str:
    """The "i" of DESIGN.md (section 4, Janis 14.11.2026): explains a control in our own tip on hover, focus, click or
    tap, instead of a line of text that takes room. `label` and `text` are plain text (escaped here)."""
    return (f'<button type="button" class="info-dot" data-tip="{esc(text)}" aria-label="{esc(label)}: {esc(text)}">'
            f'{icon("info")}</button>')


def ai_name(lang: str, provider: str) -> str:
    """The name of an AI as the page shows it: from the catalog, the user's own AI in the user's language."""
    if provider == "custom":
        return i18n.t(lang, "ai_custom_name")
    return catalog.provider(provider).name if provider in catalog.PROVIDERS else provider


def tools_line(lang: str, provider: str) -> str:
    """Where the tools of an AI come from (catalog.tools_of), in one short line: own, from the hub, missing."""
    from . import toolcheck   # what the AI's answers show, not only what the catalog says
    tools = toolcheck.effective(provider)
    def names(source: str) -> list[str]:
        return [i18n.t(lang, f"tool_{t}") for t in catalog.TOOLS if tools.get(t) == source]
    own, hub, missing = names("own"), names("hub"), names("none")
    parts = [i18n.t(lang, "tools_own")] if own else []
    if hub:
        parts.append(i18n.t(lang, "tools_all_hub") if not own else i18n.t(lang, "tools_from_hub", names=", ".join(hub)))
    if missing:
        parts.append(i18n.t(lang, "tools_without", names=", ".join(missing)))
    return i18n.t(lang, "tools_line", list=", ".join(parts))


def model_picker(lang: str, prefix: str, model: str, effort: str, *, label_model: str = "picker_model",
                 label_effort: str = "picker_effort", css: str = "m-select", setting: bool = True,
                 providers: tuple[str, ...] = (catalog.DEFAULT_PROVIDER,), allowed: dict | None = None,
                 names: dict | None = None) -> str:
    """Two drop-downs in our own style, AI model and effort level, built from the list in catalog.py (Janis,
    14.11.2026). Used wherever a model is chosen: manager chat, regular checks, the roles. The level list holds every
    level of the provider; levels the chosen model does not have are hidden, and static/picker.js keeps that right
    when the model changes (`data-levels`, `data-defaults`). `setting` adds data-setting for pages that save a change
    at once (manager.js). Unknown hints show nothing, unknown levels show their name as it is.
    `providers`: whose models the list holds, in this order (the user's connected AIs, Claude first); the provider of
    the chosen model is always there. Each option carries its provider's name (data-ai) for "… is answering"."""
    model, effort = catalog.resolve(model, effort)
    own = catalog.provider_of(model)
    shown = [catalog.provider(p) for p in dict.fromkeys((*providers, own)) if p in catalog.PROVIDERS]
    allowed = allowed or {}
    # only what each user's account offers (models.py; None = not known yet: all), the chosen one always
    all_models = [(prov, m) for prov in shown for m in prov.models
                  if allowed.get(prov.id) is None or m.id in allowed[prov.id] or m.id == model]
    chosen = next(m for _, m in all_models if m.id == model)
    levels: list[str] = []
    for _, m in all_models:
        levels += [e for e in m.efforts if e not in levels]

    texts = i18n.STRINGS.get(lang, i18n.STRINGS["de"])

    def label(key: str) -> str:
        return esc(i18n.t(lang, key))

    def model_name(prov: catalog.Provider, m: catalog.Model) -> str:
        if prov.id == "custom":   # the name the user gave his further AI
            return (names or {}).get(m.id) or ai_name(lang, "custom")
        return m.name

    def model_text(prov: catalog.Provider, m: catalog.Model) -> str:
        hint = texts.get(f"model_hint_{m.hint}", "") if m.hint else ""
        return esc(f"{model_name(prov, m)} · {hint}" if hint else model_name(prov, m))

    def effort_text(level: str) -> str:
        return esc(texts.get(f"effort_{level}", level))

    # The closed box shows only the name (option label, saves room in a tile header); the list shows name and hint.
    models = "".join(f'<option value="{m.id}" label="{esc(model_name(prov, m))}" data-ai="{esc(ai_name(lang, prov.id))}"'
                     f'{" selected" if m.id == model else ""}>{model_text(prov, m)}</option>' for prov, m in all_models)
    efforts = "".join(
        f'<option value="{e}"{" selected" if e == effort else ""}{"" if e in chosen.efforts else " hidden"}>'
        f'{effort_text(e)}</option>' for e in levels)
    data_levels = esc(json.dumps({m.id: list(m.efforts) for _, m in all_models}, separators=(",", ":")))
    data_defaults = esc(json.dumps({m.id: m.default_effort for _, m in all_models}, separators=(",", ":")))

    def attr(name: str) -> str:
        return f' data-setting="{name}"' if setting else ""
    chevron = icon("chevron_down")
    return (   # no title on the selects: its tip would cover the list
        f'<span class="model-picker" data-provider="{own}">'
        f'<label class="{css} has-select"><select name="model" id="{prefix}-model"{attr("model")} '
        f'aria-label="{label(label_model)}">{models}</select>{chevron}</label>'
        f'<label class="{css} has-select"><select name="effort" id="{prefix}-effort"{attr("effort")} '
        f'aria-label="{label(label_effort)}" data-levels="{data_levels}" data-defaults="{data_defaults}">{efforts}'
        f'</select>{chevron}</label></span>'
    )

# Claude has its own row with a real state, the AIs the runner keeps (ai_link.PROVIDERS: Mistral, ChatGPT, the own AI)
# have a row each in the folded list.
KEY_PAGES = {"mistral": "https://console.mistral.ai/api-keys"}   # where the user makes a key (fixed, never from a request)
# Row of an AI with a key: style class of the dot, status text, link text.
KEY_STATES = {
    "connected": ("ok", "connected", "claude_disconnect"),
    "connecting": ("pending", "key_checking", "connect"),
    "expired": ("expired", "key_refused", "claude_renew"),
    "noplan": ("expired", "plan_missing", "claude_renew"),
}

# The further AIs (ai_link.SLOTS, 21.11.2026): one dialog for all of them, the same steps as KEY_DIALOG (ailink.js), with
# a name, address and model; the key may stay empty (a local model). The open tile sends "custom" and the server takes
# the next free place; a row of a connected one sends its place ("custom-3"). Plain fields, no browser checks
# (DESIGN.md 9): the server says what does not fit (data-field-error).
CUSTOM_DIALOG = """<dialog class="dialog" id="key-dialog-custom" data-provider="custom">
  <h2>%t.custom_title%</h2>
  <form data-step="key" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <p class="muted">%t.custom_steps%</p>
    <p class="error" role="alert" data-field-error hidden data-endpoint="%t.custom_bad_endpoint%" data-network="%t.custom_network%" data-model="%t.custom_bad_model%" data-full="%t.custom_full%" data-key="%t.custom_bad_key%"></p>
    <label>%t.custom_label%<input type="text" name="label" maxlength="40" autocomplete="off" spellcheck="false" placeholder="%t.custom_label_hint%"></label>
    <label>%t.custom_endpoint%<input type="text" name="endpoint" required maxlength="300" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://…/v1"></label>
    <label>%t.custom_model%<input type="text" name="model" required maxlength="100" autocomplete="off" spellcheck="false"></label>
    <label>%t.custom_key%<input type="password" name="key" maxlength="400" autocomplete="off" spellcheck="false"></label>
    <p class="muted"><a class="link" data-key-page target="_blank" rel="noopener noreferrer" hidden>%t.custom_get_key%</a></p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.claude_confirm%</button>
    </div>
  </form>
  <div data-step="check" hidden><p class="muted" role="status">%t.key_wait%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p></div>
  <div data-step="done" hidden>
    <p class="muted">%t.custom_done%</p>
    <div class="actions"><button class="primary" type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="failed" hidden>
    <p class="error" role="alert">%t.custom_failed%</p>
    <div class="actions"><button type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="disconnect" hidden>
    <p class="muted">%t.key_disconnect_text%</p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="button" data-disconnect>%t.claude_disconnect%</button>
    </div>
  </div>
</dialog>"""

# ChatGPT (ai_link.DEVICE_LOGIN, 21.11.2026): no key; the server starts a sign-in at OpenAI and shows its link and
# one-time code (ailink.js fills them in from the status). The password is typed at OpenAI only.
DEVICE_DIALOG = """<dialog class="dialog wide" id="key-dialog-%ID%" data-provider="%ID%">
  <h2>%t.device_title%</h2>
  <div class="link-split">
  <section class="link-plan">
  <h3 class="link-head">%t.api_plan_title%</h3>
  <div data-step="plan-on" hidden>
    <p class="api-state">%t.plan_on%</p>
    <div class="actions"><button type="button" data-close>%t.close%</button></div>
    <button class="link" type="button" data-plan-off>%t.plan_off%</button>
  </div>
  <form data-step="key" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <p class="muted">%t.device_steps%</p>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.device_start%</button>
    </div>
  </form>
  <div data-step="check" hidden><p class="muted" role="status">%t.device_wait_link%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p></div>
  <div data-step="device" hidden>
    <p class="muted">%t.device_open%</p>
    <a class="primary" data-device-link href="#" target="_blank" rel="noopener noreferrer">%t.device_link%</a>
    <div class="copy-box copy-click device-copy"><code class="device-code" data-device-code data-copy-text aria-live="polite"></code>%COPY%</div>
    <p class="muted" role="status">%t.device_wait%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p>
  </div>
  <div data-step="done" hidden>
    <p class="muted">%t.device_done%</p>
    <div class="actions"><button class="primary" type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="failed" hidden>
    <p class="error" role="alert">%t.device_failed%</p>
    <div class="actions"><button type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="disconnect" hidden>
    <p class="muted">%DISCONNECT%</p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="button" data-disconnect>%t.claude_disconnect%</button>
    </div>
  </div>
  </section>
  %API%
  </div>
</dialog>"""

LOGIN = """<section class="glass">
  <h1>%t.login%</h1>
  <p class="subtitle">%t.login_welcome%</p>
  %ERROR%
  <form method="post" action="/login" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <label>%t.email%<input type="email" name="email" required autofocus autocomplete="username" placeholder="%t.email_placeholder%"></label>
    <label>%t.password%<input type="password" name="password" required autocomplete="current-password" placeholder="••••••••"></label>
    <button class="primary" type="submit">%t.login%</button>
  </form>
  <a class="link" href="/forgot">%t.forgot_password%</a>
</section>"""


def login_page(failed: bool = False, locked_minutes: int = 0, lang: str = "de") -> str:
    """The login page. The user is not known yet: `lang` is the browser's language (i18n.from_header)."""
    text = i18n.t(lang, "login_locked", minutes=locked_minutes) if locked_minutes else i18n.t(lang, "login_failed")
    error = f'<p class="error" role="alert">{esc(text)}</p>' if failed or locked_minutes else ""
    return page(i18n.t(lang, "login"), fill(LOGIN, lang, ERROR=error), lang)


# Closed: only the gear and the arrow show at the top right. Open: the box slides out of
# the corner and the handle rides along on its left edge (see app.css).
SETTINGS = """<div class="drawer" id="settings">
  %DRAWER_EXTRAS%
  <button class="drawer-handle" id="settings-toggle" type="button"
          aria-expanded="false" aria-controls="settings-panel" aria-label="%t.settings_toggle%">%GEAR%%ARROW%</button>
  <div class="drawer-box glass" id="settings-panel">
   <div class="drawer-scroll">
    <div class="drawer-main">
      %SERVICES%
      <a class="admin-btn" href="/account">%t.account_title%</a>
      %ADMIN%
    </div>
    <form method="post" action="/logout"><button class="link" type="submit">%t.logout%</button></form>
   </div>
  </div>
</div>
%CLAUDE_DIALOG%
%KEY_DIALOGS%
<template id="copy-tpl">%COPY%</template>"""

# The dialog of an AI that connects with an API key (ai_link.py, static/ailink.js): paste the key, the runner checks
# it with the provider. All texts come from here; %NAME% is the AI's name, %PAGE% where the user makes a key.
KEY_DIALOG = """<dialog class="dialog" id="key-dialog-%ID%" data-provider="%ID%">
  <h2>%TITLE%</h2>
  <form data-step="key" novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <p class="muted">%STEPS%</p>
    <a class="primary" href="%PAGE%" target="_blank" rel="noopener noreferrer">%OPEN%</a>
    <label>%t.key_label%<input type="password" name="key" required maxlength="200" autocomplete="off" spellcheck="false"></label>
    <div class="actions">
      <button type="button" data-close>%t.cancel%</button>
      <button class="primary" type="submit">%t.claude_confirm%</button>
    </div>
  </form>
  <div data-step="check" hidden><p class="muted" role="status">%t.key_wait%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p></div>
  <div data-step="done" hidden>
    <p class="muted">%DONE%</p>
    <div class="actions"><button class="primary" type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="failed" hidden>
    <p class="error" role="alert">%t.key_failed%</p>
    <div class="actions"><button type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="disconnect" hidden>
    <p class="muted">%t.key_disconnect_text%</p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="button" data-disconnect>%t.claude_disconnect%</button>
    </div>
  </div>
</dialog>"""

# The dialog of the Claude connection. claude.js shows one step at a time; all texts are here,
# translated by the server, none in the script.
CLAUDE_DIALOG = """<dialog class="dialog wide" id="claude-dialog">
  <h2>%t.claude_title%</h2>
  <div class="link-split">
  <section class="link-plan">
  <h3 class="link-head">%t.api_plan_title%</h3>
  <div data-step="plan-on" hidden>
    <p class="api-state">%t.plan_on%</p>
    <div class="actions"><button type="button" data-close>%t.close%</button></div>
    <button class="link" type="button" data-plan-off>%t.plan_off%</button>
  </div>
  <div data-step="start" hidden>
    <p class="muted">%t.claude_start_text%</p>
    <button class="primary" type="button" data-start>%t.device_start%</button>
  </div>
  <div data-step="wait">
    <p class="muted" role="status">%t.claude_wait%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p>
    <div class="actions"><button type="button" data-cancel>%t.cancel%</button></div>
  </div>
  <form data-step="link" hidden novalidate data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <p class="muted">%t.claude_steps%</p>
    <a class="primary" id="claude-link" href="#" target="_blank" rel="noopener noreferrer">%t.claude_open%</a>
    <label>%t.claude_code%<input name="code" required maxlength="2000" autocomplete="off" spellcheck="false"></label>
    <div class="actions">
      <button type="button" data-cancel>%t.cancel%</button>
      <button class="primary" type="submit">%t.claude_confirm%</button>
    </div>
  </form>
  <div data-step="check" hidden><p class="muted" role="status">%t.claude_checking%<span class="loading-dots" aria-hidden="true"><i></i><i></i><i></i></span></p></div>
  <div data-step="done" hidden>
    <p class="muted">%t.claude_done%</p>
    <div class="actions"><button class="primary" type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="failed" hidden>
    <p class="error" role="alert">%t.claude_failed%</p>
    <div class="actions"><button type="button" data-finish>%t.close%</button></div>
  </div>
  <div data-step="stuck" hidden>
    <p class="error" role="alert">%t.claude_stuck%</p>
    <div class="actions"><button type="button" data-cancel>%t.close%</button></div>
  </div>
  <div data-step="disconnect" hidden>
    <p class="muted">%DISCONNECT%</p>
    <div class="actions">
      <button type="button" data-finish-keep autofocus>%t.cancel%</button>
      <button class="danger-btn" type="button" data-disconnect>%t.claude_disconnect%</button>
    </div>
  </div>
  </section>
  %API%
  </div>
</dialog>
<dialog class="dialog danger" id="chat-clear-dialog">
  <h2>%t.chat_clear_title%</h2>
  <p class="muted">%t.chat_clear_text%</p>
  <div class="actions">
    <button type="button" data-close autofocus>%t.cancel%</button>
    <button class="danger-btn" type="button" id="chat-clear-yes">%t.chat_clear_yes%</button>
  </div>
  </section>
  %API%
  </div>
</dialog>"""

# Claude row: status text, the style class that colours the dot, and the text of the link.
CLAUDE_STATES = {
    "connected": ("ok", "connected", "claude_disconnect"),
    "connecting": ("pending", "claude_pending", "claude_continue"),
    "expiring": ("pending", "claude_expiring", "claude_renew"),
    "expired": ("expired", "claude_expired", "claude_renew"),
}


def _toggle(lang: str) -> str:
    """The arrow at the top right of the first AI block (the same place as the arrow of the language block): it opens
    the list of the other AIs below (core.js). A button inside the block, so the block stays one box."""
    return (f'<button class="ai-toggle" type="button" id="ai-toggle" aria-expanded="false" aria-controls="ai-more" '
            f'aria-label="{esc(i18n.t(lang, "ai_more"))}">{icon("chevron_down")}</button>')


def _make_default(lang: str, provider: str) -> str:
    """"Use as standard" (Janis, 15.11.2026): a small round green button with a star at the top right of the row of a
    connected AI that is not the standard, above its "disconnect" (the spot of the arrow in the first row), so the
    row keeps one line (ailink.js). Name and explanation in the tip."""
    label = esc(i18n.t(lang, "ai_default_short"))
    return (f'<button class="ai-default" type="button" data-ai-default="{provider}" aria-label="{label}" '
            f'data-tip="{label}. {esc(i18n.t(lang, "ai_default_hint"))}">{icon("star")}</button>')


def _shown(state: str, api_on: bool) -> str:
    """The state a row of an AI with a plan shows: connected also when only its API key is (Janis, 21.11.2026)."""
    return "connected" if api_on and state in ("none", "") else state


def copy_button(lang: str) -> str:
    """The copy button (Janis, 21.11.2026: codes, tokens and commands copy with one click). It copies the text of the
    `[data-copy-text]` in its `.copy-box` (core.js); in a `.copy-box.copy-click` (a short code) a click on the text
    copies too. For a moment it shows "copied" in place. Scripts clone it from `#copy-tpl` (settings_bar)."""
    label, done = esc(i18n.t(lang, "copy")), esc(i18n.t(lang, "copied"))
    return (f'<button class="icon-button card-btn copy-btn" type="button" data-copy aria-label="{label}" '
            f'data-tip="{label}" data-done="{done}">{icon("copy")}{icon("check", "copy-done")}</button>')


def _status(lang: str, text_key: str, manage: str = "", plan: str = "") -> str:
    """The state of a row. "Connected" of an AI with a plan and a key is a button (Janis, 21.11.2026): it looks the
    same, glows a little more under the pointer and opens the dialog with both halves as they are (claude.js,
    ailink.js); `plan` tells the dialog whether the plan is signed in."""
    text = esc(i18n.t(lang, text_key))
    if not manage:
        return f'<span class="status">{text}</span>'
    return (f'<button class="status status-open" type="button" data-manage="{manage}" data-plan="{esc(plan)}" '
            f'aria-haspopup="dialog">{text}</button>')


def _claude_row(lang: str, state: str, first: bool = True, as_default: bool = False, api: str = "",
                api_on: bool = False) -> str:
    """The Claude block: state and the link of its dialog (claude.js), or "make standard" (`as_default`)."""
    shown = _shown(state, api_on)
    style, text_key, action_key = CLAUDE_STATES.get(shown, ("", "not_connected", "connect"))
    action = (f'<button class="link inline" type="button" id="claude-open" data-status="{esc(shown)}">'
              f'{esc(i18n.t(lang, action_key))}</button>')
    corner = _toggle(lang) if first else (_make_default(lang, "claude") if as_default and shown == "connected" else "")
    status = _status(lang, text_key, "claude" if shown == "connected" else "", state)
    return (
        f'<div class="setting service {style}" id="claude-row" data-ai="claude" '
        f'data-expired="{esc(i18n.t(lang, "claude_expired"))}" data-renew="{esc(i18n.t(lang, "claude_renew"))}">'
        f'<span class="setting-label">{esc(ai_name(lang, "claude"))}</span>{corner}'
        f'<span class="service-line">{status}{action}</span>'
        f'<span class="service-tools">{esc(tools_line(lang, "claude"))}{api}</span></div>'
    )


def _key_row(lang: str, provider: str, state: str, first: bool = False, as_default: bool = False, api: str = "",
             name: str = "", api_on: bool = False) -> str:
    """The block of an AI with an API key: state and one link that opens its dialog (ailink.js), or "make standard".
    A further AI ("custom-3") shows the name the user gave it; its tools and its standard are those of "custom"."""
    kind = "custom" if ai_link.is_custom(provider) else provider
    plan, state = state, _shown(state, api_on)
    style, text_key, action_key = KEY_STATES.get(state, ("", "not_connected", "connect"))
    label = f' data-label="{esc(name)}"' if name else ""
    action = (f'<button class="link inline" type="button" data-key-open="{provider}" data-status="{esc(state)}"{label}>'
              f'{esc(i18n.t(lang, action_key))}</button>')
    corner = _toggle(lang) if first else (_make_default(lang, kind) if as_default and state == "connected" else "")
    manage = provider if state == "connected" and provider in API_PANEL else ""
    return (
        f'<div class="setting service {style}" id="key-row-{provider}" data-ai="{kind}">'
        f'<span class="setting-label">{esc(name or ai_name(lang, provider))}</span>{corner}'
        f'<span class="service-line">{_status(lang, text_key, manage, plan)}{action}</span>'
        f'<span class="service-tools">{esc(tools_line(lang, kind))}{api}</span></div>'
    )


# AIs that get an adapter of their own later (Janis, 21.11.2026): their programs do more than the general way.
SOON = ("GitHub Copilot",)
# AIs that are a ready-made entry of the "Other AI" dialog (Janis, 23.11.2026): their name, the address of their API in
# the OpenAI format and the page where the user makes a key. No adapter of their own: they work through the hub's tool
# loop (runner/hubloop.py) in every role. Fixed here, never from a request.
PRESETS = {"Gemini": {"endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
                      "page": "https://aistudio.google.com/apikey"}}


def _preset_row(lang: str, name: str, preset: dict) -> str:
    """The tile of a ready-made AI: it opens the dialog of the open tile with name and address filled in."""
    return (f'<div class="setting service" id="key-row-preset-{esc(name.lower())}"><span class="setting-label">'
            f'{esc(name)}</span><span class="service-line"><span class="status">'
            f'{esc(i18n.t(lang, "custom_preset_line"))}</span><button class="link inline" type="button" '
            f'data-key-open="custom" data-status="none" data-label="{esc(name)}" '
            f'data-endpoint="{esc(preset["endpoint"])}" data-key-page="{esc(preset["page"])}">'
            f'{esc(i18n.t(lang, "connect"))}</button></span></div>')


def _add_row(lang: str) -> str:
    """The open tile (Janis, 21.11.2026): always there while a place is free, to connect one more AI of any kind with
    an API in the OpenAI format."""
    return (f'<div class="setting service" id="key-row-custom"><span class="setting-label">'
            f'{esc(i18n.t(lang, "custom_add"))}</span><span class="service-line"><span class="status">'
            f'{esc(i18n.t(lang, "custom_add_line"))}</span><button class="link inline" type="button" '
            f'data-key-open="custom" data-status="none">{esc(i18n.t(lang, "connect"))}</button></span></div>')


def _soon_row(lang: str, name: str) -> str:
    """A placeholder: name and "later", no button and no "i" (CLAUDE.md)."""
    return (f'<div class="setting service soon"><span class="setting-label">{esc(name)}</span>'
            f'<span class="service-line"><span class="status">{esc(i18n.t(lang, "ai_soon"))}</span></span></div>')


API_PANEL = ("claude", "chatgpt")   # the AIs whose dialog has a plan and an API key half (= credentials.API_FOR)
API_MODES = ("fallback", "always", "off")
API_SCOPES = ("all", "runs", "chat")


def _api_lines(lang: str, user_id: int) -> dict[str, str]:
    """Per AI with a plan, the short note in its drawer row when the user has an API key: how it is used."""
    from . import credentials
    lines = {}
    with db.connect() as conn:
        for provider in credentials.API_FOR:
            now = credentials.settings_in(conn, user_id, provider)
            if now["connected"]:
                lines[provider] = " · " + esc(i18n.t(lang, "api_row", mode=i18n.t(lang, f"api_mode_{now['mode']}")))
    return lines


def api_panel(lang: str, provider: str, user_id: int) -> str:
    """The right half of the dialog of Claude and ChatGPT (Janis, 21.11.2026): the user's API key next to the plan, its
    state and settings (credentials.py). Sent by aiapi.js; the key leaves the page once and is never shown again."""
    from . import credentials
    with db.connect() as conn:
        now = credentials.settings_in(conn, user_id, provider)
    def options(name: str, values: tuple, chosen: str) -> str:
        return "".join(f'<option value="{v}"{" selected" if v == chosen else ""}>{esc(i18n.t(lang, f"api_{name}_{v}"))}'
                       f'</option>' for v in values)
    state = {"connected": "api_state_on", "connecting": "api_state_checking", "expired": "api_state_refused"}.get(
        now["status"], "api_state_none")
    spent = (f' {esc(i18n.t(lang, "api_spent", n=now["spent"], limit=now["daily"]))}' if now["daily"] else "")
    remove = (f'<button class="link" type="button" data-api-remove>{esc(i18n.t(lang, "api_remove"))}</button>'
              if now["status"] in ("connected", "expired") else "")
    kept = now["status"] in ("connected", "connecting")   # saved or being checked: greyed, "remove" opens it again
    chevron = icon("chevron_down")
    return (
        f'<section class="link-api" data-api="{provider}">'
        f'<h3 class="link-head">{esc(i18n.t(lang, "api_title"))}</h3>'
        f'<p class="muted link-note">{esc(i18n.t(lang, "api_costs"))}</p>'
        f'<p class="api-state" role="status" data-api-state>{esc(i18n.t(lang, state))}{spent}</p>'
        f'<form data-api-form novalidate data-saved="{esc(i18n.t(lang, "api_saved"))}" '
        f'data-failed="{esc(i18n.t(lang, "api_failed"))}" data-none="{esc(i18n.t(lang, "api_state_none"))}" '
        f'data-new="{esc(i18n.t(lang, "api_key_new"))}">'
        f'<label class="setting{" kept" if kept else ""}"><span class="setting-label">{esc(i18n.t(lang, "api_key"))}</span>'
        f'<input type="password" name="key" maxlength="300" autocomplete="off" spellcheck="false"{" disabled" if kept else ""} '
        f'placeholder="{esc(i18n.t(lang, "api_key_kept" if kept else "api_key_new"))}"></label>'
        f'<label class="setting has-select"><span class="setting-label">{esc(i18n.t(lang, "api_mode"))}</span>'
        f'<select name="mode">{options("mode", API_MODES, now["mode"])}</select>{chevron}</label>'
        f'<label class="setting has-select"><span class="setting-label">{esc(i18n.t(lang, "api_scope"))}</span>'
        f'<select name="scope">{options("scope", API_SCOPES, now["scope"])}</select>{chevron}</label>'
        f'<label class="setting"><span class="setting-label">{esc(i18n.t(lang, "api_daily"))}</span>'
        f'<input type="text" name="daily" inputmode="numeric" maxlength="7" value="{now["daily"] or ""}" '
        f'placeholder="{esc(i18n.t(lang, "api_daily_none"))}"></label>'
        f'<div class="actions"><button type="submit">{esc(i18n.t(lang, "api_save"))}</button></div>{remove}'
        f'</form></section>'
    )


def _disconnect_text(lang: str, provider: str, user_id: int, plain: str) -> str:
    """"Disconnect" in the drawer removes the plan and the API key (Janis, 21.11.2026); the text says so when there
    is a key. One by one in the dialog behind "Connected"."""
    from . import credentials
    with db.connect() as conn:
        has_key = credentials.settings_in(conn, user_id, provider)["status"] != "none"
    return esc(i18n.t(lang, "both_disconnect_text" if has_key else plain))


def _paused(user_id: int) -> bool:
    """Are the user's agents paused (agents.set_paused)? Read here directly: ui does not import agents."""
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM agent_settings WHERE user_id = ? AND key = 'agents.paused'",
                           (user_id,)).fetchone()
    return bool(row and row["value"] not in ("", "0"))


def _custom_rows(user_id: int) -> list[dict]:
    with db.connect() as conn:
        return ai_link.custom_rows(conn, user_id)


def _key_dialogs(lang: str, user_id: int) -> str:
    def dialog(provider: str) -> str:
        if provider == "custom":   # address, model and an optional key instead of a page to make a key on
            return fill(CUSTOM_DIALOG, lang)
        if provider in ai_link.DEVICE_LOGIN:   # sign-in at OpenAI with a one-time code, and the API key beside it
            return fill(DEVICE_DIALOG, lang, ID=provider, NAME=esc(ai_name(lang, provider)),
                        DISCONNECT=_disconnect_text(lang, provider, user_id, "key_disconnect_text"),
                        COPY=copy_button(lang),
                        API=api_panel(lang, provider, user_id))
        name = ai_name(lang, provider)                        # the AI's name comes from the catalog, never from here
        return fill(KEY_DIALOG, lang, ID=provider, PAGE=esc(KEY_PAGES[provider]),
                    **{part.upper(): esc(i18n.t(lang, f"key_{part}", name=name)) for part in ("title", "steps", "open", "done")})
    return "\n".join(dialog(p) for p in (*ai_link.PROVIDERS, "custom"))


def _service_rows(lang: str, claude_state: str, key_states: dict[str, str] | None = None,
                  connected: tuple[str, ...] = (), api: dict | None = None,
                  custom: list[dict] | None = None, paused: bool = False, used: dict | None = None) -> str:
    """The AIs and the chat history button (Janis, 15.11.2026). On top the standard AI with the arrow; below, folded
    (Janis, 11.11.2026: the list grows with every AI), the others. The order arranges itself (Janis, 21.11.2026):
    `connected` comes ranked (aichoice.ranked: the standard, the one before it, the other connected ones), then the AIs
    that are not connected in a fixed order (Claude, Mistral, ChatGPT, the further AIs: ai_link.custom_rows), the open
    tile and the placeholders (SOON); nothing unconnected stands between connected ones.
    With two or more connected, each connected one that is not the standard has the green star
    "use as standard" at its top right; every connected AI keeps "disconnect". The button is type="button": no submit.
    `used` (usage.by_ai): under its tools each AI says what it used today and in the last 7 days (22.11.2026)."""
    key_states = dict(key_states or {})
    several = len(connected) >= 2
    custom = custom or []
    labels = {}
    for item in custom:
        key_states[item["name"]], labels[item["name"]] = item["state"], item["label"]

    def kind(name: str) -> str:
        return "custom" if ai_link.is_custom(name) else name

    names = ["claude", *ai_link.PROVIDERS, *labels]
    linked = []                                          # the rows of the connected AIs, in their rank
    for provider in connected:
        if provider == "custom":
            linked += [i["name"] for i in custom if i["state"] == "connected"]
        elif provider in names:
            linked.append(provider)
    linked = list(dict.fromkeys(linked))
    names = linked + [n for n in names if n not in linked]
    top = names[0] if linked else "claude"

    def row(name: str, first: bool) -> str:
        as_default = several and kind(name) != kind(top)
        line = (api or {}).get(name, "")
        spent = (used or {}).get(name)
        shown = line + (f'<span class="service-usage">{esc(i18n.t(lang, "ai_usage_line", today=i18n.count(lang, spent["today"]), week=i18n.count(lang, spent["week"])))}</span>'
                        if spent and spent["week"] else "")
        if name == "claude":
            return _claude_row(lang, claude_state, first, as_default, shown, bool(line))
        return _key_row(lang, name, key_states.get(name, "none"), first, as_default, shown, labels.get(name, ""),
                        bool(line))

    rest = [row(n, False) for n in names if n != top]
    if len(custom) < len(ai_link.SLOTS):
        rest.append(_add_row(lang))
        taken = {i["label"].strip().lower() for i in custom}      # one that is connected has its own row
        rest += [_preset_row(lang, n, p) for n, p in PRESETS.items() if n.lower() not in taken]
    rest += [_soon_row(lang, n) for n in SOON]
    others = "\n        ".join(rest)
    clear = (f'<button class="clear-btn" type="button" id="chat-clear-open">'
             f'{esc(i18n.t(lang, "chat_clear"))}</button>')
    # The emergency switch (Janis, 22.11.2026), like "delete chat history" above it: red while the agents may work,
    # green "go on" while they are paused (static/aipause.js swaps text and colour without a reload).
    pause = (f'<button class="clear-btn pause-btn{" paused" if paused else ""}" type="button" id="ai-pause" '
             f'aria-pressed="{"true" if paused else "false"}" data-pause="{esc(i18n.t(lang, "ai_pause"))}" '
             f'data-resume="{esc(i18n.t(lang, "ai_resume"))}" data-tip="{esc(i18n.t(lang, "ai_pause_tip"))}">'
             f'{esc(i18n.t(lang, "ai_resume" if paused else "ai_pause"))}</button>')
    more = f'<div class="ai-more" id="ai-more" hidden>\n        {others}\n      </div>'
    services = f'<div class="ai-services" id="ai-services">{row(top, True)}\n      {more}</div>'   # swapped as one
    return "\n      ".join([services, pause, clear])


def _admin_button(user: User) -> str:
    """The way to the administration page: only for owner and admins, a quiet button under "Account"."""
    if not user.is_admin:
        return ""
    return f'<a class="admin-btn" href="/admin">{esc(i18n.t(user.language, "admin_title"))}</a>'


def settings_bar(user: User, extras: str = "") -> str:
    """Settings drawer for the top right corner of every logged-in page. `extras` (HTML) are small
    buttons to the left of the gear that ride along when the drawer slides out (project page)."""
    lang = user.language
    return fill(
        SETTINGS,
        lang,
        DRAWER_EXTRAS=extras,
        GEAR=icon("gear"),
        ARROW=icon("arrow_left", "drawer-arrow"),
        SERVICES=_service_rows(lang, claude_link.status(user.id), {p: ai_link.status(user.id, p) for p in ai_link.PROVIDERS},
                               tuple(aichoice.ranked(user.id)), _api_lines(lang, user.id),
                               _custom_rows(user.id), _paused(user.id), usage.by_ai(user.id)),
        ADMIN=_admin_button(user),
        CLAUDE_DIALOG=fill(CLAUDE_DIALOG, lang, API=api_panel(lang, "claude", user.id),
                           DISCONNECT=_disconnect_text(lang, "claude", user.id, "claude_disconnect_text")),
        KEY_DIALOGS=_key_dialogs(lang, user.id),
        COPY=copy_button(lang),
    )


def logged_in_page(
    user: User,
    title: str,
    body: str,
    *,
    scripts: tuple[str, ...] = (),
    styles: tuple[str, ...] = (),
    body_class: str = "",
    top_center: str = "",
    top_left: str = "",
    drawer_extras: str = "",
) -> str:
    """A page with the settings drawer in the corner, in the language of the user."""
    return page(
        title, body, user.language,
        top_right=settings_bar(user, drawer_extras), top_center=top_center, top_left=top_left,
        scripts=("claude.js", "ailink.js", "aiapi.js", "aipause.js", *scripts), styles=styles, body_class=body_class,
    )
