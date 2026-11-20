"""The read-only folders a run or a chat gets besides its work (Janis, 16.11.2026): the user's files of the project as
/files and, for the manager chat, the project's code as /code. Standard library only.

The hub sends the list (id, name, label as `area`, size, the names of its folders as `path`; links with their
address), never a path on disk. The runner copies the files from the hub's storage (mounted read-only into the runner
at HUB_FILES_SOURCE) into one folder per job under HUB_WORK_DIR/views/<name>/, with their real names, in the
project's own folder tree (one tree for the whole project since 18.11.2026, `file-tags`):

    files/MEMORY.md  files/Backgrounds/Dark/x.png   the files (copies, never the originals) where they lie
    files/INDEX.md                                  every file with its label and size, also those left out
    files/LINKS.md                                  the links: folder, title and address
    code/                                           main of the project's repository (manager chat)

The folder belongs to root and is readable by everybody (the run user only reads it); the container mounts it with
`readonly`, so nothing written there can reach the hub. A copy instead of the original: the storage folders are only
the hub's (0700), and a run must never see the other files of the storage. Files above MAX_FILE and anything beyond
MAX_TOTAL are left out (named in INDEX.md).

Kept between jobs (20.11.2026): copying the files for every question wrote the same 150 MB to the SD card each time.
`acquire` gives a view named after the project and a hash of what is in it (the list from the hub and the code's
commit); jobs with the same content share it (read-only anyway), a changed one is made anew and the old one goes
once no job uses it (`release`). `remove_project` deletes them with the project; `clear` removes all at the start.

A TIFF, HEIC or raw photo can not be shown to a model as it is. The browser already made a big JPEG of it for the
viewer (`<id>.preview` next to the file in the storage, web/app/files.py); it is copied next to the photo as
"<name>.jpg", so every AI can look at it (18.11.2026).
"""
import hashlib
import json
import os
import shutil
import threading
import subprocess
import tarfile
import tempfile
from pathlib import Path

LABELS = ("documents", "media", "code", "memory")
MAX_FILE = 50 * 1024 ** 2       # a larger file is not copied (videos, big archives)
MAX_TOTAL = 200 * 1024 ** 2     # all copied files of one job together
MAX_FILES = 300                 # files taken from the list at most
MAX_CODE = 100 * 1024 ** 2      # the code snapshot (git archive) at most
MAX_DEPTH = 12                  # folders of the storage taken over at most
_UNSAFE = set('/\\\x00')


def safe_name(name: str) -> str:
    """A file name that stays inside its folder: only its last part, no control characters, no leading dot."""
    last = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    text = "".join("_" if ch in _UNSAFE or ord(ch) < 32 else ch for ch in last).strip()
    text = text.lstrip(".") or "file"
    return text[:120]


def _unique(folder: Path, name: str) -> Path:
    target = folder / name
    stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
    n = 2
    while target.exists():
        target = folder / (f"{stem} ({n}).{ext}" if dot else f"{name} ({n})")
        n += 1
    return target


def _place(item: dict) -> str:
    """The folders above a file as "Folder/Sub/" ("" at the top), each part made safe."""
    folders = [safe_name(part) for part in (item.get("path") or [])[:MAX_DEPTH] if isinstance(part, str)]
    return "".join(f"{part}/" for part in folders)


def _head(repo: Path | None) -> str:
    """The commit of main in `repo` (part of a view's hash), "" when there is none."""
    if repo is None or not (Path(repo) / "HEAD").is_file():
        return ""
    done = subprocess.run(["git", "-c", "safe.directory=*", f"--git-dir={repo}", "rev-parse", "-q", "--verify", "main"],
                          capture_output=True, text=True, timeout=30)
    return done.stdout.strip()


def _size(n: int) -> str:
    return f"{n / 1024 ** 2:.1f} MB" if n >= 1024 ** 2 else f"{max(1, n // 1024)} KB"


