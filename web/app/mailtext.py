"""The mails with a button and a link (password reset, invitation): text, HTML and sending.

The HTML uses tables and inline styles only, because mail programs ignore most CSS. It is built for the weakest of
them (Janis, 15.11.2026: Outlook for Windows draws with Word, Yahoo drops much): colours also as `bgcolor`
attributes, the width as an attribute, standard font weights, and a button whose coloured cell carries the padding
(`mso-padding-alt`), so it is a real button there too. Outlook takes only the first font of a list and falls back
to Times when it lacks it, so a block only Outlook reads sets Arial; it also gets 96 dpi, or it scales the mail.
Colours follow DESIGN.md; the two palettes are the light and the dark style of the site. The mail shows one fixed
palette: the style the user saw last on the site (`users.theme`, reported by the theme switch). A mail program
cannot be asked which one the reader likes.

Glass and glow (Janis, 15.11.2026: "the flat 2D version" in other programs): mail programs know no blur, no shadow
and often no gradient, so the light edge, the sheen of the button and the coloured fields behind
the card are pictures (`static/mail/*.png`, drawn by `tools/make_mail_images.py`, served from `HUB_BASE_URL`).
They are overlays with transparency over solid colours, so a program that blocks pictures still shows a complete,
flat mail. Outlook for Windows gets no pictures (no round corners there) but a flat card and a VML button.
Robust against recolouring: every cell carries its colours explicitly, no pure white or black, and `[data-ogsc]`
and `[data-ogsb]` (set by Outlook.com and its apps when they recolour) bring our colours back. Yahoo's dark mode (Janis' screenshots, 15.11.2026) recolours a
cell only by its `bgcolor` attribute and leaves cells with a background picture light: so every cell that must follow the
card carries `bgcolor` and no picture (the halo of the button is a shadow, not a picture). Some programs lighten the colour of links and of CSS borders in their dark mode (Janis' screenshot, 15.11.2026: the button text
turned pale on orange, the side lines turned cream): the button text sits in a `span` inside the link, and the side
lines of the card are narrow cells with `bgcolor`, not CSS borders. Programs that
recolour on their own (Gmail app) we cannot stop, so the colours are chosen to stay readable when inverted.
Texts live in i18n.py (`mail_<kind>_subject|body|button|note`), so they exist in both languages.
"""
import functools
import hashlib
import os

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

