"""File storage of a project (Manager view, Janis 12.11.2026): one protected folder per project that takes
every kind of file (nothing is ever run), sorted into five areas, plus links as sources of information.

Areas (`CATEGORIES`): memory (notes the agents read, Markdown), code, media (images, video, audio), documents
(everything else, e.g. PDFs and manuals as a source of data) and links. A new file is sorted by its ending
(`category_for`) and can be moved by hand. Links are rows of the same table (no file on disk, `url` is set).

There is no size or type limit (Janis: his own server). The only protection is the free space: an upload is
refused when less than MIN_FREE would stay free, so a big file cannot choke the database. Big files come in
parts (`start_upload`, `append_chunk`, `finish_upload`): the file is made at its full size and counted in blocks
of BLOCK_SIZE; a request carries any run of whole blocks (the last one may end the file), runs may arrive in
any order, several at a time, and one can be sent again. A request is written to disk while it arrives (`Run`),
and the part of a broken request that arrived is kept. The browser picks the size of a request from the speed it
measures; `finish_upload` checks that every block is in. Files live in FILES_DIR/<project id>/<file id>, outside the web folder, never under
their display name (a name can not reach a path). Like every data module, each function gets the `user_id` and
the project must be his: foreign things are "not found" (None, False or FileError). Standard library only.

Folders and labels (Janis, 18.11.2026; labels since `file-tags`, PROJEKT.md list item 3h): a folder is a row with
`is_folder` = 1 and no file on disk; every row has `parent_id`, the folder it lies in (NULL = the top of the project).
The folders are ONE tree for the whole project, with no area. The area of a file is its label (`category`): set by
its ending when it comes in (also each file of a dropped folder), changed by hand (`set_label`); a folder has none
(''). Links have the label "links" and may lie in folders too. Names are unique per folder, ignoring case. Moving,
deleting, restoring and purging a folder take everything inside along; the trash shows only the top of what went in
together. The memory is the files labelled "memory" at the top (memory.py).
"""
import os
import shutil
import sqlite3
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import db, serversettings

FILES_DIR: Path | None = None    # tests set this; normally unset, see files_dir()


def files_dir() -> Path:
    """Where the files live: HUB_FILES_DIR, else the folder `files` NEXT TO THE DATABASE. Tied to the database on purpose:
    a test that works on its own (temporary) database therefore also works on its own folder and can never touch the
    real files (an earlier fixed path /data/files was emptied by test runs that mount the real data folder)."""
    if FILES_DIR is not None:
        return Path(FILES_DIR)
    return Path(os.environ.get("HUB_FILES_DIR") or Path(db.DB_PATH).parent / "files")
CATEGORIES = ("memory", "code", "media", "documents", "links")
MIN_FREE = 1024 ** 3             # an upload is refused when less than this would stay free
BLOCK_SIZE = 256 * 1024          # an upload is counted in blocks of this size (the unit of Cloudflare Stream and tus uploaders)
MAX_REQUEST = 512 * 1024 ** 2    # hard ceiling of one request; the real limit is the owner's choice (max_request)
THUMB_MAX = 256 * 1024            # largest preview picture (the browser makes them: 96 x 96 JPEG, a few KB)
PREVIEW_MAX = 6 * 1024 ** 2      # largest big preview of a TIFF, HEIC or raw picture (2048 px JPEG from the browser)
TEXT_MAX = 1024 ** 2             # largest file the text editor opens (also the limit of one form field)
STALE = 24 * 3600                # an unfinished upload older than this is thrown away
TRASH_DAYS = 30                  # a deleted file stays this long in the trash, then it is gone (Janis, 14.11.2026)
MAX_NAME = 120
MAX_URL = 2000

CODE = set("py js mjs ts tsx jsx swift java kt c h cpp hpp cs go rs rb php sh bash ps1 sql json yaml yml toml xml html css scss "
           "ini cfg conf gradle plist ino lua pl r m mm".split())
IMAGE = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
         "avif": "image/avif", "bmp": "image/bmp", "svg": "image/svg+xml", "ico": "image/x-icon"}
VIDEO = {"mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime", "webm": "video/webm"}
AUDIO = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "ogg": "audio/ogg", "flac": "audio/flac",
         "aac": "audio/aac", "opus": "audio/ogg"}
PDF = {"pdf": "application/pdf"}  # shown by the browser's own PDF viewer (Janis, 18.11.2026: look without downloading)
# Camera raw files (Janis, 14.11.2026: a DNG is a picture, so it goes to Media) and other pictures the browser can not
# show everywhere: they still get a small preview, made in the browser (static/tiffthumb.js), never on the server.
RAW = set("dng cr2 cr3 nef nrw arw srf sr2 orf rw2 raf pef srw x3f 3fr erf kdc mos mrw".split())
PHOTO = set("heic heif tif tiff".split()) | RAW
MEDIA_OTHER = set("mkv avi wmv flv 3gp".split()) | PHOTO
EDITABLE = {"md", "txt"}          # the pencil opens an editor for these
# Plain text the reader shows without editing (code and data files; never rendered: an HTML file shows as its text).
READABLE = CODE | EDITABLE | set("csv tsv log env gitignore dockerfile makefile properties srt vtt tex rst adoc".split())
TABLE = {"csv", "tsv"}             # the reader shows these as a table


