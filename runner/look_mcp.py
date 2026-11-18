"""A tool to look at images and PDFs for an AI whose program can only read text files (Janis, 18.11.2026: "the AIs must
really see the pictures and PDFs"). Standard library only; runs inside the run's container as an MCP server on stdio
(Mistral Vibe starts it, runner/vibe_entry.py). Claude Code needs none of this: its Read tool shows images and PDF
pages itself.

One tool, `look(path, pages="")`:
- an image (PNG, JPEG, GIF, WebP; the type from its first bytes, never from the name) comes back as a picture;
- a PDF comes back as its text (pdftotext) and its pages as pictures (pdftoppm, at most MAX_PAGES per call; `pages`
  picks others, "3" or "5-8");
- anything else is refused with a short note (text files are read with the program's own file tool).

Only files below ROOTS are opened (the read-only /files and /code, the run's /work), after following links, so a
link in /work can not point the tool elsewhere. HUB_IMAGES=0 (a model that can not see pictures): PDFs still give
their text, images only a note. The program passes on whatever picture the tool returns (checked with Vibe 3.1.2:
an MCP image becomes an image part of the next model request).
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOTS = ("/files", "/code", "/work")
MAX_IMAGE = 10 * 1024 ** 2      # Mistral's limit for one image
MAX_PDF = 100 * 1024 ** 2
MAX_PAGES = 8                   # pictures of PDF pages per call
MAX_TEXT = 30000                # characters of PDF text per call
SECONDS = 90
SCALE = 1400                    # longest side of a page picture in pixels: readable, a few hundred KB
MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
         (b"GIF89a", "image/gif"))
TOOL = {
    "name": "look",
    "description": ("Look at an image (PNG, JPEG, GIF, WebP) or a PDF of the project: the picture itself, or the PDF's "
                    "text and its pages as pictures. path: absolute path below /files, /code or /work. pages (PDF "
                    f"only, optional): \"3\" or \"5-8\", at most {MAX_PAGES} pages per call; without it the first pages."),
    "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "pages": {"type": "string"}},
                    "required": ["path"]},
}


class Refused(Exception):
    pass


def _inside(path: str) -> Path:
    """The real file, if it lies below one of ROOTS; Refused otherwise."""
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise Refused("Give an absolute path below /files, /code or /work.")
    real = Path(os.path.realpath(path))
    for root in ROOTS:
        base = os.path.realpath(root)
        if str(real) == base or str(real).startswith(base.rstrip("/") + "/"):
            if not real.is_file():
                raise Refused(f"No such file: {path}")
            return real
    raise Refused("Only files below /files, /code or /work can be opened.")


def image_type(head: bytes) -> str | None:
    for magic, kind in MAGIC:
        if head.startswith(magic):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def page_range(pages: str, count: int) -> tuple[int, int]:
    """(first, last) page, 1-based, at most MAX_PAGES long and inside the document. Refused for anything else."""
    pages = (pages or "").strip()
    if not pages:
        return 1, min(count, MAX_PAGES)
    match = re.fullmatch(r"(\d{1,5})(?:\s*-\s*(\d{1,5}))?", pages)
    if not match:
        raise Refused('pages must look like "3" or "5-8".')
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if first < 1 or last < first or first > count:
        raise Refused(f"The PDF has {count} pages.")
    return first, min(last, count, first + MAX_PAGES - 1)


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, timeout=SECONDS, stdin=subprocess.DEVNULL)


def page_count(path: Path) -> int:
    done = _run(["pdfinfo", "--", str(path)])
    match = re.search(rb"^Pages:\s+(\d+)", done.stdout, re.M)
    if done.returncode or not match:
        raise Refused("This PDF could not be opened (damaged or protected).")
    return int(match.group(1))


def look_pdf(path: Path, pages: str, images: bool) -> list[dict]:
    if path.stat().st_size > MAX_PDF:
        raise Refused("This PDF is too big to open here.")
    if shutil.which("pdftoppm") is None:
        raise Refused("PDFs can not be opened here (no PDF tools).")
    count = page_count(path)
    first, last = page_range(pages, count)
    text = _run(["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(first), "-l", str(last), "--", str(path), "-"])
    words = text.stdout.decode("utf-8", "replace").strip()
    if len(words) > MAX_TEXT:
        words = words[:MAX_TEXT] + "\n[text cut here]"
    more = f' Other pages: pages="{last + 1}-{min(count, last + MAX_PAGES)}".' if last < count else ""
    content = [{"type": "text", "text": f"PDF with {count} pages, pages {first} to {last}.{more}\n\n"
                                        f"Text of these pages:\n{words or '(no text: scanned pages, see the pictures)'}"}]
    if not images:
        return content + [{"type": "text", "text": "The model can not see pictures, so the pages come as text only."}]
    with tempfile.TemporaryDirectory() as folder:
        done = _run(["pdftoppm", "-jpeg", "-jpegopt", "quality=80", "-scale-to", str(SCALE), "-f", str(first),
                     "-l", str(last), "--", str(path), str(Path(folder) / "p")])
        shots = sorted(Path(folder).glob("p-*.jpg"), key=lambda p: int(re.search(r"(\d+)\.jpg$", p.name).group(1)))
        if done.returncode and not shots:
            raise Refused("The pages of this PDF could not be drawn.")
        for number, shot in zip(range(first, last + 1), shots):
            content.append({"type": "text", "text": f"Page {number}:"})
            content.append({"type": "image", "data": base64.b64encode(shot.read_bytes()).decode(),
                            "mimeType": "image/jpeg"})
    return content


def look(path: str, pages: str = "", images: bool = True) -> list[dict]:
    """The content of one call (MCP content items). Raises Refused with a text for the model."""
    real = _inside(path)
    with open(real, "rb") as handle:
        head = handle.read(16)
    kind = image_type(head)
    if kind:
        if not images:
            raise Refused("The model can not see pictures; this tool can not show it this image.")
        if real.stat().st_size > MAX_IMAGE:
            raise Refused("This image is too big to show (over 10 MB).")
        return [{"type": "image", "data": base64.b64encode(real.read_bytes()).decode(), "mimeType": kind}]
    if head.startswith(b"%PDF"):
        return look_pdf(real, pages, images)
    raise Refused("This tool shows images (PNG, JPEG, GIF, WebP) and PDFs. Read text files with your file tool; for a "
                  "TIFF, HEIC or raw photo open the .jpg next to it.")


def answer(message: dict, images: bool) -> dict | None:
    """The reply to one JSON-RPC message (None for a notification)."""
    number, method = message.get("id"), message.get("method")
    if number is None:
        return None
    if method == "initialize":
        version = (message.get("params") or {}).get("protocolVersion") or "2025-06-18"
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "hub-look", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = message.get("params") or {}
        args = params.get("arguments") or {}
        try:
            if params.get("name") != "look":
                raise Refused("Unknown tool.")
            result = {"content": look(args.get("path"), str(args.get("pages") or ""), images)}
        except Refused as reason:
            result = {"content": [{"type": "text", "text": str(reason)}], "isError": True}
        except (OSError, subprocess.SubprocessError):
            result = {"content": [{"type": "text", "text": "The file could not be opened."}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": number, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": number, "result": result}


def main() -> int:
    images = os.environ.get("HUB_IMAGES", "1") == "1"
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and (reply := answer(message, images)) is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
