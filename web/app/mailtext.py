"""The mails with a button and a link (password reset, invitation): text, HTML and sending.

Rebuilt from scratch on 15.11.2026 (Janis) after testing Yahoo, Gmail and Apple Mail, on the support tables of
caniemail.com. The rules, each one learned the hard way or taken from those tables:

1. No pictures at all, also no background pictures. Yahoo's dark mode leaves every cell that holds a picture or a
   background picture as it is while it darkens the rest (light patches in a dark card); many programs block
   pictures anyway, and mail proxies keep old pictures under their address. So the mail is text and colour only.
2. Everything the mail needs is inline: tables, `bgcolor` and inline styles. A `<style>` block only adds the extras,
   so it may be missing (Gmail with non-Google accounts, GMX and WEB.DE in the browser read none).
3. Light is the base. Programs that know `prefers-color-scheme` (Apple Mail, Outlook for Mac, iOS, Android and
   Outlook.com, Samsung Email, the GMX and WEB.DE apps) get our own dark style, and `color-scheme: light dark` tells
   them that we bring one, so they do not recolour by themselves. Light and dark follow the reader's mail program.
4. Programs that recolour by themselves (Gmail apps, Yahoo, Outlook for Windows) cannot be stopped, so the light
   colours must survive any recolouring: no pure white or black; the button has light text on a darker orange,
   because recolouring lightens dark text but may keep the orange (dark text on light orange became pale on
   orange in Yahoo); borders are faint `rgba` lines, because Yahoo keeps border colours while it darkens the card.
5. Glass and glow are extras by CSS only: round corners (almost everywhere), the light edge and the soft shadows
   (`box-shadow`: Apple Mail, Outlook apps and Outlook.com, Samsung), the gloss of the button and the coloured fields
   behind the card (gradients: Apple Mail, Gmail, Samsung). Gradients sit behind the selector `[class~="..."]`,
   which Gmail and Apple Mail understand and Yahoo does not, so Yahoo never sees a background picture.
6. Outlook for Windows (Word) gets Arial, 96 dpi, a hex border and a button whose cell carries the padding
   (`mso-padding-alt`); its corners stay square.
7. Small things that break mails elsewhere: `!important` always with a space and in lower case, `rgba` only with
   commas, no CSS comments inside `<style>` (a rule after a comment is lost in some programs), each kind of extra in
   its own `<style>` block (a program that rejects one block keeps the others), the button text in a `span` inside
   the link (some programs recolour links), a hidden preview text, and the whole mail far below Gmail's 102 KB.

Texts live in i18n.py (`mail_<kind>_subject|body|button|note`), so they exist in both languages.
"""
from . import i18n, mail
from .layout import esc, fill
from .users import User

KINDS = ("reset", "invite")

# The base, written inline. Values from DESIGN.md, except the button (rule 4).
LIGHT = {
    "page": "#EFDCC6", "card": "#F7E6D3", "line": "#E2C7A8", "text": "#3A2A20", "muted": "#6F5848",
    "accent": "#B05530", "on_accent": "#FFF6EE",
}
# Where a program follows our light style (rule 3) the button looks like on the site.
SITE_BUTTON = {"accent": "#E8845A", "on_accent": "#2B1D14"}
# Our dark style, only through `prefers-color-scheme` and Outlook.com's dark mode attributes.
DARK = {
    "page": "#1F1713", "card": "#33241C", "line": "#4A3428", "text": "#F6E6D8", "muted": "#BDA591",
    "accent": "#F29A72", "on_accent": "#2B1D14",
}

FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# Coloured fields behind the card (like the orbs of the site) and the gloss of the button.
_FIELDS_LIGHT = ("radial-gradient(circle at 15% 0%,rgba(240,168,120,0.55),rgba(240,168,120,0) 42%),"
                 "radial-gradient(circle at 88% 6%,rgba(230,191,140,0.6),rgba(230,191,140,0) 38%),"
                 "radial-gradient(circle at 55% 30%,rgba(232,132,90,0.25),rgba(232,132,90,0) 45%)")
_FIELDS_DARK = ("radial-gradient(circle at 15% 0%,rgba(138,79,46,0.6),rgba(138,79,46,0) 42%),"
                "radial-gradient(circle at 88% 6%,rgba(107,58,34,0.65),rgba(107,58,34,0) 38%),"
                "radial-gradient(circle at 55% 30%,rgba(200,104,63,0.3),rgba(200,104,63,0) 45%)")