class Views:
    def __init__(self, base: str | Path, source: str | Path | None):
        self.base = Path(base) / "views"
        self.source = Path(source) if source else None
        self.lock = threading.Lock()
        self.users: dict[str, int] = {}          # view name -> jobs using it now

    def acquire(self, project_id: int, files: list, links: list, repo: Path | None = None) -> Path:
        """The view of a project with this content, made if needed; give it back with `release`."""
        project_id = int(project_id)
        content = json.dumps([files, links, _head(repo), [self._stamp(project_id, item) for item in files]],
                             sort_keys=True, default=str)
        name = f"p{project_id}-{'c' if repo is not None else 'f'}{hashlib.sha256(content.encode()).hexdigest()[:20]}"
        with self.lock:
            if not (self.path(name) / "files" / "INDEX.md").is_file():
                self.build(name, project_id, files, links, repo)
            self.users[name] = self.users.get(name, 0) + 1
            self._drop_old(project_id, keep=name)
        return self.path(name)

    def _stamp(self, project_id: int, item: dict) -> list:
        """When the stored file last changed (a memory file edited to the same size is new content too)."""
        try:
            info = (self.source / str(int(project_id)) / str(int(item["id"]))).stat() if self.source else None
        except (OSError, KeyError, TypeError, ValueError):
            info = None
        return [info.st_mtime_ns, info.st_size] if info else []

    def release(self, root: Path) -> None:
        with self.lock:
            name = Path(root).name
            self.users[name] = max(0, self.users.get(name, 0) - 1)

    def _drop_old(self, project_id: int, keep: str) -> None:
        """Views of the project with other contents that no job uses any more."""
        for folder in self.base.glob(f"p{int(project_id)}-*") if self.base.is_dir() else ():
            if folder.name != keep and not self.users.get(folder.name):
                shutil.rmtree(folder, ignore_errors=True)
                self.users.pop(folder.name, None)

    def remove_project(self, project_id: int) -> bool:
        """The project was deleted: all its views go. True if none is left."""
        with self.lock:
            for folder in self.base.glob(f"p{int(project_id)}-*") if self.base.is_dir() else ():
                shutil.rmtree(folder, ignore_errors=True)
                self.users.pop(folder.name, None)
            return not any(self.base.glob(f"p{int(project_id)}-*")) if self.base.is_dir() else True

    def path(self, name: str) -> Path:
        if not name.replace("-", "").isalnum():
            raise ValueError("bad view name")
        return self.base / name

    def build(self, name: str, project_id: int, files: list, links: list, repo: Path | None = None) -> Path:
        """Make the view of one job (`name` like "run-12" or "chat-7") and return its folder."""
        root = self.path(name)
        self.remove(name)
        (root / "files").mkdir(parents=True)
        index, used = [], 0
        for item in list(files)[:MAX_FILES]:
            label = item.get("area") if item.get("area") in LABELS else "documents"
            size, shown = int(item.get("size") or 0), safe_name(item.get("name", ""))
            place = _place(item)
            src = self.source / str(int(project_id)) / str(int(item["id"])) if self.source else None
            if src is None or not src.is_file():
                index.append(f"- {place}{shown} ({label}, {_size(size)}, not available)")
                continue
            folder = root / "files" / place if place else root / "files"
            if size > MAX_FILE or used + size > MAX_TOTAL:
                line, name = f"- {place}{shown} ({label}, {_size(size)}, too big to give here", shown
            else:
                folder.mkdir(parents=True, exist_ok=True)
                target = _unique(folder, shown)
                if target.name in ("INDEX.md", "LINKS.md") and not place:   # the hub's own lists keep their names
                    target = _unique(folder, f"{target.stem} (2){target.suffix}")
                shutil.copyfile(src, target, follow_symlinks=False)
                used += size
                line, name = f"- {place}{target.name} ({label}, {_size(size)}", target.name
            picture = src.with_name(f"{src.name}.preview")
            if picture.is_file() and not picture.is_symlink() and used + picture.stat().st_size <= MAX_TOTAL:
                folder.mkdir(parents=True, exist_ok=True)
                jpeg = _unique(folder, f"{name}.jpg")
                shutil.copyfile(picture, jpeg, follow_symlinks=False)
                used += jpeg.stat().st_size
                line += f"; to look at: {place}{jpeg.name}"
            index.append(line + ")")
        (root / "files" / "INDEX.md").write_text(
            "# Files of the project (read-only)\n\n" + ("\n".join(index) or "(none)") + "\n", encoding="utf-8")
        lines = [f"- {_place(link)}{str(link.get('name', '')).strip() or 'Link'}: {str(link.get('url', '')).strip()}"
                 for link in links if str(link.get("url", "")).startswith(("http://", "https://"))]
        (root / "files" / "LINKS.md").write_text(
            "# Links of the project\n\n" + ("\n".join(lines) or "(none)") + "\n", encoding="utf-8")
        if repo is not None:
            self._code(repo, root / "code")
        for folder in [root, *[p for p in root.rglob("*") if p.is_dir()]]:
            os.chmod(folder, 0o755)
        for item in root.rglob("*"):
            if item.is_file():
                os.chmod(item, 0o444)
        return root

    @staticmethod
    def _code(repo: Path, target: Path) -> None:
        """main of the repository as plain files (no .git); nothing if the project has no code yet or it is too big."""
        target.mkdir()
        if not (repo / "HEAD").is_file():
            return
        with tempfile.TemporaryFile() as tar:
            done = subprocess.run(["git", "-c", "safe.directory=*", f"--git-dir={repo}", "archive", "--format=tar",
                                   "main"], stdout=tar, stderr=subprocess.DEVNULL, timeout=120)
            if done.returncode or tar.tell() > MAX_CODE:
                return
            tar.seek(0)
            with tarfile.open(fileobj=tar) as archive:
                archive.extractall(target, filter="data")   # plain files only: no links out, no devices

    def remove(self, name: str) -> None:
        shutil.rmtree(self.path(name), ignore_errors=True)

    def clear(self) -> None:
        """Views left over from a runner that stopped in the middle of a job."""
        shutil.rmtree(self.base, ignore_errors=True)
