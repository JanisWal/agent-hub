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

Memory folder (Janis, 14.11.2026): every project gets a fixed set of Markdown files in the area Memory once
(SKELETON: MEMORY.md, PROJEKT.md, ROADMAP.md, REGELN.md; English names for English users). The hub gives ALL
Markdown files of that area with every question (`folder`, within MAX_FOLDER), so any AI can go on from them: the
memory is files, not something of one provider. The manager updates any of them, or adds a new one, with
<memory file="NAME.md">...</memory>; a plain <memory> is MEMORY.md. A file the user deleted is not made again.

Archive (Janis, 15.11.2026): ARCHIVE.md is the history of the project: what once existed, what was dropped or changed,
and why (security, structure, modularity, ...), so a later "why did we change that?" has an answer. It is the one
file that only grows: what the manager writes into <memory file="ARCHIVE.md"> is added at its end under today's date
(`_append_archive`), nothing in it is ever replaced by the manager (the user can still edit it in the tile). It comes
last in the memory folder and, when it does not fit, its newest part is given.

Everything here belongs to one user and one project: each function gets the user and the project must be his,
and a name is only looked up among the files of that project. Standard library only.
"""
import re
import sqlite3
import time
from dataclasses import dataclass

from . import db, files

MEMORY_NAME = "MEMORY.md"
ARCHIVE_NAME = "ARCHIVE.md"   # the history of the project; only ever added to (see above)
MAX_ARCHIVE = 100_000       # characters ARCHIVE.md may grow to; beyond that new entries are refused
MAX_ARCHIVE_ENTRY = 4000    # characters of what one answer adds to it
MAX_MEMORY = 16000          # characters of the memory file that are read and kept
MAX_FILE_CHARS = 20000      # characters of one requested file that go to the manager
MAX_READ_BYTES = 400_000    # a larger file is not opened (it would only be cut)
MAX_REQUESTED = 60000       # characters of all requested files together
MAX_LIST = 60               # files named in the list at most
MAX_READS = 3               # files the manager may ask for in one answer
READ_ROUNDS = 2             # how often one question is answered again with requested files
READABLE = files.CODE | set("md txt csv tsv log json yaml yml toml ini cfg conf xml html css sql".split())

_MEMORY_TAG = re.compile(r"<memory(?:\s+file=\"([^\"<>]{1,80})\")?>(.*?)</memory>", re.DOTALL)
_MEMORY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.\-]{0,60}\.md")   # what the manager may name a memory file
MAX_FOLDER = 40000          # characters of the memory folder given with every question
MAX_NEW_FILES = 3           # memory files the manager may write in one answer
# The fixed memory files of a project, by language: name and the start of its text (headings to fill).
SKELETON = {
    "de": (
        ("MEMORY.md", "# Stand\n\n# Entscheidungen\n\n# Offene Fragen\n\n# Notizen\n"),
        ("PROJEKT.md", "# Ziel\n\n# Umfang\n\n# Aufbau\n\n## Hardware\n\n## Software\n\n# Entscheidungen und Gründe\n\n# Begriffe\n"),
        ("ROADMAP.md", "# Als Nächstes\n\n# Später\n\n# Ideen\n\n# Erledigt\n"),
        ("REGELN.md", "# Arbeitsweise\n\n# Vorgaben\n\n# Design\n\n# Nie tun\n"),
        ("ARCHIVE.md", "# Archiv\n\nWas es einmal gab, was verworfen oder geändert wurde, und warum. Neue Einträge kommen "
                       "unten dazu.\n"),
    ),
    "en": (
        ("MEMORY.md", "# Status\n\n# Decisions\n\n# Open questions\n\n# Notes\n"),
        ("PROJECT.md", "# Goal\n\n# Scope\n\n# Structure\n\n## Hardware\n\n## Software\n\n# Decisions and reasons\n\n# Terms\n"),
        ("ROADMAP.md", "# Next\n\n# Later\n\n# Ideas\n\n# Done\n"),
        ("RULES.md", "# How we work\n\n# Requirements\n\n# Design\n\n# Never do\n"),
        ("ARCHIVE.md", "# Archive\n\nWhat once existed, what was dropped or changed, and why. New entries are added at "
                       "the bottom.\n"),
    ),
}
# projects.memory_seeded holds the version of the skeleton a project got. A file added to the skeleton later names the
# version it came with, so older projects get just that file, once (and not again if the user deletes it).
SKELETON_VERSION = 2
SINCE = {"ARCHIVE.md": 2}
_READ_TAG = re.compile(r"<read>(.*?)</read>", re.DOTALL)


@dataclass
class Parsed:
    text: str                # the answer without the tags
    memory: str | None       # the new MEMORY.md, if the manager wrote one
    reads: list[str]         # names of the files it asks for
    files: dict | None = None   # other memory files it wrote: name -> text (memory folder)


def parse_answer(answer: str) -> Parsed:
    """Split an answer of the manager into what the user reads, a new memory file and requested file names."""
    memory, others = None, {}
    for name, body in _MEMORY_TAG.findall(answer):
        name, body = name.strip(), body.strip()
        if not name or name.lower() == MEMORY_NAME.lower():
            memory = body or None
        elif _MEMORY_NAME.fullmatch(name) and body and (name in others or len(others) < MAX_NEW_FILES):
            others[name] = body
    reads: list[str] = []
    for name in _READ_TAG.findall(answer):
        name = name.strip()
        if name and name.lower() not in [r.lower() for r in reads]:
            reads.append(name)
    text = _READ_TAG.sub("", _MEMORY_TAG.sub("", answer)).strip()
    return Parsed(text, memory or None, reads[:MAX_READS], others)


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


def _text_of(row: sqlite3.Row, limit: int, tail: bool = False) -> str | None:
    """The text of a stored file, cut to `limit` characters (its end with tail=True); None if it is not a readable
    text file."""
    if _extension(row["name"]) not in READABLE or row["size"] > MAX_READ_BYTES:
        return None
    path = files.path_of(row["project_id"], row["id"])
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return "… " + text[-limit:].lstrip() if tail else text[:limit].rstrip() + " …"


def read_memory(conn: sqlite3.Connection, user_id: int, project_id: int) -> str | None:
    """The memory file of the project (cut to MAX_MEMORY), or None if there is none yet."""
    row = _find(conn, user_id, project_id, MEMORY_NAME)
    return None if row is None else _text_of(row, MAX_MEMORY) or ""


def save_memory(user_id: int, project_id: int, text: str, name: str = MEMORY_NAME) -> bool:
    """Keep what the manager wrote as a memory file: replaces the file of that name or makes it (in the area Memory).
    Longer than MAX_MEMORY it is cut at a line end. False if it could not be saved (a name that is not allowed, not
    the user's project, disk nearly full)."""
    text = text.strip()
    if not text or not _MEMORY_NAME.fullmatch(name):
        return False
    if name.lower() == ARCHIVE_NAME.lower():
        return _append_archive(user_id, project_id, text)
    if len(text) > MAX_MEMORY:
        text = text[:MAX_MEMORY].rsplit("\n", 1)[0]
    with db.connect() as conn:
        row = _find(conn, user_id, project_id, name)
    try:
        if row is not None:
            if files.write_text(user_id, row["id"], text + "\n"):
                return True
            files.delete(user_id, row["id"])          # a row whose file is gone: make the memory file anew
            files.purge(user_id, row["id"])
        files.create_text_file(user_id, project_id, name, text + "\n")
        return True
    except files.FileError:
        return False


def _append_archive(user_id: int, project_id: int, text: str, today: str | None = None) -> bool:
    """Add an entry at the end of ARCHIVE.md under today's date (make the file if there is none). Nothing in it is
    replaced. False if not saved: not the user's project, the file would grow beyond MAX_ARCHIVE, disk nearly full."""
    if len(text) > MAX_ARCHIVE_ENTRY:
        text = text[:MAX_ARCHIVE_ENTRY].rsplit("\n", 1)[0]
    entry = f"## {today or time.strftime('%Y-%m-%d')}\n{text}\n"
    with db.connect() as conn:
        row = _find(conn, user_id, project_id, ARCHIVE_NAME)
    try:
        if row is not None:
            old = files.read_text(user_id, row["id"])
            if old is not None:
                new = old.rstrip() + "\n\n" + entry
                return len(new) <= MAX_ARCHIVE and files.write_text(user_id, row["id"], new)
            files.delete(user_id, row["id"])              # a row whose file is gone: make it anew
            files.purge(user_id, row["id"])
        files.create_text_file(user_id, project_id, ARCHIVE_NAME, entry)
        return True
    except files.FileError:
        return False


def _folder_rows(conn: sqlite3.Connection, user_id: int, project_id: int) -> list[sqlite3.Row]:
    """The Markdown files of the area Memory: MEMORY.md first, ARCHIVE.md last, the others by name between."""
    rows = conn.execute(
        "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id WHERE f.project_id = ? AND p.user_id = ?"
        " AND f.status = 'ready' AND f.url IS NULL AND f.category = 'memory' AND lower(f.name) LIKE '%.md'",
        (project_id, user_id)).fetchall()
    def order(r) -> tuple:
        name = r["name"].lower()
        return (0 if name == MEMORY_NAME.lower() else 2 if name == ARCHIVE_NAME.lower() else 1, name)
    return sorted(rows, key=order)


def folder(conn: sqlite3.Connection, user_id: int, project_id: int) -> str:
    """The memory folder for the manager: every Markdown file of the area Memory as a <file> block, MEMORY.md first,
    together at most MAX_FOLDER characters (what does not fit is named, to be asked for with <read>)."""
    blocks, used = [], 0
    for row in _folder_rows(conn, user_id, project_id):
        shown = row["name"].replace('"', "'")
        archive = row["name"].lower() == ARCHIVE_NAME.lower()       # its newest part matters most
        text = _text_of(row, min(MAX_MEMORY, max(0, MAX_FOLDER - used)), tail=archive)
        if text is None or (used >= MAX_FOLDER):
            blocks.append(f'<file name="{shown}">(too long to give here: ask for it with <read>)</file>')
            continue
        used += len(text)
        blocks.append(f'<file name="{shown}">\n{text.strip() or "(empty)"}\n</file>')
    return "\n\n".join(blocks)


def ensure_skeleton(user_id: int, project_id: int, lang: str = "de") -> int:
    """Make the fixed memory files of a project, once per version of the skeleton (projects.memory_seeded): a new
    project gets all of them, an older one only those added since (SINCE). A file that exists stays as it is, and one
    the user deletes later is not made again. Returns how many were made; 0 if not his project or up to date."""
    with db.connect() as conn:
        row = conn.execute("SELECT memory_seeded FROM projects WHERE id = ? AND user_id = ?",
                           (project_id, user_id)).fetchone()
        if row is None or row["memory_seeded"] >= SKELETON_VERSION:
            return 0
        seeded = row["memory_seeded"]
        conn.execute("UPDATE projects SET memory_seeded = ? WHERE id = ?", (SKELETON_VERSION, project_id))
        have = {r["name"].lower() for r in _folder_rows(conn, user_id, project_id)}
    made = 0
    for name, text in SKELETON.get(lang, SKELETON["de"]):
        if SINCE.get(name, 1) <= seeded or name.lower() in have:
            continue
        try:
            files.create_text_file(user_id, project_id, name, text)
            made += 1
        except files.FileError:
            pass
    return made


def listing(conn: sqlite3.Connection, user_id: int, project_id: int) -> str:
    """The other files and links of the project for the manager (not the memory folder), newest first, one per line."""
    rows = conn.execute(
        "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
        " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready'"
        " AND NOT (f.url IS NULL AND f.category = 'memory' AND lower(f.name) LIKE '%.md')"
        " ORDER BY f.id DESC LIMIT ?",
        (project_id, user_id, MAX_LIST),
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
