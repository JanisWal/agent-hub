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
"""
import os
import shutil
import sqlite3
import time
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
TEXT_MAX = 1024 ** 2             # largest file the text editor opens (also the limit of one form field)
STALE = 24 * 3600                # an unfinished upload older than this is thrown away
MAX_NAME = 120
MAX_URL = 2000

CODE = set("py js mjs ts tsx jsx swift java kt c h cpp hpp cs go rs rb php sh bash ps1 sql json yaml yml toml xml html css scss "
           "ini cfg conf gradle plist ino lua pl r m mm".split())
IMAGE = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
         "avif": "image/avif", "bmp": "image/bmp", "svg": "image/svg+xml"}
VIDEO = {"mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime", "webm": "video/webm"}
AUDIO = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "ogg": "audio/ogg", "flac": "audio/flac",
         "aac": "audio/aac"}
MEDIA_OTHER = set("heic heif tif tiff mkv avi wmv flv 3gp opus".split())
EDITABLE = {"md", "txt"}          # the pencil opens an editor for these


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

    @property
    def ext(self) -> str:
        return self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""

    @property
    def kind(self) -> str:
        """For the icon and the preview: link, image, video, audio, code, text or other."""
        if self.url is not None:
            return "link"
        ext = self.ext
        if ext in IMAGE:
            return "image"
        if ext in VIDEO:
            return "video"
        if ext in AUDIO:
            return "audio"
        if ext in CODE:
            return "code"
        return "text" if ext in EDITABLE else "other"

    @property
    def editable(self) -> bool:
        return self.url is None and self.ext in EDITABLE


def category_for(name: str) -> str:
    """The area a new file goes into, by its ending."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "md":
        return "memory"
    if ext in CODE:
        return "code"
    if ext in IMAGE or ext in VIDEO or ext in AUDIO or ext in MEDIA_OTHER:
        return "media"
    return "documents"


def content_type(name: str) -> tuple[str, bool]:
    """(Content-Type, inline). Only images, video and audio are shown in the browser; the type comes from a fixed
    table, never from the upload. Everything else is a download with a neutral type."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    for table in (IMAGE, VIDEO, AUDIO):
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
                      row["status"], row["created_at"])


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
    """The finished files and links of a project, newest first; empty if the project is not the user's."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT f.* FROM files f JOIN projects p ON p.id = f.project_id"
            " WHERE f.project_id = ? AND p.user_id = ? AND f.status = 'ready' ORDER BY f.id DESC",
            (project_id, user_id),
        ).fetchall()
    return [_to_file(r) for r in rows]