_GLOSS = "linear-gradient(180deg,rgba(255,255,255,0.32),rgba(255,255,255,0) 62%)"

# Extras every capable program may use (rule 5), and the narrow screen. None of the three blocks is read by Outlook
# for Windows (rule 6).
STYLE_GLASS = (
    ":root{color-scheme:light dark;supported-color-schemes:light dark;}"
    ".card{border:1px solid rgba(58,42,32,0.12);box-shadow:inset 0 1px 0 rgba(255,255,255,0.7),0 18px 40px rgba(90,50,20,0.12);}"
    ".btn{box-shadow:0 8px 22px rgba(176,85,48,0.32),inset 0 1px 0 rgba(255,255,255,0.3);}"
    "@media screen and (max-width:480px){.card{padding:28px 22px 26px !important;}.h1{font-size:26px !important;}}"
)
# Gradients and Apple's data detectors behind attribute selectors: Yahoo does not match them (rule 5).
STYLE_GRADIENTS = (
    f'[class~="fields"]{{background-image:{_FIELDS_LIGHT};background-repeat:no-repeat;}}'
    f'[class~="btn"]{{background-image:{_GLOSS};}}'
    "a[x-apple-data-detectors]{color:inherit !important;text-decoration:none !important;}"
)


def _palette_rules(colours: dict[str, str]) -> str:
    """Our colours as rules over the inline ones (for the dark style and Outlook.com)."""
    return (
        f".page{{background-color:{colours['page']} !important;}}"
        f".card{{background-color:{colours['card']} !important;}}"
        f".t{{color:{colours['text']} !important;}}"
        f".m{{color:{colours['muted']} !important;}}"
        f".btn{{background-color:{colours['accent']} !important;}}"
        f".bt{{color:{colours['on_accent']} !important;}}"
    )


# Light and dark for programs that follow the reader's setting (rule 3); Outlook.com marks what it recoloured with
# `data-ogsc` (text) and `data-ogsb` (backgrounds), there our dark colours win.
STYLE_SCHEMES = (
    "@media (prefers-color-scheme:light){"
    f".btn{{background-color:{SITE_BUTTON['accent']} !important;box-shadow:0 8px 22px rgba(232,132,90,0.35),inset 0 1px 0 rgba(255,255,255,0.35) !important;}}"
    f".bt{{color:{SITE_BUTTON['on_accent']} !important;}}"
    "}"
    "@media (prefers-color-scheme:dark){"
    + _palette_rules(DARK)
    + ".card{border-color:rgba(255,220,190,0.14) !important;box-shadow:inset 0 1px 0 rgba(255,220,190,0.18),0 18px 40px rgba(0,0,0,0.35) !important;}"
    ".btn{box-shadow:0 8px 22px rgba(242,154,114,0.3),inset 0 1px 0 rgba(255,255,255,0.3) !important;}"
    f'[class~="fields"]{{background-image:{_FIELDS_DARK} !important;}}'
    "}"
    f"[data-ogsb] .page{{background-color:{DARK['page']} !important;}}"
    f"[data-ogsb] .card{{background-color:{DARK['card']} !important;}}"
    f"[data-ogsb] .btn{{background-color:{DARK['accent']} !important;}}"
    f"[data-ogsc] .t{{color:{DARK['text']} !important;}}"
    f"[data-ogsc] .m{{color:{DARK['muted']} !important;}}"
    f"[data-ogsc] .bt{{color:{DARK['on_accent']} !important;}}"
)

# Only Outlook for Windows reads this (rule 6).
STYLE_OUTLOOK = (
    "body,table,td,p,a,h1,span{font-family:Arial,Helvetica,sans-serif !important;}"
    f".card{{border:1px solid {LIGHT['line']} !important;}}"
)