def extension(name: str) -> str:
    """The ending of a file name in lower case, without the dot ("" if it has none)."""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


class FileError(ValueError):
    """The reason is the `code`: bad_name, bad_url, bad_category, disk_full, not_found, too_big, bad_offset, incomplete,
    bad_type, name_taken."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class StoredFile:
    id: int
    project_id: int
    name: str
    category: str
    size: int
    url: str | None
    status: str
    created_at: int
    parent_id: int | None = None
    is_folder: bool = False

    @property
    def ext(self) -> str:
        return extension(self.name)

    @property
    def kind(self) -> str:
        """For the icon and the preview: link, image, video, audio, photo (TIFF, HEIC, raw: a preview, but no viewer,
        not every browser can show them), pdf, code, text, folder or other."""
        if self.is_folder:
            return "folder"
        if self.url is not None:
            return "link"
        ext = self.ext
        if ext in IMAGE:
            return "image"
        if ext in VIDEO:
            return "video"
        if ext in AUDIO:
            return "audio"
        if ext in PHOTO:
            return "photo"
        if ext in PDF:
            return "pdf"
        if ext in CODE:
            return "code"
        return "text" if ext in READABLE else "other"

    @property
    def editable(self) -> bool:
        return self.url is None and not self.is_folder and self.ext in EDITABLE

    @property
    def readable(self) -> bool:
        """The reader shows it as text (code, data, notes); only `editable` ones can be changed there."""
        return self.url is None and not self.is_folder and (self.ext in READABLE or self.name.lower() in READABLE)


def category_for(name: str) -> str:
    """The area a new file goes into, by its ending."""
    ext = extension(name)
    if ext == "md":
        return "memory"
    if ext in CODE:
        return "code"
    if ext in IMAGE or ext in VIDEO or ext in AUDIO or ext in MEDIA_OTHER:
        return "media"
    return "documents"


def content_type(name: str) -> tuple[str, bool]:
    """(Content-Type, inline). Only images, video, audio and PDFs are shown in the browser; the type comes from a fixed
    table, never from the upload. Everything else is a download with a neutral type (text comes to the reader through
    read_text, never as a page of its own)."""
    ext = extension(name)
    for table in (IMAGE, VIDEO, AUDIO, PDF):
        if ext in table:
            return table[ext], True
    return "application/octet-stream", False


def max_request() -> int:
    """The most one upload request may carry: the owner's choice on the administration page (serversettings), never
    above MAX_REQUEST. The browser gets the same value and never sends more."""
    return min(MAX_REQUEST, serversettings.upload()[1] * 1024 ** 2)


def free_bytes() -> int:
    """Free space of the disk the files live on (a function of its own, so tests can fake it)."""
    files_dir().mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(files_dir()).free


def _clean_name(name: str) -> str:
    name = "".join(ch for ch in (name or "") if ch >= " " and ch not in '\\/:*?"<>|\x7f').strip().strip(".")
    if not name:
        raise FileError("bad_name")
    return name[:MAX_NAME]


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    parts = urlsplit(url)
    if len(url) > MAX_URL or parts.scheme not in ("http", "https") or not parts.hostname or any(c.isspace() for c in url):
        raise FileError("bad_url")
    return url


def _to_file(row: sqlite3.Row) -> StoredFile:
    return StoredFile(row["id"], row["project_id"], row["name"], row["category"], row["size"], row["url"],
                      row["status"], row["created_at"], row["parent_id"], bool(row["is_folder"]))


def _owned(conn: sqlite3.Connection, user_id: int, file_id: int) -> sqlite3.Row | None:
    """The file row, only if its project belongs to the user."""
    return conn.execute(
        "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id WHERE f.id = ? AND p.user_id = ?",
        (file_id, user_id),
    ).fetchone()


def _own_project(conn: sqlite3.Connection, user_id: int, project_id: int) -> bool:
    return conn.execute("SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)).fetchone() is not None


def path_of(project_id: int, file_id: int) -> Path:
    return files_dir() / str(project_id) / str(file_id)


def list_files(user_id: int, project_id: int) -> list[StoredFile]:
    """The finished files, links and folders of a project: folders first by name, then the rest newest first; empty
    if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
            " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready'"
            " ORDER BY f.is_folder DESC, CASE WHEN f.is_folder THEN lower(f.name) END, f.id DESC",
            (project_id, user_id),
        ).fetchall()
    return [_to_file(r) for r in rows]


