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

Targeted edits (Janis, 16.11.2026; by section since 20.11.2026): instead of the whole new text the manager changes a
memory file with <memory-edit file="NAME.md"><section title="HEADING">new text</section><append>text</append>
</memory-edit>. A section is a heading and everything up to the next heading of the same or a higher level; a heading
that is not there yet is added at the end. A block is applied whole or not at all. Weaker models could not copy the
old text exactly for the earlier <find>/<replace>; a heading they copy easily. ARCHIVE.md is not edited (it only
grows). `check_edits` says what would fail, `apply_edits` does it.

In a package (`inline`, 20.11.2026) MEMORY.md always comes whole; the other memory files only while MAX_INLINE lasts
and ARCHIVE.md never (only named): an AI with tools opens them in /files, one without asks with <read>.

Versions (Janis, 16.11.2026): before a memory file is replaced (by the manager or by the user in the tile), its old
text goes into `memory_versions` (at most MAX_VERSIONS per file). The user sees and restores them in the archive of
the Manager view; the AIs never read them.

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
MAX_INLINE = 8000           # characters of memory files given with a package besides MEMORY.md (`inline`)
MEMORY_FILES = ("MEMORY.md", "PROJECT.md", "ROADMAP.md", "RULES.md", "ARCHIVE.md")   # the fixed ones (SKELETON)
RULES_NAME = "RULES.md"
MAX_NEW_FILES = 3           # memory files the manager may write in one answer
MAX_EDIT_BLOCKS = 3         # <memory-edit> blocks taken from one answer
MAX_EDIT_CHANGES = 10       # <find>/<replace> pairs and <append> parts in one block
MAX_VERSIONS = 20           # earlier versions kept per memory file
VERSIONS_SHOWN = 200        # versions the archive lists at most (newest)
_EDIT_TAG = re.compile(r"<memory-edit\s+file=\"([^\"<>]{1,80})\">(.*?)</memory-edit>", re.DOTALL)
_CHANGE_TAG = re.compile(r"<section\s+title=\"([^\"<>]{1,120})\">(.*?)</section>|<append>(.*?)</append>", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
# The fixed memory files of a project, by language: name and the start of its text (headings to fill).
SKELETON = {
    "de": (
        ("MEMORY.md", "# Stand\n\n# Entscheidungen\n\n# Offene Fragen\n\n# Notizen\n"),
        ("PROJECT.md", "# Ziel\n\n# Umfang\n\n# Aufbau\n\n## Hardware\n\n## Software\n\n# Entscheidungen und Gründe\n\n# Begriffe\n"),
        ("ROADMAP.md", "# Als Nächstes\n\n# Später\n\n# Ideen\n\n# Erledigt\n"),
        ("RULES.md", "# Arbeitsweise\n\n# Vorgaben\n\n# Design\n\n# Nie tun\n"),
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
_LEADING_DATE = re.compile(r"\A(?:\s*#{1,6}[ \t]*\d{4}-\d{2}-\d{2}[ \t]*(?:\n|\Z))+")   # date headings at the start


@dataclass
class Parsed:
    text: str                # the answer without the tags
    memory: str | None       # the new MEMORY.md, if the manager wrote one
    reads: list[str]         # names of the files it asks for
    files: dict | None = None   # other memory files it wrote: name -> text (memory folder)
    edits: list | None = None   # targeted changes: list of Edit


@dataclass
class Edit:
    file: str
    changes: list            # (heading, new text) pairs; heading None = append the text at the end


@dataclass
class EditResult:
    file: str
    ok: bool
    reason: str = ""         # not_found, not_unique, not_shown, too_long, bad_name, archive, empty


@dataclass
class Version:
    id: int
    name: str
    author: str              # who replaced it: manager or user
    size: int
    created_at: int


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
    edits = []
    for name, body in _EDIT_TAG.findall(answer)[:MAX_EDIT_BLOCKS]:
        changes = [(None, _edge(add)) if title == "" and add else (title.strip(), _edge(text))
                   for title, text, add in _CHANGE_TAG.findall(body)]
        edits.append(Edit(name.strip(), changes))
    text = _READ_TAG.sub("", _MEMORY_TAG.sub("", _EDIT_TAG.sub("", answer))).strip()
    return Parsed(text, memory or None, reads[:MAX_READS], others, edits)


def _edge(text: str) -> str:
    """The text between two tags without the line breaks right inside them (<find>\nold\n</find> means "old")."""
    return text.strip("\r\n")


def _find(conn: sqlite3.Connection, user_id: int, project_id: int, name: str,
          memory_only: bool = True) -> sqlite3.Row | None:
    """A finished file (not a link) of this project, by its name (capital letters do not matter); the oldest if
    there are several. Only the user's own projects are searched. `memory_only`: only the area Memory, the one the
    manager may write to (Janis, 16.11.2026: a manual of the same name in another area stays untouched); a file the
    manager asked for with <read> may come from any area."""
    area = " AND f.category = 'memory' AND f.parent_id IS NULL" if memory_only else ""   # the memory: top of Memory
    return conn.execute(
        "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
        " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready' AND f.url IS NULL AND f.is_folder = 0"
        f" AND f.name = ? COLLATE NOCASE{area} ORDER BY f.id LIMIT 1",
        (project_id, user_id, name),
    ).fetchone()


def _text_of(row: sqlite3.Row, limit: int, tail: bool = False) -> str | None:
    """The text of a stored file, cut to `limit` characters (its end with tail=True); None if it is not a readable
    text file."""
    if files.extension(row["name"]) not in READABLE or row["size"] > MAX_READ_BYTES:
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


def excerpt(conn: sqlite3.Connection, user_id: int, project_id: int, name: str, limit: int,
            tail: bool = False) -> str | None:
    """Start (or end, `tail`) of a memory file of the user's project, cut to `limit`; None if there is none."""
    row = _find(conn, user_id, project_id, name)
    return None if row is None else _text_of(row, limit, tail)


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
    return _write(user_id, project_id, name, text + "\n", "manager")


def _write(user_id: int, project_id: int, name: str, text: str, author: str) -> bool:
    """Replace a memory file (keeping its old text as a version) or make it in the area Memory."""
    with db.connect() as conn:
        row = _find(conn, user_id, project_id, name)
    try:
        if row is not None:
            old = files.read_text(user_id, row["id"])
            if old is not None:
                if old != text:
                    _keep_version(project_id, row["name"], old, author)
                return files.write_text(user_id, row["id"], text)
            files.delete(user_id, row["id"])          # a row whose file is gone: make the memory file anew
            files.purge(user_id, row["id"])
        files.create_text_file(user_id, project_id, name, text)
        return True
    except files.FileError:
        return False


def _keep_version(project_id: int, name: str, text: str, author: str, now: int | None = None) -> None:
    """Keep an old text; only the newest MAX_VERSIONS of a file stay. The caller checked the project."""
    if not text.strip():
        return
    with db.connect() as conn:
        conn.execute("INSERT INTO memory_versions (project_id, name, text, author, created_at) VALUES (?, ?, ?, ?, ?)",
                     (project_id, name, text, author, int(now if now is not None else time.time())))
        conn.execute(
            "DELETE FROM memory_versions WHERE project_id = ? AND name = ? COLLATE NOCASE AND id NOT IN (SELECT id FROM"
            " memory_versions WHERE project_id = ? AND name = ? COLLATE NOCASE ORDER BY id DESC LIMIT ?)",
            (project_id, name, project_id, name, MAX_VERSIONS))


def _key(title: str) -> str:
    return " ".join(title.replace("#", " ").split()).casefold()


def _section(text: str, title: str, body: str) -> tuple[str | None, str]:
    """Replace the section under the heading `title` (up to the next heading of the same or a higher level) with
    `body`; a missing heading is added at the end, at the level of the file's first heading. (None, reason) when the
    heading stands there more than once."""
    lines = text.split("\n")
    found = [(i, len(m.group(1))) for i, m in ((i, _HEADING.match(line)) for i, line in enumerate(lines))
             if m and _key(m.group(2)) == _key(title)]
    body = body.strip("\n")
    first = body.split("\n", 1)[0]
    heading = _HEADING.match(first)
    if heading and _key(heading.group(2)) == _key(title):   # the AI repeated the heading: it is kept once
        body = body.split("\n", 1)[1].strip("\n") if "\n" in body else ""
    if len(found) > 1:
        return None, "not_unique"
    if not found:
        levels = [len(m.group(1)) for m in map(_HEADING.match, lines) if m]
        mark = "#" * (levels[0] if levels else 1)
        return text.rstrip("\n") + f"\n\n{mark} {title.strip()}\n" + (body + "\n" if body else ""), ""
    start, level = found[0]
    end = next((i for i in range(start + 1, len(lines))
                if (m := _HEADING.match(lines[i])) and len(m.group(1)) <= level), len(lines))
    rest = lines[end:]
    new = lines[:start + 1] + ([body, ""] if body else [""]) + rest
    return "\n".join(new).rstrip("\n") + "\n", ""


def _edited(old: str, changes: list) -> tuple[str | None, str]:
    """(new text, "") or (None, reason) for one block: sections replaced and parts appended, in order."""
    if not changes or len(changes) > MAX_EDIT_CHANGES:
        return None, "empty" if not changes else "too_long"
    text = old
    for title, body in changes:
        if title is None:
            text = text.rstrip("\n") + "\n\n" + body.strip("\n") + "\n"
            continue
        if not title.strip():
            return None, "empty"
        text, reason = _section(text, title, body)
        if text is None:
            return None, reason
    return (text, "") if len(text) <= MAX_MEMORY else (None, "too_long")


def _plan(user_id: int, project_id: int, edits: list) -> list[tuple[EditResult, str | None, str]]:
    """For each block: its result, the new text (or None) and the file's real name."""
    with db.connect() as conn:
        plans = []
        for edit in edits:
            name = edit.file
            if not _MEMORY_NAME.fullmatch(name):
                plans.append((EditResult(name, False, "bad_name"), None, name))
                continue
            if name.lower() == ARCHIVE_NAME.lower():
                plans.append((EditResult(name, False, "archive"), None, name))
                continue
            row = _find(conn, user_id, project_id, name)
            if row is None:
                plans.append((EditResult(name, False, "not_found"), None, name))
                continue
            old = files.read_text(user_id, row["id"]) or ""
            new, reason = _edited(old, edit.changes)
            plans.append((EditResult(name, new is not None, reason), new, row["name"]))
    return plans


def check_edits(user_id: int, project_id: int, edits: list) -> list[EditResult]:
    """What applying the edits would give, without changing anything."""
    return [result for result, _, _ in _plan(user_id, project_id, edits)]


def apply_edits(user_id: int, project_id: int, edits: list, author: str = "manager") -> list[EditResult]:
    """Apply each block that fits (whole or not at all); the old text of a changed file becomes a version."""
    results = []
    for result, new, name in _plan(user_id, project_id, edits):
        if result.ok and not _write(user_id, project_id, name, new, author):
            result = EditResult(result.file, False, "not_saved")
        results.append(result)
    return results


def edit_failures(results: list[EditResult]) -> str:
    """The failed edits for the AI (another round in the chat, or the run's report), in English."""
    why = {"not_found": "there is no memory file of that name (make it with <memory file=...>)",
           "not_unique": "that heading stands more than once in the file (write the whole file instead)",
           "too_long": "the file would get too long, or too many changes",
           "archive": "ARCHIVE.md only grows: use <memory file=\"ARCHIVE.md\">", "bad_name": "not a memory file name",
           "empty": "no <section> or <append> in it", "not_saved": "the file could not be saved"}
    return "\n".join(f'<edit-failed file="{r.file.replace(chr(34), chr(39))}">{why.get(r.reason, r.reason)}'
                     f'</edit-failed>' for r in results if not r.ok)


def write_by_user(user_id: int, file_id: int, text: str) -> bool:
    """The user saves a file in the tile: a memory file keeps its old text as a version first. Raises FileError."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id WHERE f.id = ? AND p.user_id = ?"
            " AND f.status = 'ready' AND f.category = 'memory' AND f.is_folder = 0", (file_id, user_id)).fetchone()
    if row is not None and _MEMORY_NAME.fullmatch(row["name"]):
        old = files.read_text(user_id, file_id)
        if old is not None and old != text:
            _keep_version(row["project_id"], row["name"], old, "user")
    return files.write_text(user_id, file_id, text)


def versions(user_id: int, project_id: int) -> list[Version]:
    """The earlier versions of the project's memory files, newest first; empty for a foreign project."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT v.id, v.name, v.author, length(v.text) AS size, v.created_at FROM memory_versions v"
            " JOIN projects p ON p.id = v.project_id WHERE v.project_id = ? AND p.user_id = ?"
            " ORDER BY v.id DESC LIMIT ?", (project_id, user_id, VERSIONS_SHOWN)).fetchall()
    return [Version(r["id"], r["name"], r["author"], r["size"], r["created_at"]) for r in rows]


def version_text(user_id: int, version_id: int) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT v.text FROM memory_versions v JOIN projects p ON p.id = v.project_id"
                           " WHERE v.id = ? AND p.user_id = ?", (version_id, user_id)).fetchone()
    return None if row is None else row["text"]


def restore(user_id: int, version_id: int) -> int | None:
    """Put an earlier version back; the current text becomes a version itself (nothing is lost). The project id, or
    None if the version is not the user's or could not be saved."""
    with db.connect() as conn:
        row = conn.execute("SELECT v.* FROM memory_versions v JOIN projects p ON p.id = v.project_id"
                           " WHERE v.id = ? AND p.user_id = ?", (version_id, user_id)).fetchone()
    if row is None or not _write(user_id, row["project_id"], row["name"], row["text"], "user"):
        return None
    return row["project_id"]


def _append_archive(user_id: int, project_id: int, text: str, today: str | None = None) -> bool:
    """Add an entry at the end of ARCHIVE.md under today's date (make the file if there is none). Nothing in it is
    replaced. False if not saved: not the user's project, the file would grow beyond MAX_ARCHIVE, disk nearly full."""
    text = _LEADING_DATE.sub("", text)   # the AI dated it itself (first real run, 15.11.2026): the hub's date counts
    if not text.strip():
        return False
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
        " AND f.status = 'ready' AND f.url IS NULL AND f.category = 'memory' AND lower(f.name) LIKE '%.md'"
        " AND f.is_folder = 0 AND f.parent_id IS NULL", (project_id, user_id)).fetchall()
    def order(r) -> tuple:
        name = r["name"].lower()
        return (0 if name == MEMORY_NAME.lower() else 2 if name == ARCHIVE_NAME.lower() else 1, name)
    return sorted(rows, key=order)


