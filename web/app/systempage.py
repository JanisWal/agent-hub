"""HTML of the owner's system page."""
from . import i18n
from .layout import fill
from .users import User

SYSTEM = """<section class="sys-wrap" data-network="%t.err_network%">
  <header class="sys-head"><h2>%t.system_title%</h2></header>
  <div class="sys-list glass">
    <div class="sys-row">
      <div class="sys-main"><span class="sys-name">%t.sys_reboot%</span><span class="sys-hint">%t.sys_reboot_hint%</span></div>
      <button type="button" data-power="reboot">%t.sys_reboot%</button>
    </div>
    <div class="sys-row">
      <div class="sys-main"><span class="sys-name">%t.sys_poweroff%</span><span class="sys-hint">%t.sys_poweroff_hint%</span></div>
      <button type="button" data-power="poweroff">%t.sys_poweroff%</button>
    </div>
  </div>
  <p class="sys-note" role="status" hidden
     data-done-reboot="%t.sys_reboot_done%" data-done-poweroff="%t.sys_poweroff_done%"></p>
</section>
<dialog class="dialog" id="power-reboot-dialog">
  <form novalidate data-url="/system/power" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.sys_reboot_title%</h2>
    <p class="muted">%t.sys_reboot_hint%</p>
    <input type="hidden" name="action" value="reboot">
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="primary" type="submit">%t.sys_reboot_do%</button>
    </div>
  </form>
</dialog>
<dialog class="dialog danger" id="power-poweroff-dialog">
  <form novalidate data-url="/system/power" data-msg-required="%t.msg_required%" data-msg-email="%t.msg_email%">
    <h2>%t.sys_poweroff_title%</h2>
    <p class="muted">%t.sys_poweroff_hint%</p>
    <input type="hidden" name="action" value="poweroff">
    <label>%t.your_password%<input type="password" name="confirm" required autocomplete="current-password"></label>
    <p class="error" role="alert" data-error hidden></p>
    <div class="actions">
      <button type="button" data-close autofocus>%t.cancel%</button>
      <button class="danger-btn" type="submit">%t.sys_poweroff_do%</button>
    </div>
  </form>
</dialog>"""


def render(user: User) -> str:
    """The system block with its dialogs (a part of /admin, only for the owner; adminpage.py checks that)."""
    return fill(SYSTEM, user.language)