def folder_path(items: list[StoredFile], item: StoredFile) -> list[str]:
    """The names of the folders above a row, outermost first ([] at the top of its area), from a list_files list."""
    folders = {f.id: f for f in items if f.is_folder}
    path, seen, parent = [], set(), item.parent_id
    while parent in folders and parent not in seen:   # `seen`: never loop, even on broken data
        seen.add(parent)
        path.append(folders[parent].name)
        parent = folders[parent].parent_id
    return path[::-1]


def _folder(conn: sqlite3.Connection, project_id: int, folder_id: int | None) -> sqlite3.Row | None:
    """A finished folder of this project (the caller has checked the project is the user's)."""
    if folder_id is None:
        return None
    return conn.execute("SELECT * FROM files WHERE id = ? AND project_id = ? AND is_folder = 1 AND status = 'ready'",
                        (folder_id, project_id)).fetchone()


def _subtree(conn: sqlite3.Connection, row_id: int) -> list[int]:
    """The row and everything below it (a file: only itself)."""
    return [r[0] for r in conn.execute(
        "WITH RECURSIVE t(id) AS (SELECT ? UNION SELECT f.id FROM files f JOIN t ON f.parent_id = t.id) SELECT id FROM t",
        (row_id,))]


def create_folder(user_id: int, project_id: int, name: str, parent_id: int | None = None, reuse: bool = False,
                  now: int | None = None) -> StoredFile:
    """A new folder at the top of the project or inside a folder. `reuse`: a folder of that name in that place is
    returned instead (an uploaded folder tree joins what is there). Raises FileError: bad_name, not_found (not his
    project or not his folder), name_taken."""
    name = _clean_name(name)
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        return make_folder(conn, project_id, name, parent_id, reuse, now)


def make_folder(conn: sqlite3.Connection, project_id: int, name: str, parent_id: int | None = None,
                reuse: bool = False, now: int | None = None) -> StoredFile:
    """create_folder on an open connection; the caller has checked that the project is the user's."""
    name = _clean_name(name)
    if parent_id is not None and _folder(conn, project_id, parent_id) is None:
        raise FileError("not_found")
    same = conn.execute(
        "SELECT * FROM files WHERE project_id = ? AND parent_id IS ? AND status = 'ready' AND lower(name) = lower(?)"
        " ORDER BY id LIMIT 1", (project_id, parent_id, name)).fetchone()
    if same is not None:
        if reuse and same["is_folder"]:
            return _to_file(same)
        raise FileError("name_taken")
    cur = conn.execute(
        "INSERT INTO files (project_id, name, category, size, status, created_at, parts, parent_id, is_folder)"
        " VALUES (?, ?, '', 0, 'ready', ?, '', ?, 1)",
        (project_id, name, int(now if now is not None else time.time()), parent_id))
    return _to_file(conn.execute("SELECT * FROM files WHERE id = ?", (cur.lastrowid,)).fetchone())


def move(user_id: int, project_id: int, ids: list[int], folder_id: int | None = None) -> int:
    """Move files, links and folders (with all inside) of the user's project into a folder or to the top (marked rows
    dragged onto a folder, a step of the path or "All"). The label stays. A name the place has already gets " (2)".
    Left out: rows that are not his, a folder into itself or below itself. Returns how many moved. Raises FileError:
    not_found (not his project or folder)."""
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        return move_rows(conn, project_id, ids, folder_id)


def move_rows(conn: sqlite3.Connection, project_id: int, ids: list[int], folder_id: int | None = None) -> int:
    """move on an open connection; the caller has checked that the project is the user's."""
    if folder_id is not None and _folder(conn, project_id, folder_id) is None:
        raise FileError("not_found")
    moved = 0
    for row_id in dict.fromkeys(ids):
        row = conn.execute("SELECT * FROM files WHERE id = ? AND project_id = ? AND status = 'ready'",
                           (row_id, project_id)).fetchone()
        if row is None or row["parent_id"] == folder_id:
            continue
        if row["is_folder"] and folder_id is not None and folder_id in _subtree(conn, row["id"]):
            continue                                   # never into itself
        name = row["name"]
        taken = {r[0].lower() for r in conn.execute(
            "SELECT name FROM files WHERE project_id = ? AND parent_id IS ? AND status = 'ready' AND id != ?",
            (project_id, folder_id, row["id"]))}
        if name.lower() in taken:
            name = _free_name(name, taken)
        conn.execute("UPDATE files SET parent_id = ?, name = ? WHERE id = ?", (folder_id, name, row["id"]))
        moved += 1
    return moved


