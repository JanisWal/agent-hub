"""Shared page shell: top bar, background colour fields and the theme toggle (see DESIGN.md)."""
import html
import re

from . import i18n

# The inline script applies the saved theme before first paint to avoid a flash.
SHELL = """<!doctype html>
<html lang="%LANG%">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE% – Agent-Hub</title>
<script>try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}catch(e){}</script>
<link rel="stylesheet" href="/static/theme.css">
<script src="/static/theme.js" defer></script>
%SCRIPTS%
</head>
<body>
<div class="orbs" aria-hidden="true"><i></i><i></i><i></i></div>
<header class="topbar">
  <span class="brand">Agent-Hub</span>
  %TOP_RIGHT%
</header>
<main>
%BODY%
</main>
<button id="theme-toggle" class="icon-button theme-fab" type="button" aria-label="%TOGGLE_LABEL%">
  <svg class="i-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
  <svg class="i-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
</button>
</body>
</html>"""


def fill(template: str, **values: str) -> str:
    """Replace %NAME% placeholders in one pass.

    Inserted values are not scanned again, so user text such as a project
    named "%BODY%" cannot inject anything. Unknown placeholders stay as they are.
    """
    return re.sub(
        r"%([A-Z_]+)%", lambda m: str(values.get(m.group(1), m.group(0))), template
    )


def page(title: str, body: str, lang: str = "de", top_right: str = "", scripts=()) -> str:
    """Wrap a body in the shell. `title` is plain text, `body` and `top_right` are HTML."""
    script_tags = "\n".join(f'<script src="{src}" defer></script>' for src in scripts)
    return fill(
        SHELL,
        LANG=lang,
        TITLE=html.escape(title),
        SCRIPTS=script_tags,
        TOP_RIGHT=top_right,
        BODY=body,
        TOGGLE_LABEL=html.escape(i18n.t(lang, "theme_toggle")),
    )
