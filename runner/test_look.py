"""The look tool for AIs whose program reads only text (look_mcp.py). The PDF cases need poppler-utils (in the Vibe
image); elsewhere they are skipped."""
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from runner import look_mcp


def png(width=4, height=4, rgb=b"\xff\x00\x00") -> bytes:
    raw = b"".join(b"\x00" + rgb * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def pdf(pages: list[str]) -> bytes:
    """A small valid PDF with one line of text per page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages))), len(pages)),
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        stream = f"BT /F1 24 Tf 40 700 Td ({text}) Tj ET"
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
                       "/Resources << /Font << /F1 3 0 R >> >> >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class LookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.files, self.work, self.outside = base / "files", base / "work", base / "secret"
        for folder in (self.files / "media", self.work, self.outside):
            folder.mkdir(parents=True)
        roots = mock.patch.object(look_mcp, "ROOTS", (str(self.files), str(base / "code"), str(self.work)))
        roots.start()
        self.addCleanup(roots.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_an_image_comes_back_as_a_picture_by_its_bytes_not_its_name(self):
        (self.files / "media" / "red.png").write_bytes(png())
        (self.files / "media" / "renamed.txt").write_bytes(png())
        for name in ("red.png", "renamed.txt"):
            content = look_mcp.look(str(self.files / "media" / name))
            self.assertEqual(content[0]["type"], "image")
            self.assertEqual(content[0]["mimeType"], "image/png")
            self.assertEqual(base64.b64decode(content[0]["data"]), png())

    def test_only_files_below_the_roots_and_never_through_a_link(self):
        (self.outside / "key.png").write_bytes(png())
        (self.work / "link.png").symlink_to(self.outside / "key.png")
        for path in (str(self.outside / "key.png"), str(self.work / "link.png"), str(self.files / ".." / "secret" / "key.png"),
                     "relative.png", "", None, str(self.files / "media" / "missing.png")):
            with self.assertRaises(look_mcp.Refused):
                look_mcp.look(path)

    def test_other_files_are_refused_and_a_blind_model_gets_no_picture(self):
        (self.files / "notes.md").write_text("# hello")
        with self.assertRaises(look_mcp.Refused):
            look_mcp.look(str(self.files / "notes.md"))
        (self.files / "media" / "red.png").write_bytes(png())
        with self.assertRaises(look_mcp.Refused):
            look_mcp.look(str(self.files / "media" / "red.png"), images=False)

    def test_page_ranges(self):
        self.assertEqual(look_mcp.page_range("", 20), (1, look_mcp.MAX_PAGES))
        self.assertEqual(look_mcp.page_range("", 3), (1, 3))
        self.assertEqual(look_mcp.page_range("5", 20), (5, 5))
        self.assertEqual(look_mcp.page_range("5-40", 20), (5, 5 + look_mcp.MAX_PAGES - 1))
        self.assertEqual(look_mcp.page_range("18 - 30", 20), (18, 20))
        for bad in ("0", "21", "4-2", "a", "1;rm", "-3"):
            with self.assertRaises(look_mcp.Refused):
                look_mcp.page_range(bad, 20)

    @unittest.skipUnless(shutil.which("pdftoppm"), "needs poppler-utils")
    def test_a_pdf_gives_its_text_and_its_pages_as_pictures(self):
        (self.files / "manual.pdf").write_bytes(pdf([f"Page number {n}" for n in range(1, 11)]))
        content = look_mcp.look(str(self.files / "manual.pdf"))
        self.assertIn("PDF with 10 pages, pages 1 to 8", content[0]["text"])
        self.assertIn('pages="9-10"', content[0]["text"])
        self.assertIn("Page number 3", content[0]["text"])
        pictures = [c for c in content if c["type"] == "image"]
        self.assertEqual(len(pictures), 8)
        self.assertTrue(base64.b64decode(pictures[0]["data"]).startswith(b"\xff\xd8\xff"))
        later = look_mcp.look(str(self.files / "manual.pdf"), "10")
        self.assertIn("Page number 10", later[0]["text"])
        self.assertEqual(sum(c["type"] == "image" for c in later), 1)
        blind = look_mcp.look(str(self.files / "manual.pdf"), images=False)
        self.assertFalse(any(c["type"] == "image" for c in blind))
        (self.files / "broken.pdf").write_bytes(b"%PDF-1.4 nothing else")
        with self.assertRaises(look_mcp.Refused):
            look_mcp.look(str(self.files / "broken.pdf"))

    def test_the_server_speaks_mcp_on_stdio(self):
        (self.files / "media" / "red.png").write_bytes(png())
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "look", "arguments": {"path": str(self.files / "media" / "red.png")}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "look", "arguments": {"path": "/etc/passwd"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
        ]
        replies = {r["id"]: r for r in (look_mcp.answer(m, True) for m in messages) if r is not None}
        self.assertEqual(sorted(replies), [1, 2, 3, 4, 5])
        self.assertEqual(replies[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual([t["name"] for t in replies[2]["result"]["tools"]], ["look"])
        self.assertEqual(replies[3]["result"]["content"][0]["type"], "image")
        self.assertTrue(replies[4]["result"]["isError"])
        self.assertIn("error", replies[5])
        # and as a real process, the way the program starts it
        script = Path(look_mcp.__file__)
        done = subprocess.run([sys.executable, str(script)], input="\n".join(json.dumps(m) for m in messages[:3]) + "\n",
                              capture_output=True, text=True, timeout=30, env=dict(os.environ, HUB_IMAGES="0"))
        lines = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([line["id"] for line in lines], [1, 2])


if __name__ == "__main__":
    unittest.main()
