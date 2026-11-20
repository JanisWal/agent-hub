"""The hub's own tools for an AI whose program lacks some (Janis, 20.11.2026: every AI must be usable; one that brings
tools uses its own, one without gets these, maybe weaker, but never nothing). Standard library only; runs inside the run's
container, never on the server itself.

Two ways in:
- as an MCP server on stdio (`main`): a program that speaks MCP (Mistral Vibe, runner/vibe_entry.py) gets the tools named
  in HUB_TOOLS (comma separated; default "look");
- as plain functions (`call`, `schemas`) for runner/hubloop.py, the loop for an AI that only has an API.

The tools (TOOLS): look (images and PDFs, see below), list_files, read_file, grep, write_file, edit_file, run (a shell
command in /work, or /tmp without a work folder) and fetch (a public web page through the egress proxy of the job).
Paths only below ROOTS, after following links; writing only below /work. Whatever a tool returns is information for the
AI, never instructions.

look(path, pages=""): an image (PNG, JPEG, GIF, WebP; the type from its first bytes, never from the name) comes back as
a picture; a PDF as its text (pdftotext) and its pages as pictures (pdftoppm, at most MAX_PAGES per call; `pages` picks
others, "3" or "5-8"). HUB_IMAGES=0 (a model that can not see pictures): PDFs give their text, images only a note.
"""
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOTS = ("/files", "/code", "/work")
WRITE_ROOT = "/work"
MAX_READ = 60000                # characters of a text file per call
MAX_LIST = 400                  # entries of a listing
MAX_GREP = 200                  # matching lines of a search
MAX_RUN = 20000                 # characters of a command's output (its end)
RUN_SECONDS = 120
MAX_FETCH = 400_000             # bytes of a web page that are read
MAX_WRITE = 2_000_000           # characters one write may put into a file
MAX_IMAGE = 10 * 1024 ** 2      # Mistral's limit for one image
MAX_PDF = 100 * 1024 ** 2
MAX_PAGES = 8                   # pictures of PDF pages per call
MAX_TEXT = 30000                # characters of PDF text per call
SECONDS = 90
SCALE = 1400                    # longest side of a page picture in pixels: readable, a few hundred KB
MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
         (b"GIF89a", "image/gif"))
LOOK = {
    "name": "look",
    "description": ("Look at an image (PNG, JPEG, GIF, WebP) or a PDF of the project: the picture itself, or the PDF's "
                    "text and its pages as pictures. path: absolute path below /files, /code or /work. pages (PDF "
                    f"only, optional): \"3\" or \"5-8\", at most {MAX_PAGES} pages per call; without it the first pages."),
    "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "pages": {"type": "string"}},
                    "required": ["path"]},
}


def _schema(name: str, description: str, props: dict, required: tuple = ()) -> dict:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": {k: {"type": v} for k, v in props.items()},
                            "required": list(required)}}


SCHEMAS = {
    "look": LOOK,
    "list_files": _schema("list_files", "List the files and folders below a folder (/files, /code or /work), with sizes.",
                          {"path": "string"}, ("path",)),
    "read_file": _schema("read_file", f"Read a text file below /files, /code or /work (at most {MAX_READ} characters "
                                      "from `offset`).", {"path": "string", "offset": "integer"}, ("path",)),
    "grep": _schema("grep", "Search the text files below a folder for a regular expression; matching lines with file "
                            "and line number.", {"pattern": "string", "path": "string"}, ("pattern",)),
    "write_file": _schema("write_file", "Write a whole text file below /work (made or replaced).",
                          {"path": "string", "text": "string"}, ("path", "text")),
    "edit_file": _schema("edit_file", "Replace the text `old` (it must occur exactly once) with `new` in a file below "
                                      "/work.", {"path": "string", "old": "string", "new": "string"}, ("path", "old", "new")),
    "run": _schema("run", f"Run a shell command in /work (at most {RUN_SECONDS} s); its exit code and the end of its "
                          "output come back.", {"command": "string"}, ("command",)),
    "fetch": _schema("fetch", "Read a public web page (http or https) as text.", {"url": "string"}, ("url",)),
}
TOOLS = tuple(SCHEMAS)


class Refused(Exception):
    pass


def _inside(path: str, kind: str = "file", roots: tuple = ()) -> Path:
    """The real path, if it lies below one of `roots` (ROOTS by default): an existing file ("file"), an existing folder
    ("folder") or a file that may not exist yet ("new"). Refused otherwise."""
    roots = roots or ROOTS
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise Refused("Give an absolute path below " + ", ".join(roots) + ".")
    real = Path(os.path.realpath(path))
    for root in roots:
        base = os.path.realpath(root)
        if str(real) == base or str(real).startswith(base.rstrip("/") + "/"):
            if kind == "file" and not real.is_file():
                raise Refused(f"No such file: {path}")
            if kind == "folder" and not real.is_dir():
                raise Refused(f"No such folder: {path}")
            return real
    raise Refused("Only paths below " + ", ".join(roots) + " can be used.")


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