def start_upload(user_id: int, project_id: int, name: str, size: int, now: int | None = None) -> StoredFile:
    """Make the file for an upload that follows in runs of blocks. It exists at its full size from the start (the rest
    is filled in), so the runs may come in any order. Raises FileError: bad_name, not_found (not his project),
    disk_full (the file would not fit and leave MIN_FREE)."""
    name = _clean_name(name)
    now = int(now if now is not None else time.time())
    if size < 0:
        raise FileError("bad_name")
    parts = "0" * -(-size // BLOCK_SIZE)          # one flag per block, "1" = it is in
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        _drop_stale(conn, now)
        if free_bytes() - size < MIN_FREE:
            raise FileError("disk_full")
        cur = conn.execute(
            "INSERT INTO files (project_id, name, category, size, status, created_at, parts)"
            " VALUES (?, ?, ?, ?, 'uploading', ?, ?)",
            (project_id, name, category_for(name), size, now, parts),
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


def _same_name(conn: sqlite3.Connection, project_id: int, category: str, name: str, but: int | None = None) -> list[int]:
    """Ids of the finished files of the area with this name, ignoring upper and lower case (as Windows and macOS do)."""
    return [r[0] for r in conn.execute(
        "SELECT id FROM files WHERE project_id = ? AND category = ? AND status = 'ready' AND lower(name) = lower(?)"
        " AND id IS NOT ?", (project_id, category, name, but))]


def _free_name(name: str, taken: set[str]) -> str:
    """The name with " (2)", " (3)", ... before the ending, the first that is not taken (lower case in `taken`)."""
    stem, dot, ext = name.rpartition(".") if "." in name.strip(".") else (name, "", "")
    for n in range(2, 10000):
        candidate = f"{stem} ({n}){dot}{ext}"[:MAX_NAME] if dot else f"{name} ({n})"[:MAX_NAME]
        if candidate.lower() not in taken:
            return candidate
    raise FileError("bad_name")


def check_names(user_id: int, project_id: int, names: list[str], category: str | None = None) -> list[dict] | None:
    """Before an upload: which of these names already exist in the area the file goes to (the chosen `category`, else
    the one its ending gives). For each such name: the ids of the files with it and a free name for "keep both".
    A name that comes twice in the same upload counts as taken too (with no ids). None if the project is not his."""
    if category is not None and category not in CATEGORIES:
        category = None
    found = []
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            return None
        names_by_area: dict[str, set[str]] = {}
        for raw in names:
            try:
                name = _clean_name(raw)
            except FileError:
                continue
            area = category or category_for(name)
            if area not in names_by_area:
                names_by_area[area] = {r[0].lower() for r in conn.execute(
                    "SELECT name FROM files WHERE project_id = ? AND category = ? AND status = 'ready'", (project_id, area))}
            taken = names_by_area[area]
            if name.lower() in taken:
                free = _free_name(name, taken)
                found.append({"name": raw, "ids": _same_name(conn, project_id, area, name), "free": free})
                taken.add(free.lower())
            else:
                taken.add(name.lower())
    return found


def add_link(user_id: int, project_id: int, url: str, name: str = "", now: int | None = None) -> StoredFile:
    """Add a link as a source of information. The name defaults to the host. Raises FileError: bad_url, not_found."""
    url = _clean_url(url)
    name = _clean_name(name) if (name or "").strip() else _clean_name(urlsplit(url).hostname or url)
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        cur = conn.execute(
            "INSERT INTO files (project_id, name, category, size, url, status, created_at)"
            " VALUES (?, ?, 'links', 0, ?, 'ready', ?)",
            (project_id, name, url, int(now if now is not None else time.time())),
        )
        row = conn.execute("SELECT * FROM files WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_file(row)


def create_text_file(user_id: int, project_id: int, name: str, text: str, now: int | None = None) -> StoredFile:
    """Make a finished text file at once, without an upload (the manager's memory file). Raises FileError:
    bad_name, not_found (not his project), too_big (over TEXT_MAX), disk_full."""
    name = _clean_name(name)
    data = text.encode("utf-8")
    if len(data) > TEXT_MAX:
        raise FileError("too_big")
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        if free_bytes() - len(data) < MIN_FREE:
            raise FileError("disk_full")
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
    """Rename a file or link; a link may get a new address, any row may be moved to another area. Raises FileError."""
    name = _clean_name(name)
    if category is not None and category not in CATEGORIES:
        raise FileError("bad_category")
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "ready":
            raise FileError("not_found")
        is_link = row["url"] is not None
        new_url = _clean_url(url) if is_link and url is not None else row["url"]
        if is_link:
            category = "links"            # a link stays a link, a file never becomes one
        elif category == "links":
            raise FileError("bad_category")
        if not is_link and _same_name(conn, row["project_id"], category or row["category"], name, but=file_id):
            raise FileError("name_taken")  # two files of an area never share a name (the upload asks first)
        conn.execute("UPDATE files SET name = ?, url = ?, category = ? WHERE id = ?",
                     (name, new_url, category or row["category"], file_id))
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _to_file(row)


def thumb_path(project_id: int, file_id: int) -> Path:
    return files_dir() / str(project_id) / f"{file_id}.thumb"


def has_thumb(item: "StoredFile") -> bool:
    return item.url is None and thumb_path(item.project_id, item.id).is_file()


def save_thumb(user_id: int, file_id: int, data: bytes) -> bool:
    """Keep the small preview picture of an image or video (a JPEG made by the browser). False if the file is not
    the user's, not finished, or not an image or video. Raises FileError: too_big, bad_type (not a JPEG). It is
    served with a fixed type, so even a wrong body can run nothing."""
    if len(data) > THUMB_MAX:
        raise FileError("too_big")
    if not data.startswith(b"\xff\xd8\xff"):
        raise FileError("bad_type")
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
    if row is None or row["status"] != "ready":
        return False
    item = _to_file(row)
    if item.kind not in ("image", "video"):
        return False
    thumb_path(item.project_id, item.id).write_bytes(data)
    return True


def open_thumb(user_id: int, file_id: int) -> Path | None:
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
    if row is None or row["url"] is not None:
        return None
    path = thumb_path(row["project_id"], file_id)
    return path if path.is_file() else None


def delete(user_id: int, file_id: int) -> bool:
    """Delete for good (no trash can). False if it is not the user's."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None:
            return False
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    path_of(row["project_id"], file_id).unlink(missing_ok=True)
    thumb_path(row["project_id"], file_id).unlink(missing_ok=True)
    return True


def open_file(user_id: int, file_id: int) -> tuple[Path, StoredFile] | None:
    """The path and row of a finished file of the user, or None (links have no file)."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
    if row is None or row["status"] != "ready" or row["url"] is not None:
        return None
    path = path_of(row["project_id"], file_id)
    return (path, _to_file(row)) if path.is_file() else None


def read_text(user_id: int, file_id: int) -> str | None:
    """The text of an editable file (Markdown or plain text), or None. Raises FileError(too_big) for a huge one."""
    found = open_file(user_id, file_id)
    if found is None or not found[1].editable:
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
        path_of(row["project_id"], row["id"]).unlink(missing_ok=True)
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
