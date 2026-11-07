"""Page shell and the small template engine used by every view (see DESIGN.md)."""
import html
import re

from . import i18n
from .icons import icon

REPO_URL = "https://github.com/JanisWal/agent-hub"

# The inline script applies the saved theme before first paint (no flash) and switches off the
# entrance animation after a reload we triggered ourselves ("noanim", see core.js).
SHELL = """<!doctype html>
<html lang="%LANG%">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE% – Agent-Hub</title>
<script>try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t;if(sessionStorage.getItem("noanim")){document.documentElement.classList.add("noanim");sessionStorage.removeItem("noanim")}}catch(e){}</script>
<link rel="stylesheet" href="/static/app.css">
%STYLES%
<script src="/static/core.js" defer></script>
%SCRIPTS%
</head>
<body class="%BODY_CLASS%">
<div class="orbs" aria-hidden="true"><i></i><i></i><i></i></div>
<header class="topbar">
  <a class="brand" href="%REPO_URL%" target="_blank" rel="noopener noreferrer" aria-label="%t.brand_link%">Agent-Hub</a>
  %TOP_RIGHT%
</header>
<main>
%BODY%
</main>
<button id="theme-toggle" class="icon-button theme-fab" type="button" aria-label="%t.theme_toggle%">
  %MOON%
  %SUN%
</button>
</body>
</html>"""

_PLACEHOLDER = re.compile(r"%(t\.[a-z_]+|[A-Z_]+)%")


def esc(text: str) -> str:
    """Escape for HTML text and attribute values."""
    return html.escape(text, quote=True)


def fill(template: str, lang: str = "de", **values: str) -> str:
    """Replace placeholders in one pass.

    `%NAME%` is replaced by the keyword value of that name (HTML as given, escape user text
    yourself), `%t.key%` by the escaped translation of `key` in `lang`. Inserted values are
    not scanned again, so user text such as a project named "%BODY%" cannot inject anything.
    Unknown upper-case placeholders stay as they are, an unknown translation key raises KeyError.
    """

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name.startswith("t."):
            return esc(i18n.t(lang, name[2:]))
        return str(values.get(name, match.group(0)))

    return _PLACEHOLDER.sub(replace, template)


def page(
    title: str,
    body: str,
    lang: str = "de",
    *,
    top_right: str = "",
    scripts: tuple[str, ...] = (),
    styles: tuple[str, ...] = (),
    body_class: str = "",
) -> str:
    """Wrap a body in the shell. `title` is plain text, `body` and `top_right` are HTML.

    `styles` and `scripts` are file names in /static (loaded after app.css and core.js).
    """
    return fill(
        SHELL,
        lang,
        LANG=lang,
        TITLE=esc(title),
        STYLES="\n".join(f'<link rel="stylesheet" href="/static/{name}">' for name in styles),
        SCRIPTS="\n".join(f'<script src="/static/{name}" defer></script>' for name in scripts),
        BODY_CLASS=esc(body_class),
        TOP_RIGHT=top_right,
        BODY=body,
        REPO_URL=REPO_URL,
        MOON=icon("moon", "i-moon"),
        SUN=icon("sun", "i-sun"),
    )
