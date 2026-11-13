"""File storage of a project (Manager view, Janis 12.11.2026): one protected folder per project that takes
every kind of file (nothing is ever run), sorted into five areas, plus links as sources of information.

Areas (`CATEGORIES`): memory (notes the agents read, Markdown), code, media (images, video, audio), documents
(everything else, e.g. PDFs and manuals as a source of data) and links. A new file is sorted by its ending
(`category_for`) and can be moved by hand. Links are rows of the same table (no file on disk, `url` is set).

There is no size or type limit (Janis: his own server). The only protection is the free space: an upload is
refused when less than MIN_FREE would stay free, so a big file cannot choke the database. Big files come in
chunks (`start_upload`, `append_chunk`, `finish_upload`): the chunk must start exactly where the file ends, so an
interrupted upload can go on. Files live in FILES_DIR/<project id>/<file id>, outside the web folder, never under
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

from . import db

FILES_DIR = Path(os.environ.get("HUB_FILES_DIR", "/data/files"))
CATEGORIES = ("memory", "code", "media", "documents", "links")
MIN_FREE = 1024 ** 3             # an upload is refused when less than this would stay free
CHUNK_MAX = 16 * 1024 ** 2       # largest chunk one request may carry
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
    """The reason is the `code`: bad_name, bad_url, bad_category, disk_full, not_found, too_big, bad_offset."""

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


def free_bytes() -> int:
    """Free space of the disk the files live on (a function of its own, so tests can fake it)."""
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(FILES_DIR).free


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
    return FILES_DIR / str(project_id) / str(file_id)


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
    """Make the (empty) file for an upload that follows in chunks. Raises FileError: bad_name, not_found (not his
    project), disk_full (the file would not fit and leave MIN_FREE)."""
    name = _clean_name(name)
    now = int(now if now is not None else time.time())
    if size < 0:
        raise FileError("bad_name")
    with db.connect() as conn:
        if not _own_project(conn, user_id, project_id):
            raise FileError("not_found")
        _drop_stale(conn, now)
        if free_bytes() - size < MIN_FREE:
            raise FileError("disk_full")
        cur = conn.execute(
            "INSERT INTO files (project_id, name, category, size, status, created_at) VALUES (?, ?, ?, 0, 'uploading', ?)",
            (project_id, name, category_for(name), now),
        )
        file_id = cur.lastrowid
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    target = path_of(project_id, file_id)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(b"")
    return _to_file(row)


def append_chunk(user_id: int, file_id: int, offset: int, data: bytes) -> int:
    """Add a chunk at the end of an unfinished upload and return the new size. Raises FileError: not_found,
    bad_offset (the chunk must start where the file ends), too_big (over CHUNK_MAX), disk_full."""
    if len(data) > CHUNK_MAX:
        raise FileError("too_big")
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "uploading":
            raise FileError("not_found")
        target = path_of(row["project_id"], file_id)
        have = target.stat().st_size if target.exists() else 0
        if offset != have:
            raise FileError("bad_offset")
        if free_bytes() - len(data) < MIN_FREE:
            raise FileError("disk_full")
        with open(target, "ab") as handle:
            handle.write(data)
        conn.execute("UPDATE files SET size = ? WHERE id = ?", (have + len(data), file_id))
    return have + len(data)


def finish_upload(user_id: int, file_id: int) -> StoredFile:
    """Mark an upload as complete. Raises FileError(not_found) if it is not an unfinished upload of the user."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None or row["status"] != "uploading":
            raise FileError("not_found")
        conn.execute("UPDATE files SET status = 'ready' WHERE id = ?", (file_id,))
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _to_file(row)


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
        conn.execute("UPDATE files SET name = ?, url = ?, category = ? WHERE id = ?",
                     (name, new_url, category or row["category"], file_id))
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _to_file(row)


def delete(user_id: int, file_id: int) -> bool:
    """Delete for good (no trash can). False if it is not the user's."""
    with db.connect() as conn:
        row = _owned(conn, user_id, file_id)
        if row is None:
            return False
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    path_of(row["project_id"], file_id).unlink(missing_ok=True)
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
    """Delete the folders of projects that no longer exist (the rows go with the project, the files do not)."""
    if not FILES_DIR.is_dir():
        return
    with db.connect() as conn:
        alive = {str(r[0]) for r in conn.execute("SELECT id FROM projects")}
    for folder in FILES_DIR.iterdir():
        if folder.is_dir() and folder.name not in alive:
            shutil.rmtree(folder, ignore_errors=True)
