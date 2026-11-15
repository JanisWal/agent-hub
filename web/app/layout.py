"""Page shell and the small template engine used by every view (see DESIGN.md)."""
import functools
import hashlib
import html
import re
from pathlib import Path

from . import i18n
from .icons import icon

REPO_URL = "https://github.com/JanisWal/agent-hub"
STATIC_DIR = Path(__file__).parent / "static"


@functools.lru_cache(maxsize=None)
def static_url(name: str) -> str:
    """URL of a file in /static with a content hash, e.g. /static/core.js?v=1a2b3c4d5e.

    Cloudflare and browsers keep static files for hours. A changed file gets a new URL, so a
    page never mixes old and new scripts (an old dashboard.js next to a new core.js broke the
    settings drawer). Files do not change while the container runs, so the hash is cached.
    """
    digest = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
    return f"/static/{name}?v={digest}"

# theme.js runs before the first paint (no defer): it applies the saved theme (no flash) and switches off the
# entrance animation after a reload we triggered ourselves. No page has inline script: the content security
# policy (main.py) allows scripts from /static only.
SHELL = """<!doctype html>
<html lang="%LANG%">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE% – Agent-Hub</title>
<link rel="icon" href="%ICON_SVG%" type="image/svg+xml">
<link rel="icon" href="%ICON_PNG%" sizes="48x48" type="image/png">
<link rel="apple-touch-icon" href="%ICON_TOUCH%">
<meta name="theme-color" content="#EFDCC6" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1F1713" media="(prefers-color-scheme: dark)">
<script src="%THEME_JS%"></script>
<link rel="stylesheet" href="%APP_CSS%">
%STYLES%
<script src="%CORE_JS%" defer></script>
%SCRIPTS%
</head>
<body class="%BODY_CLASS%">
<div class="orbs" aria-hidden="true"><i></i><i></i><i></i></div>
<header class="topbar">
  <a class="brand" href="%REPO_URL%" target="_blank" rel="noopener noreferrer" aria-label="%t.brand_link%">Agent-Hub</a>
  %TOP_LEFT%
  %TOP_CENTER%
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
    top_center: str = "",
    top_left: str = "",
    scripts: tuple[str, ...] = (),
    styles: tuple[str, ...] = (),
    body_class: str = "",
) -> str:
    """Wrap a body in the shell. `title` is plain text, `body`, `top_right` and `top_center` are HTML
    (`top_center` sits in the top bar at the golden section, e.g. the name of a project).

    `styles` and `scripts` are file names in /static (loaded after app.css and core.js).
    """
    return fill(
        SHELL,
        lang,
        LANG=lang,
        TITLE=esc(title),
        APP_CSS=static_url("app.css"),
        CORE_JS=static_url("core.js"),
        THEME_JS=static_url("theme.js"),
        ICON_SVG=static_url("icon.svg"),
        ICON_PNG=static_url("icon-48.png"),
        ICON_TOUCH=static_url("icon-180.png"),
        STYLES="\n".join(f'<link rel="stylesheet" href="{static_url(name)}">' for name in styles),
        SCRIPTS="\n".join(f'<script src="{static_url(name)}" defer></script>' for name in scripts),
        BODY_CLASS=esc(body_class),
        TOP_RIGHT=top_right,
        TOP_CENTER=top_center,
        TOP_LEFT=top_left,
        BODY=body,
        REPO_URL=REPO_URL,
        MOON=icon("moon", "i-moon"),
        SUN=icon("sun", "i-sun"),
    )