HTML = """<!doctype html>
<html lang="%LANG%" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no, url=no">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>%TITLE%</title>
<!--[if mso]>
<xml><o:OfficeDocumentSettings><o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml>
<style>%STYLE_OUTLOOK%</style>
<![endif]-->
<!--[if !mso]><!-->
<style>%STYLE_GLASS%</style>
<style>%STYLE_GRADIENTS%</style>
<style>%STYLE_SCHEMES%</style>
<!--<![endif]-->
</head>
<body class="page" bgcolor="%PAGE%" style="margin:0;padding:0;width:100%;background-color:%PAGE%;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">%PREVIEW%&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table class="page" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="%PAGE%" style="width:100%;background-color:%PAGE%;">
<tr><td class="page fields" align="center" bgcolor="%PAGE%" style="padding:32px 16px 40px;background-color:%PAGE%;">
<!--[if mso]><table role="presentation" width="520" align="center" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:520px;margin:0 auto;">
  <tr><td class="t" style="padding:0 8px 16px;font-family:%FONT%;font-size:18px;line-height:24px;font-weight:700;color:%TEXT%;">Agent-Hub</td></tr>
  <tr><td class="card" bgcolor="%CARD%" style="background-color:%CARD%;border-radius:28px;padding:36px 32px 32px;font-family:%FONT%;color:%TEXT%;">
    <h1 class="t h1" style="margin:0 0 16px;font-family:%FONT%;font-size:30px;line-height:36px;mso-line-height-rule:exactly;font-weight:700;color:%TEXT%;">%GREETING%</h1>
    <p class="t" style="margin:0 0 28px;font-family:%FONT%;font-size:17px;line-height:26px;color:%TEXT%;">%BODY%</p>
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto;">
      <tr><td class="btn" align="center" bgcolor="%ACCENT%" style="background-color:%ACCENT%;border-radius:16px;mso-padding-alt:16px 30px;">
        <a class="bt" href="%LINK%" target="_blank" style="display:inline-block;padding:16px 30px;border-radius:16px;font-family:%FONT%;font-size:17px;line-height:22px;font-weight:700;color:%ON_ACCENT%;text-decoration:none;"><span class="bt" style="color:%ON_ACCENT%;">%BUTTON%</span></a>
      </td></tr>
    </table>
    <p class="m" style="margin:28px 0 4px;font-family:%FONT%;font-size:13px;line-height:19px;color:%MUTED%;">%LINK_HELP%</p>
    <p class="m" style="margin:0;font-family:%FONT%;font-size:13px;line-height:19px;word-break:break-all;color:%MUTED%;"><a class="m" href="%LINK%" target="_blank" style="color:%MUTED%;text-decoration:underline;"><span class="m" style="color:%MUTED%;">%LINK_TEXT%</span></a></p>
    <p class="m" style="margin:24px 0 0;font-family:%FONT%;font-size:13px;line-height:20px;color:%MUTED%;">%NOTE%</p>
  </td></tr>
  <tr><td class="m" style="padding:16px 8px 0;font-family:%FONT%;font-size:12px;line-height:18px;color:%MUTED%;">%FOOTER%</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>"""


def _duration(lang: str, seconds: int) -> str:
    """"one hour" or "7 days": the only lengths we use are one hour and whole days."""
    if seconds >= 24 * 3600:
        return i18n.t(lang, "duration_days", n=seconds // (24 * 3600))
    return i18n.t(lang, "duration_hour")


def build(kind: str, user: User, link: str, seconds: int) -> tuple[str, str, str]:
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
        LANG=lang, TITLE=esc(subject), FONT=esc(FONT), PREVIEW=esc(body),
        GREETING=esc(greeting), BODY=esc(body), BUTTON=esc(button), NOTE=esc(note),
        LINK=esc(link), LINK_TEXT=esc(link), LINK_HELP=esc(i18n.t(lang, "mail_link_help")),
        FOOTER=esc(i18n.t(lang, "mail_footer")),
        STYLE_GLASS=STYLE_GLASS, STYLE_GRADIENTS=STYLE_GRADIENTS, STYLE_SCHEMES=STYLE_SCHEMES,
        STYLE_OUTLOOK=STYLE_OUTLOOK,
        **{key.upper(): value for key, value in LIGHT.items()},
    )
    return subject, text, html


def send_link_mail(kind: str, user: User, token: str, seconds: int) -> bool:
    """Mail the link `<HUB_BASE_URL>/reset/<token>` to the user, in his language. False if it
    could not be sent (no HUB_BASE_URL, no key, or Resend said no)."""
    base = mail.base_url()
    if not base:
        mail.log.warning("mail not sent: HUB_BASE_URL is not set")
        return False
    subject, text, html = build(kind, user, f"{base}/reset/{token}", seconds)
    return mail.send_mail(user.email, subject, text, html)