def set_label(user_id: int, project_id: int, ids: list[int], label: str) -> int:
    """Give files a label (rows dragged onto a tab, or the pencil): a folder gives it to every file inside, the folder
    stays where it is. Links keep "links", and no file becomes a link. Returns how many files changed. Raises
    FileError: not_found (not his project), bad_category."""
    if label not in CATEGORIES or label == "links":
        raise FileError("bad_category")
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        changed = 0
        for row_id in dict.fromkeys(ids):
            row = conn.execute("SELECT id FROM files WHERE id = ? AND project_id = ? AND status = 'ready'",
                               (row_id, project_id)).fetchone()
            if row is None:
                continue
            inside = _subtree(conn, row["id"])
            changed += conn.execute(
                f"UPDATE files SET category = ? WHERE id IN ({','.join('?' * len(inside))}) AND is_folder = 0"
                " AND url IS NULL AND category != ?", (label, *inside, label)).rowcount
    return changed


def one_tree(conn: sqlite3.Connection) -> None:
    """Once (18.11.2026, `file-tags`; db._prepare, remove when no database from before can be left): folders lose their
    area, and names must now be unique per folder of the whole project. Inside a folder they already are (everything in
    it had the folder's area); at the top a name may come once per area: the memory files keep theirs, every later one
    gets " (2)". The labels of the files stay as they are."""
    conn.execute("UPDATE files SET category = '' WHERE is_folder = 1")
    taken: dict[int, set[str]] = {}
    for row in conn.execute("SELECT id, project_id, name FROM files WHERE parent_id IS NULL AND status = 'ready'"
                            " ORDER BY project_id, (category = 'memory' AND is_folder = 0) DESC, id").fetchall():
        names = taken.setdefault(row["project_id"], set())
        if row["name"].lower() in names:
            free = _free_name(row["name"], names)
            conn.execute("UPDATE files SET name = ? WHERE id = ?", (free, row["id"]))
            names.add(free.lower())
        else:
            names.add(row["name"].lower())


AGENT_FILES = 300   # files named in the list for a run or chat at most


def for_agents(conn: sqlite3.Connection, user_id: int, project_id: int) -> tuple[list[dict], list[dict]]:
    """(files, links) of a project for the read-only /files of a run or chat (runner/view.py, Janis 16.11.2026):
    files as id, name, area (its label), size and `path` (the names of the folders above it, outermost first; the
    runner copies them into the same folders; never a path on disk), links as name, address and path. Only finished
    files of the user's own project; nothing in the trash."""
    folders = {r["id"]: r for r in conn.execute(
        "SELECT f.id, f.name, f.parent_id FROM files f JOIN projects p ON p.id = f.project_id"
        " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready' AND f.is_folder = 1", (project_id, user_id))}
    rows = conn.execute(
        "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
        " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready' AND f.is_folder = 0 ORDER BY f.id LIMIT ?",
        (project_id, user_id, AGENT_FILES)).fetchall()

    def path(parent) -> list[str]:
        names, seen = [], set()
        while parent in folders and parent not in seen:
            seen.add(parent)
            names.append(folders[parent]["name"])
            parent = folders[parent]["parent_id"]
        return names[::-1]
    stored = [{"id": r["id"], "name": r["name"], "area": r["category"], "size": r["size"], "path": path(r["parent_id"])}
              for r in rows if not r["url"]]
    links = [{"name": r["name"], "url": r["url"], "path": path(r["parent_id"])} for r in rows if r["url"]]
    return stored, links


