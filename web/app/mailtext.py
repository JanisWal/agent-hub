"""The mails with a button and a link (password reset, invitation): text, HTML and sending.

The HTML uses tables and inline styles only, because mail programs ignore most CSS. Colours
follow DESIGN.md; the two palettes are the light and the dark style of the site. The mail
shows one fixed palette (`theme`), it cannot ask the mail program which one the reader likes.
Texts live in i18n.py (`mail_<kind>_subject|body|button|note`), so they exist in both languages.
"""
from . import i18n, mail
from .layout import esc, fill
from .users import User

KINDS = ("reset", "invite")

# Values from the colour table in DESIGN.md. `card` is the glass area as a solid colour, because
# mail programs know no blur.
PALETTES = {
    "light": {
        "BG": "#EFDCC6", "CARD": "#F7E6D3", "BORDER": "#E2C7A8", "TEXT": "#3A2A20",
        "MUTED": "#6F5848", "ACCENT": "#E8845A", "ON_ACCENT": "#2B1D14",
    },
    "dark": {
        "BG": "#1F1713", "CARD": "#33241C", "BORDER": "#4A3428", "TEXT": "#F6E6D8",
        "MUTED": "#BDA591", "ACCENT": "#F29A72", "ON_ACCENT": "#2B1D14",
    },
}

FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# Rounded card, headline, text, bulletproof button (solid colour first, the gloss is an extra for
# programs that understand gradients), the link as text for programs that block buttons, a note.
HTML = """<!doctype html>
<html lang="%LANG%">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="%SCHEME%">
<meta name="supported-color-schemes" content="%SCHEME%">
<title>%TITLE%</title>
</head>
<body style="margin:0;padding:0;background-color:%BG%;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:%BG%;">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;">
    <tr><td style="padding:0 8px 16px;font-family:%FONT%;font-size:18px;font-weight:650;letter-spacing:-0.01em;color:%TEXT%;">Agent-Hub</td></tr>
    <tr><td style="background-color:%CARD%;border:1px solid %BORDER%;border-radius:28px;padding:40px 32px;font-family:%FONT%;color:%TEXT%;">
      <h1 style="margin:0 0 16px;font-size:30px;line-height:1.15;font-weight:700;letter-spacing:-0.03em;color:%TEXT%;">%GREETING%</h1>
      <p style="margin:0 0 32px;font-size:17px;line-height:1.55;color:%TEXT%;">%BODY%</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td align="center" bgcolor="%ACCENT%" style="border-radius:16px;background-color:%ACCENT%;background-image:linear-gradient(180deg,rgba(255,255,255,0.38),rgba(255,255,255,0) 55%);">
          <a href="%LINK%" style="display:block;padding:17px 24px;font-family:%FONT%;font-size:17px;font-weight:650;color:%ON_ACCENT%;text-decoration:none;border-radius:16px;">%BUTTON%</a>
        </td>
      </tr></table>
      <p style="margin:28px 0 4px;font-size:13px;line-height:1.4;color:%MUTED%;">%LINK_HELP%</p>
      <p style="margin:0;font-size:13px;line-height:1.4;word-break:break-all;"><a href="%LINK%" style="color:%MUTED%;">%LINK_TEXT%</a></p>
      <p style="margin:28px 0 0;font-size:13px;line-height:1.55;color:%MUTED%;">%NOTE%</p>
    </td></tr>
    <tr><td style="padding:16px 8px 0;font-family:%FONT%;font-size:12px;line-height:1.4;color:%MUTED%;">%FOOTER%</td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


def _duration(lang: str, seconds: int) -> str:
    """"one hour" or "7 days": the only lengths we use are one hour and whole days."""
    if seconds >= 24 * 3600:
        return i18n.t(lang, "duration_days", n=seconds // (24 * 3600))
    return i18n.t(lang, "duration_hour")


def build(kind: str, user: User, link: str, seconds: int, theme: str = "light") -> tuple[str, str, str]:
    """Subject, plain text and HTML of a mail. `seconds` is how long the link works."""
    if kind not in KINDS:
        raise ValueError(f"unknown mail kind {kind}")
    lang = user.language
    greeting = i18n.t(lang, "mail_greeting", name=user.name)
    body = i18n.t(lang, f"mail_{kind}_body")
    button = i18n.t(lang, f"mail_{kind}_button")
    note = i18n.t(lang, f"mail_{kind}_note", duration=_duration(lang, seconds))
    subject = i18n.t(lang, f"mail_{kind}_subject")
    text = f"{greeting}\n\n{body}\n\n{button}:\n{link}\n\n{note}\n"
    html = fill(
        HTML, lang,
        LANG=lang, SCHEME=theme if theme in PALETTES else "light", FONT=esc(FONT), TITLE=esc(subject),
        GREETING=esc(greeting), BODY=esc(body), BUTTON=esc(button), NOTE=esc(note),
        LINK=esc(link), LINK_TEXT=esc(link), LINK_HELP=esc(i18n.t(lang, "mail_link_help")),
        FOOTER=esc(i18n.t(lang, "mail_footer")),
        **PALETTES.get(theme, PALETTES["light"]),
    )
    return subject, text, html


def send_link_mail(kind: str, user: User, token: str, seconds: int, theme: str = "light") -> bool:
    """Mail the link `<HUB_BASE_URL>/reset/<token>` to the user, in his language. False if it
    could not be sent (no HUB_BASE_URL, no key, or Resend said no)."""
    base = mail.base_url()
    if not base:
        mail.log.warning("mail not sent: HUB_BASE_URL is not set")
        return False
    subject, text, html = build(kind, user, f"{base}/reset/{token}", seconds, theme)
    return mail.send_mail(user.email, subject, text, html)
