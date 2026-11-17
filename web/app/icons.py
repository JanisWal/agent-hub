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
    # Device pictograms (devices.icon_for; redrawn 17.11.2026 after Janis' wishes): the picture of a device in the
    # Manager view. Servers are rack units, with a penguin (Linux) or the four panes (Windows); a Mac is the rounded
    # body of any Mac (mini, Studio, iMac, MacBook alike) with an apple; a Raspberry Pi is a dense board (pin header,
    # chips, ports), a microcontroller a small one with pins; a router stands upright with radio waves.
    "dev_pi": ('<rect x="2" y="5" width="20" height="14" rx="1.6"/><path d="M5 7.6h.01M7.2 7.6h.01M9.4 7.6h.01'
               'M11.6 7.6h.01M13.8 7.6h.01M16 7.6h.01"/><rect x="5.5" y="10.5" width="5" height="5" rx=".6"/>'
               '<rect x="12.5" y="11" width="3" height="3" rx=".4"/><path d="M22 10.5h-3.2v3.2H22M22 15.2h-3.2v2.3H22"/>'
               '<path d="M4 17.2v.01"/>'),
    "dev_chip": ('<rect x="7" y="3" width="10" height="18" rx="1.4"/><rect x="9.5" y="6.5" width="5" height="5" rx=".5"/>'
                 '<path d="M4.5 6h2.5M4.5 9h2.5M4.5 12h2.5M4.5 15h2.5M17 6h2.5M17 9h2.5M17 12h2.5M17 15h2.5M10.5 21v-2.4h3V21"/>'),
    "dev_server_linux": ('<rect x="2" y="3" width="13" height="6.5" rx="1.6"/><rect x="2" y="11.5" width="11" height="6.5" rx="1.6"/>'
                         '<path d="M5 6.2v.01M5 14.7v.01M8 6.2h4"/>'
                         '<circle cx="18.2" cy="11.6" r="2.4"/><path d="M15.6 21c-.7-1.7-.6-4.5.6-6.2a2.4 2.4 0 0 1 4 0'
                         'c1.2 1.7 1.3 4.5.6 6.2zM14.8 21.4h2.4M19.2 21.4h2.4M17.4 11.3v.01M19 11.3v.01"/>'),
    "dev_server_windows": ('<rect x="2" y="3" width="13" height="6.5" rx="1.6"/><rect x="2" y="11.5" width="11" height="6.5" rx="1.6"/>'
                           '<path d="M5 6.2v.01M5 14.7v.01M8 6.2h4"/><path fill="currentColor" stroke="none" d="M15.6 13.4h2.8v2.8h-2.8zM19.2 13.4h2.8v2.8h-2.8zM15.6 17.0h2.8v2.8h-2.8zM19.2 17.0h2.8v2.8h-2.8z"/>'),
    "dev_pc_windows": ('<rect x="2" y="3" width="20" height="13.5" rx="2"/><path d="M8 21h8M12 16.5V21"/><path fill="currentColor" stroke="none" d="M9.3 7h2.3v2.3h-2.3zM12.400000000000002 7h2.3v2.3h-2.3zM9.3 10.100000000000001h2.3v2.3h-2.3zM12.400000000000002 10.100000000000001h2.3v2.3h-2.3z"/>'),
    "dev_linux": ('<rect x="2" y="3" width="20" height="13.5" rx="2"/><path d="M8 21h8M12 16.5V21"/>'
                  '<circle cx="12" cy="7.4" r="1.7"/><path d="M10.1 13.8c-.5-1.2-.4-3 .4-4.1a1.9 1.9 0 0 1 3 0'
                  'c.8 1.1.9 2.9.4 4.1z"/>'),
    "dev_mac": ('<rect x="3" y="3" width="18" height="18" rx="5"/><path fill="currentColor" stroke="none" d="M12 9.6c.9-.6 2-.9 3-.4 1.3.6 1.9 1.9 1.9 3.3 0 2.6-1.6 5.3-3 5.3-.7 0-1.1-.4-1.9-.4s-1.2.4-1.9.4c-1.4 0-3-2.7-3-5.3 0-1.4.6-2.7 1.9-3.3 1-.5 2.1-.2 3 .4zM12.2 8.9c0-1.3.8-2.4 2.1-2.7.1 1.3-.8 2.5-2.1 2.7z"/>'),
    "dev_router": ('<rect x="8" y="10" width="8" height="11" rx="1.8"/><path d="M12 13.2v.01M12 15.7v.01M12 18.2v.01"/>'
                   '<path d="M9.6 7.4a3.4 3.4 0 0 1 4.8 0M7.4 5.2a6.5 6.5 0 0 1 9.2 0M5.2 3a9.6 9.6 0 0 1 13.6 0"/>'),
    "dev_box": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9"/>',
    # what a device is for, read from its name or description (devices.CONTEXT_ICON)
    "dev_display": '<rect x="2" y="4" width="20" height="13" rx="1.6"/><path d="M9 21h6M12 17v4M6 13l3-3 2.5 2.5L15 9l3 3"/>',
    "dev_camera": '<rect x="3" y="7" width="18" height="12" rx="2.5"/><circle cx="12" cy="13" r="3.5"/><path d="M8.5 7L10 4.5h4L15.5 7"/>',
    "dev_printer": '<path d="M7 9V3h10v6M7 18H4.5a1.5 1.5 0 0 1-1.5-1.5V11a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5.5a1.5 1.5 0 0 1-1.5 1.5H17"/><path d="M7 14h10v7H7z"/>',
    "dev_storage": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 10.5h8M8 14h8M9 18h.01M12 18h.01"/>',
    "dev_speaker": '<rect x="6" y="3" width="12" height="18" rx="2"/><circle cx="12" cy="14.5" r="3.2"/><circle cx="12" cy="7.5" r="1.2"/>',
    "dev_sensor": '<circle cx="12" cy="12" r="2"/><path d="M8 8a5.6 5.6 0 0 0 0 8M16 8a5.6 5.6 0 0 1 0 8M5.2 5.2a9.6 9.6 0 0 0 0 13.6M18.8 5.2a9.6 9.6 0 0 1 0 13.6"/>',
    "dev_light": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
    # Device actions and the device window (17.11.2026): power, restart (a circle with an arrow), update (a line with
    # an arrow up above it), the shell, the files and the logs of a device
    "power": '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "update": '<path d="M5 20h14"/><path d="M12 16V4M7 9l5-5 5 5"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3.5 6v.01M3.5 12v.01M3.5 18v.01"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
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