def start_upload(user_id: int, project_id: int, name: str, size: int, now: int | None = None,
                 folder_id: int | None = None, label: str | None = None) -> StoredFile:
    """Make the file for an upload that follows in runs of blocks. It exists at its full size from the start (the rest
    is filled in), so the runs may come in any order. `folder_id`: it goes into that folder. `label`: a file dropped on
    a tab gets that label, else the one of its ending. Raises FileError: bad_name, not_found (not his project or
    folder), disk_full (the file would not fit and leave MIN_FREE)."""
    name = _clean_name(name)
    now = int(now if now is not None else time.time())
    if size < 0:
        raise FileError("bad_name")
    parts = "0" * -(-size // BLOCK_SIZE)          # one flag per block, "1" = it is in
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        if folder_id is not None and _folder(conn, project_id, folder_id) is None:
            raise FileError("not_found")
        _drop_stale(conn, now)
        if free_bytes() - size < MIN_FREE:
            raise FileError("disk_full")
        cur = conn.execute(
            "INSERT INTO files (project_id, name, category, size, status, created_at, parts, parent_id)"
            " VALUES (?, ?, ?, ?, 'uploading', ?, ?, ?)",
            (project_id, name, label if label in CATEGORIES and label != "links" else category_for(name), size, now,
             parts, folder_id),
        )
        file_id = cur.lastrowid
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    target = path_of(project_id, file_id)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(target, "wb") as handle:
        handle.truncate(size)
    return _to_file(row)


class Run:
    """One request of an upload, written to its place in the file AS IT ARRIVES (nothing is held in memory, so a big
    request costs the Pi no RAM). What came in is kept even if the line breaks: close() counts every whole block that
    was written, and the last block when the run reached the end of the file. The browser then asks upload_progress
    and sends only what is missing (like a tus server, which also keeps the part of a request that arrived).

    `length` is the announced size (Content-Length). When it is known the run must lie inside the file and be whole
    blocks unless it ends the file; without it (None) the run may go up to MAX_REQUEST or the end of the file.
    Raises FileError: not_found, bad_offset, too_big (over MAX_REQUEST, or more than announced), disk_full."""

    def __init__(self, user_id: int, file_id: int, offset: int, length: int | None):
        most = max_request()
        if length is not None and length > most:
            raise FileError("too_big")
        with db.connect() as conn:
            row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "uploading":
            raise FileError("not_found")
        size = row["size"]
        if offset < 0 or offset % BLOCK_SIZE or offset >= size:
            raise FileError("bad_offset")
        if length is not None and (length <= 0 or offset + length > size
                                   or (offset + length < size and length % BLOCK_SIZE)):
            raise FileError("bad_offset")
        self.limit = length if length is not None else min(most, size - offset)
        if free_bytes() - self.limit < MIN_FREE:
            raise FileError("disk_full")
        self.file_id, self.offset, self.size, self.written = file_id, offset, size, 0
        self.handle = open(path_of(row["project_id"], file_id), "r+b")
        self.handle.seek(offset)

    def write(self, data: bytes) -> None:
        if self.written + len(data) > self.limit:
            raise FileError("too_big")
        self.handle.write(data)
        self.written += len(data)

    def close(self) -> int:
        """Count what arrived; returns how many blocks of the file are in (0 if the upload is gone meanwhile)."""
        self.handle.close()
        first = self.offset // BLOCK_SIZE
        if self.offset + self.written == self.size:
            count = -(-self.written // BLOCK_SIZE)
        else:
            count = self.written // BLOCK_SIZE
        with db.connect() as conn:
            if count:
                conn.execute("UPDATE files SET parts = substr(parts, 1, ?) || ? || substr(parts, ?)"
                             " WHERE id = ? AND status = 'uploading'", (first, "1" * count, first + count + 1, self.file_id))
            row = conn.execute("SELECT parts FROM files WHERE id = ? AND status = 'uploading'", (self.file_id,)).fetchone()
        return row[0].count("1") if row else 0


def append_chunk(user_id: int, file_id: int, offset: int, data: bytes) -> int:
    """A whole run at once (a Run with one piece); returns how many blocks are in. Raises FileError like Run."""
    run = Run(user_id, file_id, offset, len(data))
    try:
        run.write(data)
    finally:
        received = run.close()
    return received


def upload_progress(user_id: int, file_id: int, now: int | None = None) -> tuple[int, str] | None:
    """(size, parts) of an unfinished upload of the user, or None. `parts` has one character per block, "1" = it is in.
    Asking also keeps the upload alive (an upload that is being resumed is not stale). This is how the browser goes
    on after a break: it asks what the server really has and sends only the rest."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "uploading":
            return None
        conn.execute("UPDATE files SET created_at = ? WHERE id = ?", (int(now if now is not None else time.time()), file_id))
    return row["size"], row["parts"]


def finish_upload(user_id: int, file_id: int) -> StoredFile:
    """Mark an upload as complete. Raises FileError: not_found (not an unfinished upload of the user),
    incomplete (a block is missing)."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "uploading":
            raise FileError("not_found")
        if "0" in row["parts"]:
            raise FileError("incomplete")
        conn.execute("UPDATE files SET status = 'ready' WHERE id = ?", (file_id,))
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _to_file(row)


def _same_name(conn: sqlite3.Connection, project_id: int, name: str, but: int | None = None,
               parent: int | None = None) -> list[int]:
    """Ids of the finished rows of one place (a folder, or the top) with this name, ignoring upper and lower case (as
    Windows and macOS do)."""
    return [r[0] for r in conn.execute(
        "SELECT id FROM files WHERE project_id = ? AND parent_id IS ? AND status = 'ready'"
        " AND lower(name) = lower(?) AND id IS NOT ?", (project_id, parent, name, but))]


def _names_in(conn: sqlite3.Connection, project_id: int, parent: int | None) -> set[str]:
    return {r[0].lower() for r in conn.execute(
        "SELECT name FROM files WHERE project_id = ? AND parent_id IS ? AND status = 'ready'", (project_id, parent))}


def _free_name(name: str, taken: set[str]) -> str:
    """The name with " (2)", " (3)", ... before the ending, the first that is not taken (lower case in `taken`)."""
    stem, dot, ext = name.rpartition(".") if "." in name.strip(".") else (name, "", "")
    for n in range(2, 10000):
        candidate = f"{stem} ({n}){dot}{ext}"[:MAX_NAME] if dot else f"{name} ({n})"[:MAX_NAME]
        if candidate.lower() not in taken:
            return candidate
    raise FileError("bad_name")


def check_names(user_id: int, project_id: int, names: list[str], folder_id: int | None = None) -> list[dict] | None:
    """Before an upload: which of these names already exist in the place the files go to (the folder, else the top).
    For each such name: the ids of the rows with it and a free name for "keep both". A name that comes twice in the
    same upload counts as taken too (with no ids). None if the project (or the folder) is not his."""
    found = []
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            return None
        if folder_id is not None and _folder(conn, project_id, folder_id) is None:
            return None
        taken = _names_in(conn, project_id, folder_id)
        for raw in names:
            try:
                name = _clean_name(raw)
            except FileError:
                continue
            if name.lower() in taken:
                free = _free_name(name, taken)
                found.append({"name": raw, "ids": _same_name(conn, project_id, name, parent=folder_id), "free": free})
                taken.add(free.lower())
            else:
                taken.add(name.lower())
    return found


def add_link(user_id: int, project_id: int, url: str, name: str = "", now: int | None = None,
             folder_id: int | None = None) -> StoredFile:
    """Add a link as a source of information, at the top or in a folder. The name defaults to the host; a name the
    place has already gets " (2)". Raises FileError: bad_url, not_found (not his project or folder)."""
    url = _clean_url(url)
    name = _clean_name(name) if (name or "").strip() else _clean_name(urlsplit(url).hostname or url)
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        if folder_id is not None and _folder(conn, project_id, folder_id) is None:
            raise FileError("not_found")
        taken = _names_in(conn, project_id, folder_id)
        if name.lower() in taken:
            name = _free_name(name, taken)
        cur = conn.execute(
            "INSERT INTO files (project_id, name, category, size, url, status, created_at, parent_id)"
            " VALUES (?, ?, 'links', 0, ?, 'ready', ?, ?)",
            (project_id, name, url, int(now if now is not None else time.time()), folder_id),
        )
        row = conn.execute("SELECT * FROM files WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_file(row)


def create_text_file(user_id: int, project_id: int, name: str, text: str, now: int | None = None) -> StoredFile:
    """Make a finished text file at once at the top, without an upload (the manager's memory file). Raises FileError:
    bad_name, not_found (not his project), too_big (over TEXT_MAX), disk_full, name_taken (a row of that name is at
    the top already: names are unique per place)."""
    name = _clean_name(name)
    data = text.encode("utf-8")
    if len(data) > TEXT_MAX:
        raise FileError("too_big")
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        if free_bytes() - len(data) < MIN_FREE:
            raise FileError("disk_full")
        if _same_name(conn, project_id, name):
            raise FileError("name_taken")
        cur = conn.execute(
            "INSERT INTO files (project_id, name, category, size, status, created_at, parts)"
            " VALUES (?, ?, ?, ?, 'ready', ?, '')",
            (project_id, name, category_for(name), len(data), int(now if now is not None else time.time())),
        )
        row = conn.execute("SELECT * FROM files WHERE id = ?", (cur.lastrowid,)).fetchone()
    target = path_of(project_id, row["id"])
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(data)
    return _to_file(row)


def update(user_id: int, file_id: int, name: str, url: str | None = None, category: str | None = None) -> StoredFile:
    """Rename a file, link or folder where it is; a link may get a new address, a file another label (`category`; a
    link stays a link, a folder has none). Raises FileError: bad_name, bad_url, bad_category, not_found, name_taken."""
    name = _clean_name(name)
    if category is not None and (category not in CATEGORIES or category == "links"):
        raise FileError("bad_category")
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "ready":
            raise FileError("not_found")
        is_link = row["url"] is not None
        new_url = _clean_url(url) if is_link and url is not None else row["url"]
        label = row["category"] if is_link or row["is_folder"] or category is None else category
        if _same_name(conn, row["project_id"], name, but=file_id, parent=row["parent_id"]):
            raise FileError("name_taken")  # two rows of a place never share a name (the upload asks first)
        conn.execute("UPDATE files SET name = ?, url = ?, category = ? WHERE id = ?", (name, new_url, label, file_id))
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _to_file(row)


def thumb_path(project_id: int, file_id: int, large: bool = False) -> Path:
    return files_dir() / str(project_id) / f"{file_id}.{'preview' if large else 'thumb'}"


def has_thumb(item: "StoredFile") -> bool:
    return item.url is None and thumb_path(item.project_id, item.id).is_file()


def save_thumb(user_id: int, file_id: int, data: bytes, large: bool = False) -> bool:
    """Keep the small preview picture of an image or video (a JPEG made by the browser). False if the file is not
    the user's, not finished, or not an image or video. Raises FileError: too_big, bad_type (not a JPEG). It is
    served with a fixed type, so even a wrong body can run nothing. `large`: the big preview the viewer shows for a
    TIFF, HEIC or raw picture (Janis, 14.11.2026), which browsers can not show themselves; only for those."""
    if len(data) > (PREVIEW_MAX if large else THUMB_MAX):
        raise FileError("too_big")
    if not data.startswith(b"\xff\xd8\xff"):
        raise FileError("bad_type")
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
    if row is None or row["status"] != "ready":
        return False
    item = _to_file(row)
    if item.kind not in (("photo",) if large else ("image", "video", "photo")):
        return False
    thumb_path(item.project_id, item.id, large).write_bytes(data)
    return True


def open_thumb(user_id: int, file_id: int, large: bool = False) -> Path | None:
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
    if row is None or row["url"] is not None:
        return None
    path = thumb_path(row["project_id"], file_id, large)
    return path if path.is_file() else None


def _remove_stored(project_id: int, file_id: int) -> None:
    """Delete what a file has on the disk: the file itself and its two preview pictures."""
    for path in (path_of(project_id, file_id), thumb_path(project_id, file_id), thumb_path(project_id, file_id, True)):
        path.unlink(missing_ok=True)


def delete(user_id: int, file_id: int, now: int | None = None) -> bool:
    """Put a file or link into the trash (Janis, 14.11.2026): it leaves every list and the manager's view, and it is
    gone for good after TRASH_DAYS unless it is restored. A folder goes with everything inside (one moment, so they
    come back together). An unfinished upload goes at once. False if not the user's."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None:
            return False
        if row["status"] == "ready":
            ids = _subtree(conn, file_id)
            conn.execute(f"UPDATE files SET status = 'trash', trashed_at = ? WHERE status = 'ready'"
                         f" AND id IN ({','.join('?' * len(ids))})", (now, *ids))
            return True
    return purge(user_id, file_id)


def purge(user_id: int, file_id: int) -> bool:
    """Delete for good (from the trash, or an unfinished upload), a folder with everything inside. False if not the
    user's or a finished file."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] == "ready":
            return False
        ids = _subtree(conn, file_id)
        conn.execute(f"DELETE FROM files WHERE id IN ({','.join('?' * len(ids))})", ids)
    for gone in ids:
        _remove_stored(row["project_id"], gone)
    return True


def restore(user_id: int, file_id: int) -> StoredFile | None:
    """Take a file or folder back out of the trash to its place (a folder with what went into the trash with it); if
    its folder is gone, to the top. A name that is taken there by now gets " (2)". None if it is not the
    user's or not in the trash."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "trash":
            return None
        parent = row["parent_id"] if _folder(conn, row["project_id"], row["parent_id"]) else None
        name = row["name"]
        if _same_name(conn, row["project_id"], name, parent=parent):
            name = _free_name(name, _names_in(conn, row["project_id"], parent))
        ids = [i for i in _subtree(conn, file_id) if i != file_id]
        conn.execute("UPDATE files SET status = 'ready', trashed_at = NULL, name = ?, parent_id = ? WHERE id = ?",
                     (name, parent, file_id))
        if ids:
            conn.execute(f"UPDATE files SET status = 'ready', trashed_at = NULL WHERE status = 'trash' AND trashed_at = ?"
                         f" AND id IN ({','.join('?' * len(ids))})", (row["trashed_at"], *ids))
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _to_file(row)


def list_trash(user_id: int, project_id: int, now: int | None = None) -> list[tuple[StoredFile, int]]:
    """The trash of a project, last deleted first, each with the days it still stays; empty if not the user's. Of what
    went in together with a folder only the folder is shown. What is older than TRASH_DAYS is deleted for good on the
    way."""
    purge_old_trash(now)
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
            " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'trash' AND NOT EXISTS (SELECT 1 FROM files u"
            " WHERE u.id = f.parent_id AND u.status = 'trash' AND u.trashed_at = f.trashed_at)"
            " ORDER BY f.trashed_at DESC, f.id DESC",
            (project_id, user_id),
        ).fetchall()
    return [(_to_file(r), max(1, TRASH_DAYS - (now - (r["trashed_at"] or now)) // 86400)) for r in rows]


def empty_trash(user_id: int, project_id: int) -> int:
    """Delete everything in the project's trash for good. Returns how many rows the trash showed."""
    return sum(purge(user_id, item.id) for item, _ in list_trash(user_id, project_id))


def purge_old_trash(now: int | None = None) -> int:
    """Delete for good what lies in the trash longer than TRASH_DAYS (all users). Returns how many."""
    now = int(now if now is not None else time.time())
    with db.connect() as conn:
        rows = conn.execute("SELECT id, project_id FROM files WHERE status = 'trash' AND trashed_at < ?",
                            (now - TRASH_DAYS * 86400,)).fetchall()
        for row in rows:
            conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
    for row in rows:
        _remove_stored(row["project_id"], row["id"])
    return len(rows)


def open_file(user_id: int, file_id: int) -> tuple[Path, StoredFile] | None:
    """The path and row of a finished file of the user, or None (links have no file)."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
    if row is None or row["status"] != "ready" or row["url"] is not None or row["is_folder"]:
        return None
    path = path_of(row["project_id"], file_id)
    return (path, _to_file(row)) if path.is_file() else None


def zip_entries(user_id: int, project_id: int, ids: list[int]) -> list[tuple[Path, str]] | None:
    """For a ZIP of several files (dragging marked files out, a folder): (path, name in the ZIP) of the user's finished
    files of this project among `ids`, in that order; a folder brings everything inside under its own name
    ("Folder/Sub/file.png"). Links have no file and are left out; a name that comes twice in one place gets " (2)".
    None if the project is not his."""
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            return None
        rows = {r["id"]: r for r in conn.execute(
            "SELECT * FROM files WHERE project_id = ? AND status = 'ready' AND url IS NULL", (project_id,))}
    children: dict[int, list] = {}
    for row in sorted(rows.values(), key=lambda r: (not r["is_folder"], r["name"].lower())):
        children.setdefault(row["parent_id"], []).append(row)
    entries, taken, seen = [], set(), set()

    def add(row, prefix: str) -> None:
        if row["id"] in seen:
            return
        seen.add(row["id"])
        name = row["name"]
        if (prefix + name).lower() in taken:
            name = _free_name(name, {t[len(prefix):] for t in taken if t.startswith(prefix.lower())})
        taken.add((prefix + name).lower())
        if row["is_folder"]:
            for child in children.get(row["id"], []):
                add(child, f"{prefix}{name}/")
            return
        path = path_of(project_id, row["id"])
        if path.is_file():
            entries.append((path, prefix + name))
    for file_id in dict.fromkeys(ids):
        if file_id in rows:
            add(rows[file_id], "")
    return entries


class _Sink:
    """Where zipfile writes: it only collects what came, zip_stream hands it on (zipfile handles a stream that cannot seek)."""

    def __init__(self):
        self.parts, self.size = [], 0

    def write(self, data) -> int:
        self.parts.append(bytes(data))
        self.size += len(data)
        return len(data)

    def tell(self) -> int:
        return self.size

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data, self.parts = b"".join(self.parts), []
        return data


def zip_stream(entries: list[tuple[Path, str]], piece: int = 1024 ** 2) -> Iterator[bytes]:
    """The ZIP of these files, made while it is sent: never whole in memory or on disk. Stored, not compressed (pictures,
    videos and archives are compressed already, and the server saves the work); ZIP64, so files over 4 GB are fine."""
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path, name in entries:
            with archive.open(name, "w", force_zip64=True) as target, open(path, "rb") as source:
                while data := source.read(piece):
                    target.write(data)
                    yield sink.take()
            yield sink.take()
    yield sink.take()


def read_text(user_id: int, file_id: int) -> str | None:
    """The text of a readable file (notes, code, data), or None. Raises FileError(too_big) for a huge one."""
    found = open_file(user_id, file_id)
    if found is None or not found[1].readable:
        return None
    if found[0].stat().st_size > TEXT_MAX:
        raise FileError("too_big")
    return found[0].read_text(encoding="utf-8", errors="replace")


def write_text(user_id: int, file_id: int, text: str) -> bool:
    """Replace the text of an editable file. False if it is not an editable file of the user."""
    found = open_file(user_id, file_id)
    if found is None or not found[1].editable:
        return False
    data = text.encode("utf-8")
    if len(data) > TEXT_MAX:
        raise FileError("too_big")
    if free_bytes() - len(data) < MIN_FREE:
        raise FileError("disk_full")
    found[0].write_bytes(data)
    with db.connect() as conn:
        conn.execute("UPDATE files SET size = ? WHERE id = ?", (len(data), file_id))
    return True


def _drop_stale(conn: sqlite3.Connection, now: int) -> None:
    """Throw away uploads that were never finished (the browser was closed)."""
    for row in conn.execute("SELECT id, project_id FROM files WHERE status = 'uploading' AND created_at < ?",
                            (now - STALE,)).fetchall():
        _remove_stored(row["project_id"], row["id"])
        conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))


def remove_orphans() -> None:
    """Delete the folders of projects that no longer exist (the rows go with the project, the files do not). Only
    folders whose name is a project number are ever touched."""
    root = files_dir()
    if not root.is_dir():
        return
    with db.connect() as conn:
        alive = {str(r[0]) for r in conn.execute("SELECT id FROM projects")}
    for folder in root.iterdir():
        if folder.is_dir() and folder.name.isdigit() and folder.name not in alive:
            shutil.rmtree(folder, ignore_errors=True)