# Page with the coloured fields behind it, a card made of top end, middle and bottom end (the ends are
# pictures with round corners and the light edge; programs that block them show the solid colour), headline,
# text, the button (the sheen as a picture over the solid colour, the halo as a shadow; a VML button for Outlook for Windows),
# the link as text for programs that block buttons, a note. `<!--[if !mso]><!-->` is read by everything but Outlook
# for Windows, `<!--[if mso]>` only by it.
HTML = """<!doctype html>
<html lang="%LANG%" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">
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
<style>
:root{color-scheme:%SCHEME%;supported-color-schemes:%SCHEME%;}
[data-ogsb] .page{background-color:%BG% !important;}
[data-ogsb] .card{background-color:%CARD% !important;}
[data-ogsb] .btn{background-color:%ACCENT% !important;}
[data-ogsc] .t{color:%TEXT% !important;}
[data-ogsc] .m{color:%MUTED% !important;}
[data-ogsc] .bt{color:%ON_ACCENT% !important;}
</style>
<title>%TITLE%</title>
</head>
<body class="page" bgcolor="%BG%" style="margin:0;padding:0;width:100%;background-color:%BG%;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<table class="page" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="%BG%" style="width:100%;background-color:%BG%;border-collapse:collapse;">
<tr><td class="page" align="center" bgcolor="%BG%"%BACKDROP% style="padding:32px 16px;%BACKDROP_CSS%">
  <table role="presentation" width="520" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:520px;border-collapse:separate;border-spacing:0;">
    <tr><td class="t" style="padding:0 8px 16px;font-family:%FONT%;font-size:18px;font-weight:700;letter-spacing:-0.01em;color:%TEXT%;">Agent-Hub</td></tr>
<!--[if !mso]><!-->
    <tr><td class="card" bgcolor="%CARD%" style="padding:0;font-size:0;line-height:0;background-color:%CARD%;border-radius:28px 28px 0 0;">%CAP_TOP%</td></tr>
<!--<![endif]-->
<!--[if mso]>
    <tr><td bgcolor="%CARD%" height="24" style="background-color:%CARD%;border-top:1px solid %BORDER%;border-left:1px solid %BORDER%;border-right:1px solid %BORDER%;font-size:0;line-height:0;">&nbsp;</td></tr>
<![endif]-->
    <tr><td style="padding:0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;"><tr>
    <td width="1" bgcolor="%BORDER%" style="width:1px;background-color:%BORDER%;font-size:0;line-height:0;">&nbsp;</td>
    <td class="card" bgcolor="%CARD%" style="background-color:%CARD%;padding:0 32px;font-family:%FONT%;color:%TEXT%;">
      <h1 class="t" style="margin:0 0 16px;font-family:%FONT%;font-size:30px;line-height:1.15;mso-line-height-rule:exactly;font-weight:700;letter-spacing:-0.03em;color:%TEXT%;">%GREETING%</h1>
      <p class="t" style="margin:0 0 28px;font-family:%FONT%;font-size:17px;line-height:1.55;color:%TEXT%;">%BODY%</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:320px;margin:0 auto;"><tr>
        <td class="card" align="center" bgcolor="%CARD%" style="padding:18px 16px;background-color:%CARD%;">
<!--[if mso]>
          <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="%LINK%" style="height:54px;width:260px;v-text-anchor:middle;" arcsize="30%" strokecolor="%ACCENT%" fillcolor="%ACCENT%"><v:fill type="gradient" color="%SHEEN%" color2="%ACCENT%" angle="180"/><w:anchorlock/><center style="font-family:Arial,sans-serif;font-size:17px;font-weight:bold;color:%ON_ACCENT%;">%BUTTON%</center></v:roundrect>
<![endif]-->
<!--[if !mso]><!-->
          <table role="presentation" width="260" cellpadding="0" cellspacing="0" border="0" align="center" style="width:260px;margin:0 auto;"><tr>
            <td class="btn" align="center" bgcolor="%ACCENT%"%SHEEN_PIC% style="width:260px;height:54px;border-radius:16px;background-color:%ACCENT%;box-shadow:0 0 18px 2px rgba(%ACCENT_RGB%,0.45);%SHEEN_CSS%">
              <a class="bt" href="%LINK%" style="display:block;height:54px;line-height:54px;white-space:nowrap;font-family:%FONT%;font-size:17px;font-weight:700;color:%ON_ACCENT%;text-decoration:none;border-radius:16px;"><span class="bt" style="color:%ON_ACCENT%;">%BUTTON%</span></a>
            </td>
          </tr></table>
<!--<![endif]-->
        </td>
      </tr></table>
      <p class="m" style="margin:20px 0 4px;font-size:13px;line-height:1.4;color:%MUTED%;">%LINK_HELP%</p>
      <p class="m" style="margin:0;font-size:13px;line-height:1.4;word-break:break-all;"><a href="%LINK%" style="color:%MUTED%;">%LINK_TEXT%</a></p>
      <p class="m" style="margin:28px 0 0;font-size:13px;line-height:1.55;color:%MUTED%;">%NOTE%</p>
    </td>
    <td width="1" bgcolor="%BORDER%" style="width:1px;background-color:%BORDER%;font-size:0;line-height:0;">&nbsp;</td>
    </tr></table></td></tr>
<!--[if !mso]><!-->
    <tr><td class="card" bgcolor="%CARD%" style="padding:0;font-size:0;line-height:0;background-color:%CARD%;border-radius:0 0 28px 28px;">%CAP_BOTTOM%</td></tr>
<!--<![endif]-->
<!--[if mso]>
    <tr><td bgcolor="%CARD%" height="24" style="background-color:%CARD%;border-bottom:1px solid %BORDER%;border-left:1px solid %BORDER%;border-right:1px solid %BORDER%;font-size:0;line-height:0;">&nbsp;</td></tr>
<![endif]-->
    <tr><td class="m" style="padding:16px 8px 0;font-family:%FONT%;font-size:12px;line-height:1.4;color:%MUTED%;">%FOOTER%</td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""

# Sizes of the pictures as shown (the files are twice as large), see tools/make_mail_images.py.
PICTURES = {"backdrop": (600, 360), "button": (260, 54)}
CAPS = {"card-top": (520, 40), "card-bottom": (520, 28)}


@functools.lru_cache(maxsize=None)
def _version(name: str) -> str:
    """Short hash of a picture file for `?v=`: mail proxies (Apple Mail, Gmail) keep a picture by its address for
    a long time, so a changed picture needs a new address (an old halo showed as a strip under the button)."""
    with open(os.path.join(os.path.dirname(__file__), "static", "mail", name + ".png"), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:8]


def _lighter(colour: str, share: float = 0.28) -> str:
    """`#RRGGBB` mixed with white, for the gradient of the Outlook button."""
    red, green, blue = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(round(value + (255 - value) * share) for value in (red, green, blue))


def _pictures(theme: str) -> dict[str, str]:
    """Placeholders for the pictures: `X` is the HTML attribute, `X_CSS` the style part (programs read one or the
    other). All empty when `HUB_BASE_URL` is not set: a flat mail, still complete."""
    names = ("BACKDROP", "BACKDROP_CSS", "SHEEN_PIC", "SHEEN_CSS", "CAP_TOP", "CAP_BOTTOM")
    base = mail.base_url()
    if not base:
        return {name: "" for name in names}

    def url(name: str) -> str:
        return esc(f"{base}/static/mail/{name}-{theme}.png?v={_version(f'{name}-{theme}')}")

    def css(name: str, picture: str, position: str) -> str:
        width, height = PICTURES[picture]
        return (f"background-image:url('{url(name)}');background-repeat:no-repeat;"
                f"background-position:{position};background-size:{width}px {height}px;")

    def cap(name: str) -> str:
        width, height = CAPS[name]
        return (f'<img src="{url(name)}" width="{width}" height="{height}" alt="" '
                'style="display:block;width:100%;height:auto;border:0;">')

    return {
        "BACKDROP": f' background="{url("backdrop")}"', "BACKDROP_CSS": css("backdrop", "backdrop", "center top"),
        "SHEEN_PIC": f' background="{url("button")}"', "SHEEN_CSS": css("button", "button", "center"),
        "CAP_TOP": cap("card-top"), "CAP_BOTTOM": cap("card-bottom"),
    }


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
    theme = theme if theme in PALETTES else (user.theme if user.theme in PALETTES else "light")
    palette = PALETTES[theme]
    greeting = i18n.t(lang, "mail_greeting", name=user.name)
    body = i18n.t(lang, f"mail_{kind}_body")
    button = i18n.t(lang, f"mail_{kind}_button")
    note = i18n.t(lang, f"mail_{kind}_note", duration=_duration(lang, seconds))
    subject = i18n.t(lang, f"mail_{kind}_subject")
    text = f"{greeting}\n\n{body}\n\n{button}:\n{link}\n\n{note}\n"
    html = fill(
        HTML, lang,
        LANG=lang, SCHEME=theme, FONT=esc(FONT), TITLE=esc(subject),
        GREETING=esc(greeting), BODY=esc(body), BUTTON=esc(button), NOTE=esc(note),
        LINK=esc(link), LINK_TEXT=esc(link), LINK_HELP=esc(i18n.t(lang, "mail_link_help")),
        FOOTER=esc(i18n.t(lang, "mail_footer")),
        **palette, SHEEN=_lighter(palette["ACCENT"]), ACCENT_RGB=",".join(str(int(palette["ACCENT"][i:i + 2], 16)) for i in (1, 3, 5)), **_pictures(theme),
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
