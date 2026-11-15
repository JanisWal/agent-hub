"""Draws the pictures of the mails (glass and glow that mail programs cannot draw with CSS).

    python3 tools/make_mail_images.py OUT_DIR      (standard library only; run once, the PNGs are committed)

Mail programs know no blur, no shadow and often no gradient, so the light edge, the glow and the soft
colour fields behind the card are pictures (twice the size for sharp screens, see mailtext.py). They are
overlays with transparency: below each of them the mail keeps a solid colour, so a program that blocks
pictures shows a flat but complete mail. The colours are the two palettes of mailtext.py.
"""
import math
import os
import struct
import sys
import zlib

PALETTES = {
    "light": {"CARD": (247, 230, 211), "BORDER": (226, 199, 168), "ACCENT": (232, 132, 90), "EDGE": (255, 255, 255, 0.55),
              "SHEEN": 0.20, "ORBS": ((240, 168, 120, 0.50), (230, 191, 140, 0.55), (232, 132, 90, 0.40))},
    "dark": {"CARD": (51, 36, 28), "BORDER": (74, 52, 40), "ACCENT": (242, 154, 114), "EDGE": (255, 220, 190, 0.30),
             "SHEEN": 0.03, "ORBS": ((138, 79, 46, 0.55), (107, 58, 34, 0.60), (200, 104, 63, 0.42))},
}


def write_png(path, width, height, rows):
    """`rows` is a list of bytes (RGBA, not premultiplied) per line."""
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)


def render(width, height, shade, samples=3):
    """Averages `shade(x, y) -> (r, g, b, a)` (a from 0 to 1) over samples x samples points per pixel."""
    rows = []
    step = 1.0 / samples
    for y in range(height):
        row = bytearray()
        for x in range(width):
            red = green = blue = alpha = 0.0
            for sy in range(samples):
                for sx in range(samples):
                    r, g, b, a = shade(x + (sx + 0.5) * step, y + (sy + 0.5) * step)
                    red += r * a
                    green += g * a
                    blue += b * a
                    alpha += a
            count = samples * samples
            if alpha > 0:
                row += bytes((round(red / alpha), round(green / alpha), round(blue / alpha), round(255 * alpha / count)))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    return rows


def over(base, top):
    """`top` (r, g, b, a) laid over `base` (r, g, b, a)."""
    ta, ba = top[3], base[3]
    alpha = ta + ba * (1 - ta)
    if alpha == 0:
        return (0, 0, 0, 0)
    return tuple((top[i] * ta + base[i] * ba * (1 - ta)) / alpha for i in range(3)) + (alpha,)


def box_distance(x, y, left, top, right, bottom, radius):
    """Signed distance to a rounded rectangle (negative inside)."""
    cx, cy = (left + right) / 2, (top + bottom) / 2
    qx = abs(x - cx) - ((right - left) / 2 - radius)
    qy = abs(y - cy) - ((bottom - top) / 2 - radius)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius


def coverage(distance):
    return min(1.0, max(0.0, 0.5 - distance))  # one pixel soft edge


def card_cap(name, palette, top, size=(1040, 80)):
    """Top or bottom end of the card as an overlay: the border ring, the light edge and the sheen. There is no
    fill: the fill is the colour of the cell below (clipped round by the program), so a program that recolours the
    card for its dark mode recolours the ends with it (Yahoo did; a filled picture stayed light)."""
    width, height = size
    radius, line = 56, 2
    border, edge, sheen = palette["BORDER"], palette["EDGE"], palette["SHEEN"]

    def shade(x, y):
        yy = y if top else height - y
        distance = box_distance(x, yy, 0, 0, width, height * 4, radius)
        if coverage(distance) == 0:
            return (0, 0, 0, 0)
        ring = coverage(distance) - coverage(distance + line)
        inside = coverage(distance + line)
        colour = (*border, max(0.0, ring))
        if top:
            colour = over(colour, (255, 255, 255, sheen * max(0.0, 1 - yy / height) ** 1.5 * inside))
            glint = max(0.0, coverage(distance + line + 1) - coverage(distance + line + 3))  # light edge inside the ring
            colour = over(colour, (edge[0], edge[1], edge[2], edge[3] * glint * (1 - min(1.0, yy / (height * 0.9)))))
        return colour

    return name, width, height, render(width, height, shade)


def button_sheen(name, palette, size=(520, 108)):
    """Gloss over the button's solid colour: light top, soft shade at the bottom, a hairline edge."""
    width, height = size
    radius = 32

    def shade(x, y):
        distance = box_distance(x, y, 0, 0, width, height, radius)
        inside = coverage(distance)
        if inside == 0:
            return (0, 0, 0, 0)
        gloss = 0.40 * max(0.0, 1 - y / (height * 0.58)) ** 1.2
        colour = (255, 255, 255, gloss)
        colour = over(colour, (60, 25, 5, 0.12 * max(0.0, (y - height * 0.6) / (height * 0.4))))
        colour = over(colour, (255, 255, 255, 0.45 * (coverage(distance + 3) - coverage(distance + 1)) * max(0.0, 1 - y / (height * 0.5))))
        return (*colour[:3], colour[3] * inside)

    return name, width, height, render(width, height, shade)


def backdrop(name, palette, size=(1200, 720)):
    """The coloured fields behind the glass, like the orbs of the site, fading out to the page colour."""
    width, height = size
    orbs = palette["ORBS"]
    spots = ((0.18, 0.12, 380, orbs[0]), (0.82, 0.05, 340, orbs[1]), (0.55, 0.38, 300, orbs[2]))

    def shade(x, y):
        colour = (0, 0, 0, 0.0)
        for fx, fy, reach, (r, g, b, a) in spots:
            d = math.hypot(x - fx * width, y - fy * height) / reach
            if d < 1:
                colour = over(colour, (r, g, b, a * (1 - d) ** 2 * (3 - 2 * (1 - d)) ))
        fade = min(1.0, max(0.0, (height - y) / (height * 0.35)))
        side = min(1.0, x / (width * 0.2), (width - x) / (width * 0.2))  # no hard edge left and right
        side = side * side * (3 - 2 * side)
        return (*colour[:3], colour[3] * fade * side)

    return name, width, height, render(width, height, shade, samples=1)


def main(out):
    os.makedirs(out, exist_ok=True)
    for theme, palette in PALETTES.items():
        for name, width, height, rows in (
            card_cap(f"card-top-{theme}", palette, True),
            card_cap(f"card-bottom-{theme}", palette, False, (1040, 56)),
            button_sheen(f"button-{theme}", palette),
            backdrop(f"backdrop-{theme}", palette),
        ):
            write_png(os.path.join(out, name + ".png"), width, height, rows)
            print(name, width, height)


if __name__ == "__main__":
    main(sys.argv[1])
