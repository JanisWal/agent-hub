"""The mails with a button and a link (password reset, invitation): text, HTML and sending.

The HTML uses tables and inline styles only, because mail programs ignore most CSS. It is built for the weakest of
them (Janis, 15.11.2026: Outlook for Windows draws with Word, Yahoo drops much): colours also as `bgcolor`
attributes, the width as an attribute, standard font weights, and a button whose coloured cell carries the padding
(`mso-padding-alt`), so it is a real button there too. Outlook takes only the first font of a list and falls back
to Times when it lacks it, so a block only Outlook reads sets Arial; it also gets 96 dpi, or it scales the mail. Round corners and the gloss are extras that may be missing. Colours
follow DESIGN.md; the two palettes are the light and the dark style of the site. The mail
shows one fixed palette: the style the user saw last on the site (`users.theme`, reported by
the theme switch). A mail program cannot be asked which one the reader likes.
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
<html lang="%LANG%" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="x-apple-disable-message-reformatting">
<!--[if mso]>
<xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml>
<style>body,table,td,p,a,h1{font-family:Arial,Helvetica,sans-serif !important;}</style>
<![endif]-->
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="%SCHEME%">
<meta name="supported-color-schemes" content="%SCHEME%">
<title>%TITLE%</title>
</head>
<body bgcolor="%BG%" style="margin:0;padding:0;width:100%;background-color:%BG%;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="%BG%" style="width:100%;background-color:%BG%;border-collapse:collapse;">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="520" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:520px;">
    <tr><td style="padding:0 8px 16px;font-family:%FONT%;font-size:18px;font-weight:700;letter-spacing:-0.01em;color:%TEXT%;">Agent-Hub</td></tr>
    <tr><td bgcolor="%CARD%" style="background-color:%CARD%;border:1px solid %BORDER%;border-radius:28px;padding:40px 32px;font-family:%FONT%;color:%TEXT%;">
      <h1 style="margin:0 0 16px;font-family:%FONT%;font-size:30px;line-height:1.15;mso-line-height-rule:exactly;font-weight:700;letter-spacing:-0.03em;color:%TEXT%;">%GREETING%</h1>
      <p style="margin:0 0 32px;font-family:%FONT%;font-size:17px;line-height:1.55;color:%TEXT%;">%BODY%</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td align="center" bgcolor="%ACCENT%" style="border-radius:16px;background-color:%ACCENT%;background-image:linear-gradient(180deg,rgba(255,255,255,0.38),rgba(255,255,255,0) 55%);mso-padding-alt:17px 24px;">
          <a href="%LINK%" style="display:block;padding:17px 24px;font-family:%FONT%;font-size:17px;line-height:1.3;font-weight:700;color:%ON_ACCENT%;text-decoration:none;border-radius:16px;">%BUTTON%</a>
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


def build(kind: str, user: User, link: str, seconds: int, theme: str | None = None) -> tuple[str, str, str]:
    """Subject, plain text and HTML of a mail. `seconds` is how long the link works.

    `theme` ("light" or "dark") defaults to the style the user saw last (`user.theme`).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown mail kind {kind}")
    lang = user.language
    theme = theme or user.theme
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


def send_link_mail(kind: str, user: User, token: str, seconds: int, theme: str | None = None) -> bool:
    """Mail the link `<HUB_BASE_URL>/reset/<token>` to the user, in his language. False if it
    could not be sent (no HUB_BASE_URL, no key, or Resend said no)."""
    base = mail.base_url()
    if not base:
        mail.log.warning("mail not sent: HUB_BASE_URL is not set")
        return False
    subject, text, html = build(kind, user, f"{base}/reset/{token}", seconds, theme)
    return mail.send_mail(user.email, subject, text, html)
