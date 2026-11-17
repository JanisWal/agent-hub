"""All inline SVG icons (24 x 24 grid) in one place."""

# Line icons are drawn with stroke (see app.css), "filled" ones with fill.
_GEAR = (
    '<circle cx="12" cy="12" r="3"/>'
    '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06'
    "a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4"
    "a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82"
    " 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82"
    "l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3"
    "a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0"
    " 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2"
    'h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
)

ICONS = {
    "gear": _GEAR,
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.01"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "expand": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "collapse": '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
    "arrow_left": '<path d="M15 6l-6 6 6 6"/>',
    "arrow_up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "inbox": '<path d="M4 13l2.4-7.2A1.2 1.2 0 0 1 7.5 5h9a1.2 1.2 0 0 1 1.1.8L20 13"/><path d="M4 13v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5h-5a3 3 0 0 1-6 0z"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.4 2.6 3.6 5.6 3.6 9s-1.2 6.4-3.6 9c-2.4-2.6-3.6-5.6-3.6-9S9.6 5.6 12 3z"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    # Device pictograms (devices.icon_for): the picture of a device in the Manager view
    "dev_pi": '<rect x="3" y="6" width="18" height="12" rx="2"/><rect x="6.5" y="9.5" width="4" height="4" rx="0.6"/><path d="M14 9.5h4M14 12h4M14 14.5h2M7 18v2M11 18v2M15 18v2"/>',
    "dev_server": '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5v.01M7 16.5v.01M11 7.5h6M11 16.5h6"/>',
    "dev_windows": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16M3 12h18"/>',
    "dev_pc": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "dev_mac": '<rect x="5" y="5" width="14" height="10" rx="1.5"/><path d="M2.5 19h19l-1.5-4H4z"/>',
    "dev_chip": '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    "dev_router": '<rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 17v.01M11 17v.01M8 14l-2-6M16 14l2-6"/>',
    "dev_linux": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="M10.4 13c-.6-.9-.3-2 .2-2.8.3-.5.4-1 .4-1.6a1 1 0 0 1 2 0c0 .6.1 1.1.4 1.6.5.8.8 1.9.2 2.8"/>',
    # Device actions and the device window (17.11.2026): power, restart (a circle with an arrow), update (a line with
    # an arrow up above it), the shell, the files and the logs of a device
    "power": '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "update": '<path d="M5 20h14"/><path d="M12 16V4M7 9l5-5 5 5"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3.5 6v.01M3.5 12v.01M3.5 18v.01"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "dev_box": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 12h6"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M16 7l3 3M13.5 9.5l2.5 2.5"/>',
    "crown": '<path d="M3 7l4.5 4L12 4l4.5 7L21 7l-2 11H5z"/><path d="M5 21h14"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12z"/>',
    "done":'<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "note": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "photo": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/>',
    "film": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9.5v5l4.5-2.5z"/>',
    "music": '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "download": '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "pencil": '<path d="M4 20l1-4L16.5 4.5a2 2 0 0 1 3 3L8 19z"/><path d="M14 7l3 3"/>',
    "check": '<path d="M5 12.5l5 5 9-10"/>',
    "play": '<path d="M8 5.5v13l10-6.5z"/>',
    "star": '<path d="M12 3.8l2.5 5.1 5.6.8-4 3.9.9 5.6-5-2.6-5 2.6.9-5.6-4-3.9 5.6-.8z"/>',
    "cross": '<path d="M6 6l12 12M18 6L6 18"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
    "triangle_left": '<path d="M15 6l-8 6 8 6z"/>',
    "triangle_right": '<path d="M9 6l8 6-8 6z"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "sun": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
    ),
}


def icon(name: str, css_class: str = "") -> str:
    """The icon as an <svg> element, optionally with a CSS class."""
    cls = f' class="{css_class}"' if css_class else ""
    return f'<svg{cls} viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'