def _text(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def list_files(path: str) -> list[dict]:
    folder = _inside(path, "folder")
    lines = []
    for item in sorted(folder.rglob("*")):
        if len(lines) >= MAX_LIST:
            lines.append(f"... more than {MAX_LIST} entries: list a sub-folder")
            break
        if any(part.startswith(".git") for part in item.relative_to(folder).parts):
            continue
        shown = item.relative_to(folder)
        lines.append(f"{shown}/" if item.is_dir() else f"{shown} ({item.stat().st_size} bytes)")
    return _text("\n".join(lines) or "(empty)")


def read_file(path: str, offset: int = 0) -> list[dict]:
    real = _inside(path)
    with open(real, "rb") as handle:
        head = handle.read(4096)
    if b"\x00" in head or head.startswith(b"%PDF") or image_type(head):
        raise Refused("This is not a text file" + (": open it with look." if "look" in _enabled() else "."))
    text = real.read_text(encoding="utf-8", errors="replace")
    start = max(0, int(offset or 0))
    part = text[start:start + MAX_READ]
    more = (f"\n[{len(text) - start - len(part)} more characters: read on with offset={start + len(part)}]"
            if start + len(part) < len(text) else "")
    return _text(part + more)


def grep(pattern: str, path: str = "/work") -> list[dict]:
    try:
        expression = re.compile(pattern)
    except (re.error, TypeError):
        raise Refused("Not a valid regular expression.") from None
    folder = _inside(path or "/work", "folder")
    found = []
    for item in sorted(folder.rglob("*")):
        if len(found) >= MAX_GREP or not item.is_file() or ".git" in item.parts or item.stat().st_size > 2_000_000:
            continue
        try:
            for number, line in enumerate(item.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
                if expression.search(line):
                    found.append(f"{item}:{number}: {line[:300]}")
                    if len(found) >= MAX_GREP:
                        break
        except (UnicodeDecodeError, OSError):
            continue
    return _text("\n".join(found) or "(no match)")


def write_file(path: str, text: str) -> list[dict]:
    if not isinstance(text, str) or len(text) > MAX_WRITE:
        raise Refused("Give the text of the file (not too long).")
    real = _inside(path, "new", (WRITE_ROOT,))
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text(text, encoding="utf-8")
    return _text(f"Wrote {path} ({len(text)} characters).")


def edit_file(path: str, old: str, new: str) -> list[dict]:
    real = _inside(path, "file", (WRITE_ROOT,))
    text = real.read_text(encoding="utf-8", errors="replace")
    count = text.count(old) if isinstance(old, str) and old else 0
    if count != 1:
        raise Refused("`old` is not in the file." if count == 0 else f"`old` occurs {count} times: take a longer piece.")
    real.write_text(text.replace(old, new if isinstance(new, str) else "", 1), encoding="utf-8")
    return _text(f"Changed {path}.")


def run(command: str) -> list[dict]:
    if not isinstance(command, str) or not command.strip():
        raise Refused("Give a command.")
    where = WRITE_ROOT if os.path.isdir(WRITE_ROOT) else tempfile.gettempdir()
    try:
        done = subprocess.run(["sh", "-c", command], cwd=where, capture_output=True, text=True, timeout=RUN_SECONDS,
                              stdin=subprocess.DEVNULL)
        output, code = (done.stdout or "") + (done.stderr or ""), done.returncode
    except subprocess.TimeoutExpired:
        output, code = f"(stopped after {RUN_SECONDS} s)", 124
    return _text(f"exit code {code}\n{output[-MAX_RUN:]}")


_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def fetch(url: str) -> list[dict]:
    """A web page as text, through the job's proxy (HTTPS_PROXY: public hosts only, never the home network)."""
    if not isinstance(url, str) or not re.match(r"https?://", url):
        raise Refused("Give an http or https address.")
    if not os.environ.get("HTTPS_PROXY") and not os.environ.get("https_proxy"):
        raise Refused("This job has no web access.")
    request = urllib.request.Request(url, headers={"User-Agent": "agent-hub-fetch/1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer_:
            body = answer_.read(MAX_FETCH).decode(answer_.headers.get_content_charset() or "utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise Refused(f"The page could not be read ({type(error).__name__}).") from None
    text = html.unescape(_TAGS.sub(" ", body))
    return _text(re.sub(r"[ \t]*\n\s*\n\s*", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()[:MAX_READ])


def _enabled(names=None) -> tuple[str, ...]:
    """The tools of this job, in the order of TOOLS: `names`, else HUB_TOOLS (comma separated; "look" when unset)."""
    named = set(names) if names is not None else {t.strip() for t in os.environ.get("HUB_TOOLS", "look").split(",")}
    return tuple(t for t in TOOLS if t in named)


def call(name: str, args: dict, images: bool = True, enabled=None) -> list[dict]:
    """One tool call: content items (text, image). Raises Refused with a text for the model."""
    if name not in _enabled(enabled):
        raise Refused("Unknown tool.")
    args = args if isinstance(args, dict) else {}
    if name == "look":
        return look(args.get("path"), str(args.get("pages") or ""), images)
    if name == "list_files":
        return list_files(args.get("path") or "/work")
    if name == "read_file":
        return read_file(args.get("path"), args.get("offset") or 0)
    if name == "grep":
        return grep(args.get("pattern"), args.get("path") or "/work")
    if name == "write_file":
        return write_file(args.get("path"), args.get("text"))
    if name == "edit_file":
        return edit_file(args.get("path"), args.get("old"), args.get("new"))
    if name == "run":
        return run(args.get("command"))
    return fetch(args.get("url"))


def schemas(enabled=None) -> list[dict]:
    return [SCHEMAS[t] for t in _enabled(enabled)]


def answer(message: dict, images: bool) -> dict | None:
    """The reply to one JSON-RPC message (None for a notification)."""
    number, method = message.get("id"), message.get("method")
    if number is None:
        return None
    if method == "initialize":
        version = (message.get("params") or {}).get("protocolVersion") or "2025-06-18"
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "hub-tools", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": schemas()}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            result = {"content": call(params.get("name"), params.get("arguments") or {}, images)}
        except Refused as reason:
            result = {"content": [{"type": "text", "text": str(reason)}], "isError": True}
        except (OSError, ValueError, subprocess.SubprocessError):
            result = {"content": [{"type": "text", "text": "The tool could not do it."}], "isError": True}
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
