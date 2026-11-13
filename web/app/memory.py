"""The manager's memory and files (Janis, 13.11.2026; Phase 2 of the file storage, see files.py).

Memory: the project has one memory file, `MEMORY.md` in the area Memory of the file storage. The hub puts it in
front of every question of the manager chat (chat.build_input), so the manager always knows the current state.
When the manager has finished some work it ends its answer with the complete new memory inside <memory> tags;
the hub saves that as MEMORY.md (the manager itself never writes anywhere) and strips it from the answer. The
file is an ordinary file: Janis can read and edit it in the tile. It is plain Markdown with fixed headings
(Status, Decisions, Open questions, Notes) and not tied to Claude, so any other AI could use it as it is.

Other files: the manager gets a list (name, area, size) and opens a file only when the question needs it, by
ending its answer with <read>file name</read> (up to MAX_READS names). The hub then sends the contents of text
files with the same question again (at most READ_ROUNDS times, chat.finish). PDFs, images and other files that
are not text can not be opened this way. Links in the list are sources the manager can open with its web tools.

Everything here belongs to one user and one project: each function gets the user and the project must be his,
and a name is only looked up among the files of that project. Standard library only.
"""
import re
import sqlite3
from dataclasses import dataclass

from . import db, files

MEMORY_NAME = "MEMORY.md"
MAX_MEMORY = 16000          # characters of the memory file that are read and kept
MAX_FILE_CHARS = 20000      # characters of one requested file that go to the manager
MAX_READ_BYTES = 400_000    # a larger file is not opened (it would only be cut)
MAX_REQUESTED = 60000       # characters of all requested files together
MAX_LIST = 60               # files named in the list at most
MAX_READS = 3               # files the manager may ask for in one answer
READ_ROUNDS = 2             # how often one question is answered again with requested files
READABLE = files.CODE | set("md txt csv tsv log json yaml yml toml ini cfg conf xml html css sql".split())

_MEMORY_TAG = re.compile(r"<memory>(.*?)</memory>", re.DOTALL)
_READ_TAG = re.compile(r"<read>(.*?)</read>", re.DOTALL)


@dataclass
class Parsed:
    text: str                # the answer without the tags
    memory: str | None       # the new memory file, if the manager wrote one
    reads: list[str]         # names of the files it asks for


def parse_answer(answer: str) -> Parsed:
    """Split an answer of the manager into what the user reads, a new memory file and requested file names."""
    found = _MEMORY_TAG.findall(answer)
    memory = found[-1].strip() if found else None
    reads: list[str] = []
    for name in _READ_TAG.findall(answer):
        name = name.strip()
        if name and name.lower() not in [r.lower() for r in reads]:
            reads.append(name)
    text = _READ_TAG.sub("", _MEMORY_TAG.sub("", answer)).strip()
    return Parsed(text, memory or None, reads[:MAX_READS])


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _find(conn: sqlite3.Connection, user_id: int, project_id: int, name: str) -> sqlite3.Row | None:
    """A finished file (not a link) of this project, by its name (capital letters do not matter); the oldest if
    there are several. Only the user's own projects are searched."""
    return conn.execute(
        "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
        " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready' AND f.url IS NULL"
        " AND f.name = ? COLLATE NOCASE ORDER BY f.id LIMIT 1",
        (project_id, user_id, name),
    ).fetchone()


def _text_of(row: sqlite3.Row, limit: int) -> str | None:
    """The text of a stored file, cut to `limit` characters; None if it is not a readable text file."""
    if _extension(row["name"]) not in READABLE or row["size"] > MAX_READ_BYTES:
        return None
    path = files.path_of(row["project_id"], row["id"])
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def read_memory(conn: sqlite3.Connection, user_id: int, project_id: int) -> str | None:
    """The memory file of the project (cut to MAX_MEMORY), or None if there is none yet."""
    row = _find(conn, user_id, project_id, MEMORY_NAME)
    return None if row is None else _text_of(row, MAX_MEMORY) or ""


def save_memory(user_id: int, project_id: int, text: str) -> bool:
    """Keep what the manager wrote as the memory file: replaces MEMORY.md or makes it. Longer than MAX_MEMORY
    it is cut at a line end. False if it could not be saved (not the user's project, disk nearly full)."""
    text = text.strip()
    if not text:
        return False
    if len(text) > MAX_MEMORY:
        text = text[:MAX_MEMORY].rsplit("\n", 1)[0]
    with db.connect() as conn:
        row = _find(conn, user_id, project_id, MEMORY_NAME)
    try:
        if row is not None:
            return files.write_text(user_id, row["id"], text + "\n")
        files.create_text_file(user_id, project_id, MEMORY_NAME, text + "\n")
        return True
    except files.FileError:
        return False


def listing(conn: sqlite3.Connection, user_id: int, project_id: int) -> str:
    """The other files and links of the project for the manager, newest first, one per line."""
    rows = conn.execute(
        "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
        " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready' AND NOT (f.url IS NULL AND f.name = ? COLLATE NOCASE)"
        " ORDER BY f.id DESC LIMIT ?",
        (project_id, user_id, MEMORY_NAME, MAX_LIST),
    ).fetchall()
    lines = []
    for row in rows:
        if row["url"] is not None:
            lines.append(f"- {row['name']}: {row['url']} (link, a source)")
        else:
            readable = _extension(row["name"]) in READABLE and row["size"] <= MAX_READ_BYTES
            lines.append(f"- {row['name']} ({row['category']}, {row['size']} bytes"
                         f"{'' if readable else ', not text: you can not open it'})")
    return "\n".join(lines)


def contents(conn: sqlite3.Connection, user_id: int, project_id: int, names: list[str]) -> str:
    """The files the manager asked for, as <file name="..."> blocks; a name that is not a file of this project
    (or not readable text) says so. Together at most MAX_REQUESTED characters."""
    blocks, used = [], 0
    for name in names[:MAX_READS]:
        row = _find(conn, user_id, project_id, name)
        text = None if row is None else _text_of(row, min(MAX_FILE_CHARS, MAX_REQUESTED - used))
        if row is None:
            body = "(there is no such file in this project)"
        elif text is None:
            body = "(this file is not text or too large to open here)"
        else:
            body, used = text, used + len(text)
        shown = name.replace('"', "'")
        blocks.append(f'<file name="{shown}">\n{body}\n</file>')
    return "\n\n".join(blocks)
