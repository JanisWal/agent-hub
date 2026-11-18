"""The read-only folders a run or a chat gets besides its work (Janis, 16.11.2026): the user's files of the project as
/files and, for the manager chat, the project's code as /code. Standard library only.

The hub sends the list (id, name, area, size; links with their address), never a path. The runner copies the files
from the hub's storage (mounted read-only into the runner at HUB_FILES_SOURCE) into one folder per job under
HUB_WORK_DIR/views/<name>/, with their real names, sorted by area and in their folders (`path`, 18.11.2026):

    files/documents/  files/media/  files/code/  files/memory/   the files (copies, never the originals)
    files/media/Backgrounds/Dark/x.png                           a file in a folder of the storage
    files/INDEX.md                                               every file with area and size, also those left out
    files/LINKS.md                                               the links: title and address
    code/                                                        main of the project's repository (manager chat)

The folder belongs to root and is readable by everybody (the run user only reads it); the container mounts it with
`readonly`, so nothing written there can reach the hub. A copy instead of the original: the storage folders are only
the hub's (0700), and a run must never see the other files of the storage. Files above MAX_FILE and anything beyond
MAX_TOTAL are left out (named in INDEX.md). The view is deleted when the job ends; `clear` removes leftovers.

A TIFF, HEIC or raw photo can not be shown to a model as it is. The browser already made a big JPEG of it for the
viewer (`<id>.preview` next to the file in the storage, web/app/files.py); it is copied next to the photo as
"<name>.jpg", so every AI can look at it (18.11.2026).
"""
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

AREAS = ("documents", "media", "code", "memory")
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


def _size(n: int) -> str:
    return f"{n / 1024 ** 2:.1f} MB" if n >= 1024 ** 2 else f"{max(1, n // 1024)} KB"


class Views:
    def __init__(self, base: str | Path, source: str | Path | None):
        self.base = Path(base) / "views"
        self.source = Path(source) if source else None

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
            area = item.get("area") if item.get("area") in AREAS else "documents"
            size, shown = int(item.get("size") or 0), safe_name(item.get("name", ""))
            folders = [safe_name(part) for part in (item.get("path") or [])[:MAX_DEPTH] if isinstance(part, str)]
            place = "/".join([area, *folders])
            src = self.source / str(int(project_id)) / str(int(item["id"])) if self.source else None
            if src is None or not src.is_file():
                index.append(f"- {place}/{shown} ({_size(size)}, not available)")
                continue
            folder = root / "files" / place
            if size > MAX_FILE or used + size > MAX_TOTAL:
                line, name = f"- {place}/{shown} ({_size(size)}, too big to give here", shown
            else:
                folder.mkdir(parents=True, exist_ok=True)
                target = _unique(folder, shown)
                shutil.copyfile(src, target, follow_symlinks=False)
                used += size
                line, name = f"- {place}/{target.name} ({_size(size)}", target.name
            picture = src.with_name(f"{src.name}.preview")
            if picture.is_file() and not picture.is_symlink() and used + picture.stat().st_size <= MAX_TOTAL:
                folder.mkdir(parents=True, exist_ok=True)
                jpeg = _unique(folder, f"{name}.jpg")
                shutil.copyfile(picture, jpeg, follow_symlinks=False)
                used += jpeg.stat().st_size
                line += f"; to look at: {place}/{jpeg.name}"
            index.append(line + ")")
        (root / "files" / "INDEX.md").write_text(
            "# Files of the project (read-only)\n\n" + ("\n".join(index) or "(none)") + "\n", encoding="utf-8")
        lines = [f"- {str(link.get('name', '')).strip() or 'Link'}: {str(link.get('url', '')).strip()}"
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