def inline(conn: sqlite3.Connection, user_id: int, project_id: int, only: tuple[str, ...] | None = None,
           budget: int = MAX_INLINE, can_open: bool = True) -> str:
    """Memory files for a package as <file> blocks: MEMORY.md whole (up to MAX_MEMORY), the others while `budget`
    lasts, ARCHIVE.md never (it only grows; it is named). `only`: just these files (names, any case). What does not fit
    is named with its size: to open in /files (`can_open`) or to ask for with <read>. "" when there is nothing."""
    wanted = {n.lower() for n in only} if only else None
    blocks, used = [], 0
    hint = "open it in /files when you need it" if can_open else "ask for it with <read> when you need it"
    for row in _folder_rows(conn, user_id, project_id):
        name = row["name"].lower()
        if wanted is not None and name not in wanted:
            continue
        shown = row["name"].replace('"', "'")
        main = name == MEMORY_NAME.lower()
        text = None if name == ARCHIVE_NAME.lower() else _text_of(row, MAX_MEMORY)
        if text is not None and (main or used + len(text) <= budget):
            used += 0 if main else len(text)
            blocks.append(f'<file name="{shown}">\n{text.strip() or "(empty)"}\n</file>')
        else:
            blocks.append(f'<file name="{shown}" size="{row["size"]} bytes">({hint})</file>')
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
        " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready' AND f.is_folder = 0"
        " AND NOT (f.url IS NULL AND f.category = 'memory' AND f.parent_id IS NULL AND lower(f.name) LIKE '%.md')"
        " ORDER BY f.id DESC LIMIT ?",
        (project_id, user_id, MAX_LIST),
    ).fetchall()
    lines = []
    for row in rows:
        if row["url"] is not None:
            lines.append(f"- {row['name']}: {row['url']} (link, a source)")
        else:
            readable = files.extension(row["name"]) in READABLE and row["size"] <= MAX_READ_BYTES
            lines.append(f"- {row['name']} ({row['category']}, {row['size']} bytes"
                         f"{'' if readable else ', not text: you can not open it'})")
    return "\n".join(lines)


def contents(conn: sqlite3.Connection, user_id: int, project_id: int, names: list[str]) -> str:
    """The files the manager asked for, as <file name="..."> blocks; a name that is not a file of this project
    (or not readable text) says so. Together at most MAX_REQUESTED characters."""
    blocks, used = [], 0
    for name in names[:MAX_READS]:
        row = _find(conn, user_id, project_id, name, memory_only=False)
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
