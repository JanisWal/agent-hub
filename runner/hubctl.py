"""Fixed actions on the server itself (27.11.2026): backup, checking and putting back a backup, and the settings that live
in `.env`. Runs as root in a short-lived container of the runner's image (launcher.build_hubctl_command), started by
the runner for a job of the hub (web/app/hostjobs.py). Standard library plus pyrage (age encryption, as in the web
service).

Why a container of its own: the web service may not touch the host, and the runner must not hold the database or `.env`.
This container sees the hub's base folder (data, logins, code of the projects, `.env`), the backup folder and the Docker
socket, does exactly one job and is gone. It is started detached, so it may stop and start the hub's services (the
runner too) while it works. Its result is a file `<data>/jobs/<id>.json` the web service reads (hostjobs.py); a put-back
backup writes `<data>/jobs/restore.json` into the data it put back, since the old database moved aside with the rest.

The backup file (format 1): `agent-hub-backup-YYYY-MM-DD-HHMM.zip.age`, a ZIP encrypted with age to the owner's recovery
key (the server keeps only the public half). Inside:
    manifest.json      format, version, created, hub version, size and sha256 of every file, counts, database schema
    database/hub.db    a consistent copy (SQLite's own backup call)
    files/...          the file storage as it is kept (data/files)
    repos/<n>.git      the code of the projects with all branches
    logins/...         the AI logins and keys (still encrypted with HUB_TOKEN_KEY, which is in secrets.env)
    secrets.env        only the keys in SECRET_KEYS; paths, port and the runner's token belong to the device
Not in it: work in progress (gitdirs/, tasks/), the Docker images, the system. By hand: `age -d -i key.txt file > x.zip`.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

FORMAT = "agent-hub-backup"
VERSION = 1
PREFIX = "agent-hub-backup-"
SUFFIX = ".zip.age"
# What moves with a backup from one server to another: what opens the saved logins and device secrets, mail and the
# public address. Never the runner's or broker's token (made new on each device), never paths or ports.
SECRET_KEYS = ("HUB_TOKEN_KEY", "HUB_VAULT_IDENTITY", "HUB_VAULT_PUBLIC", "RESEND_API_KEY", "MAIL_FROM", "HUB_BASE_URL",
               "TUNNEL_TOKEN")
# What the set-up assistant and the administration may write into .env (action "settings").
SETTING_KEYS = ("HUB_BASE_URL", "RESEND_API_KEY", "MAIL_FROM", "TUNNEL_TOKEN")
TOP = ("manifest.json", "database/", "files/", "repos/", "logins/", "secrets.env")
SERVICES = ("web", "runner", "egress", "broker")   # stopped while a backup is put back; the tunnel keeps running
WEB_UID = 9000                                     # compose.yml: the web service owns the data folder
KEEP_DAILY, KEEP_WEEKLY = 7, 4                     # as the old nightly backup (backup.sh)
KEEP_BEFORE_DAYS = 7                               # the state before a put-back backup, for going back
_VALUE = re.compile(r"[\x20-\x7e]{0,500}")         # one printable line, nothing that could add a second line to .env
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}-\d{4}")
CHUNK = 1 << 20
# Files that are compressed already are only stored: packing them again costs the Pi minutes per gigabyte and saves
# almost nothing (27.11.2026: 1.3 GB of uploads, mostly pictures and documents, took over ten minutes).
PACKED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".avif", ".mp4", ".mov", ".m4v", ".mkv", ".webm",
          ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z",
          ".rar", ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub", ".jar", ".apk", ".dmg",
          ".thumb", ".preview"}   # the hub's own small pictures of a file (web/app/files.py)


class Failed(Exception):
    """The job can not be done; `str()` is a short reason the page turns into a text (hostjobs.py)."""


class Paths:
    """The folders of this server, the same paths as on the host (the daemon mounts host paths)."""

    def __init__(self, env=os.environ):
        self.base = Path(env["HUB_BASE_DIR"])
        self.app = Path(env["HUB_APP_DIR"])          # compose.yml and .env
        self.data = Path(env["HUB_DATA_DIR"])        # hub.db, files/
        self.claude = Path(env["HUB_CLAUDE_DIR"])    # logins of the AIs
        self.work = Path(env["HUB_WORK_DIR"])        # repos/, gitdirs/, tasks/
        self.backups = Path(env["HUB_BACKUP_DIR"])
        self.name = env.get("HUB_NAME", "agent-hub")
        self.jobs = self.work / ".hubctl"            # root only: payloads, staging, the unpacked backup
        self.results = self.data / "jobs"

    @property
    def staging(self) -> Path:
        return self.jobs / "restore"


# --- small helpers -------------------------------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _walk(folder: Path):
    """Every regular file below `folder` (sorted, no links followed: a link could point anywhere on the server)."""
    if not folder.is_dir():
        return
    for root, dirs, names in os.walk(folder, followlinks=False):
        dirs.sort()
        for name in sorted(names):
            path = Path(root) / name
            if path.is_file() and not path.is_symlink():
                yield path


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                values[key.strip()] = value.strip()
    return values


def merge_env(path: Path, changes: dict[str, str | None]) -> None:
    """Set (or with None remove) keys in an .env file and keep every other line as it is. Written to a new file and
    renamed, mode 600, owner kept."""
    for key, value in changes.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) or (value is not None and not _VALUE.fullmatch(value)):
            raise Failed("bad_value")
    lines, seen = [], set()
    if path.exists():
        for line in path.read_text().splitlines():
            key = line.partition("=")[0].strip()
            if "=" in line and not line.lstrip().startswith("#") and key in changes:
                if key in seen or changes[key] is None:
                    continue
                lines.append(f"{key}={changes[key]}")
                seen.add(key)
            else:
                lines.append(line)
    lines += [f"{key}={value}" for key, value in changes.items() if key not in seen and value is not None]
    stat = path.stat() if path.exists() else None
    fresh = path.with_name(path.name + ".new")
    fresh.write_text("\n".join(lines) + "\n")
    os.chmod(fresh, 0o600)
    if stat is not None:
        os.chown(fresh, stat.st_uid, stat.st_gid)
    os.replace(fresh, path)


def _give_web(path: Path) -> None:
    """Hand a file or folder (recursively) to the web service. On a drive without owners (FAT) nothing happens."""
    try:
        os.chown(path, WEB_UID, WEB_UID)
        if path.is_dir():
            for root, dirs, names in os.walk(path):
                for name in dirs + names:
                    os.lchown(os.path.join(root, name), WEB_UID, WEB_UID)
    except (PermissionError, OSError):
        pass


def write_result(paths: Paths, name: str, result: dict) -> None:
    """The answer to the hub: `<data>/jobs/<name>.json`, readable by the web service only."""
    paths.results.mkdir(parents=True, exist_ok=True)
    _give_web(paths.results)
    target = paths.results / f"{name}.json"
    fresh = target.with_name(target.name + ".new")
    fresh.write_text(json.dumps(result))
    os.chmod(fresh, 0o600)
    _give_web(fresh)
    os.replace(fresh, target)


def compose(paths: Paths, *args: str) -> None:
    """`docker compose` for this hub (its folder, its .env, its name). Failed when it does not work."""
    done = subprocess.run(["docker", "compose", "--project-directory", str(paths.app), "-p", paths.name, *args],
                          capture_output=True, text=True, timeout=900)
    if done.returncode != 0:
        print(f"hubctl: compose {args[0]} failed: {(done.stderr or '')[-400:]}", file=sys.stderr, flush=True)
        raise Failed("compose")


def hub_version(paths: Paths) -> str:
    """The commit the hub runs (from its Git folder), or "" when it was installed without Git."""
    head = paths.app / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            target = paths.app / ".git" / ref[5:]
            if target.exists():
                return target.read_text().strip()[:40]
            packed = paths.app / ".git" / "packed-refs"
            for line in packed.read_text().splitlines():
                if line.endswith(" " + ref[5:]):
                    return line.split()[0][:40]
            return ""
        return ref[:40]
    except OSError:
        return ""


def _file_kinds(db_path: Path) -> dict[str, str]:
    """"<project>/<number>" of every stored file -> the ending of its real name (".jpg"), from the database."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {f"{pid}/{fid}": os.path.splitext(name or "")[1] for fid, pid, name in
                conn.execute("SELECT id, project_id, name FROM files WHERE is_folder = 0")}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def describe(db_path: Path) -> dict:
    """What a database holds, for the page before it is put back: counts, the owner, and the schema (table: columns),
    so the hub can refuse a backup of a newer version (a table or column it does not know)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        schema = {t: sorted(row[1] for row in conn.execute(f'PRAGMA table_info("{t}")')) for t in tables}

        def count(sql: str) -> int:
            try:
                return int(conn.execute(sql).fetchone()[0])
            except sqlite3.Error:
                return 0
        owner = conn.execute("SELECT email FROM users WHERE role = 'owner'").fetchone() if "users" in schema else None
        return {"schema": schema, "owner": owner[0] if owner else "",
                "counts": {"users": count("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL"),
                           "projects": count("SELECT COUNT(*) FROM projects"),
                           "files": count("SELECT COUNT(*) FROM files WHERE is_folder = 0")}}
    finally:
        conn.close()


# --- backup --------------------------------------------------------------------------------------------------------
def make_backup(paths: Paths, recipient: str, now: float | None = None) -> dict:
    """Write one encrypted backup into the backup folder; {"name", "size"}. Nothing half-written stays: the ZIP is built
    in the root-only job folder, the encrypted file gets its name only when complete."""
    import pyrage
    try:
        public = pyrage.x25519.Recipient.from_str(recipient.strip())
    except Exception:
        raise Failed("no_key")
    if not (paths.data / "hub.db").exists():
        raise Failed("no_data")
    when = datetime.datetime.fromtimestamp(now if now is not None else time.time())
    name = f"{PREFIX}{when:%Y-%m-%d-%H%M}{SUFFIX}"
    paths.jobs.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.jobs, 0o700)
    stage, db_copy = paths.jobs / "backup.zip", paths.jobs / "backup.db"
    try:
        src = sqlite3.connect(f"file:{paths.data / 'hub.db'}?mode=ro", uri=True)
        dst = sqlite3.connect(db_copy)
        src.backup(dst)
        dst.close()
        src.close()
        listed = {}
        with zipfile.ZipFile(stage, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            def add(path: Path, arcname: str, kind: str = "") -> None:
                digest, size = hashlib.sha256(), 0
                info = zipfile.ZipInfo(arcname, time.localtime(path.stat().st_mtime)[:6])
                info.compress_type = zipfile.ZIP_STORED if kind.lower() in PACKED else zipfile.ZIP_DEFLATED
                with open(path, "rb") as source, archive.open(info, "w", force_zip64=True) as target:
                    for block in iter(lambda: source.read(CHUNK), b""):
                        digest.update(block)
                        size += len(block)
                        target.write(block)
                listed[arcname] = {"size": size, "sha256": digest.hexdigest()}
            add(db_copy, "database/hub.db")
            kinds = _file_kinds(db_copy)   # stored files have only a number: their real name says what they are
            for folder, top in ((paths.data / "files", "files"), (paths.work / "repos", "repos"), (paths.claude, "logins")):
                for path in _walk(folder):
                    inner = path.relative_to(folder).as_posix()
                    add(path, f"{top}/{inner}", (kinds.get(inner) if top == "files" else "") or path.suffix)
            env = read_env(paths.app / ".env")
            secrets = "".join(f"{key}={env[key]}\n" for key in SECRET_KEYS if env.get(key))
            archive.writestr("secrets.env", secrets)
            listed["secrets.env"] = {"size": len(secrets.encode()), "sha256": hashlib.sha256(secrets.encode()).hexdigest()}
            facts = describe(db_copy)
            manifest = {"format": FORMAT, "version": VERSION, "created": when.isoformat(timespec="seconds"),
                        "hub": hub_version(paths), "counts": facts["counts"], "owner": facts["owner"],
                        "schema": facts["schema"], "files": listed}
            archive.writestr("manifest.json", json.dumps(manifest, indent=1))
        paths.backups.mkdir(parents=True, exist_ok=True)
        part = paths.backups / ("." + name + ".part")
        pyrage.encrypt_file(str(stage), str(part), [public])
        os.chmod(part, 0o600)
        _give_web(part)
        os.replace(part, paths.backups / name)
    finally:
        for leftover in (stage, db_copy):
            leftover.unlink(missing_ok=True)
    prune(paths.backups)
    prune_before(paths, time.time() if now is None else now)
    return {"name": name, "size": (paths.backups / name).stat().st_size}


def prune(folder: Path) -> list[str]:
    """Keep the newest KEEP_DAILY backups and, beyond those, the newest KEEP_WEEKLY made on a Sunday; the names that went."""
    found = sorted((p for p in folder.glob(PREFIX + "*" + SUFFIX) if _STAMP.fullmatch(p.name[len(PREFIX):-len(SUFFIX)])),
                   key=lambda p: p.name, reverse=True)
    gone, weekly = [], 0
    for index, path in enumerate(found):
        if index < KEEP_DAILY:
            continue
        day = datetime.date.fromisoformat(path.name[len(PREFIX):len(PREFIX) + 10])
        if day.isoweekday() == 7 and weekly < KEEP_WEEKLY:
            weekly += 1
            continue
        path.unlink()
        gone.append(path.name)
    return gone


def prune_before(paths: Paths, now: float) -> None:
    """The state before a put-back backup goes after KEEP_BEFORE_DAYS (it may hold data of deleted accounts)."""
    for folder in paths.base.glob("before-restore-*"):
        if folder.is_dir() and now - folder.stat().st_mtime > KEEP_BEFORE_DAYS * 86400:
            shutil.rmtree(folder, ignore_errors=True)


# --- put a backup back ---------------------------------------------------------------------------------------------
def _safe_name(name: str) -> bool:
    parts = name.split("/")
    return (bool(name) and not name.startswith("/") and "\\" not in name and "\x00" not in name
            and all(part not in ("", ".", "..") for part in parts[:-1]) and parts[-1] not in (".", "..")
            and any(name == top or (top.endswith("/") and name.startswith(top)) for top in TOP))


def check_restore(paths: Paths, identity: str, upload: Path) -> dict:
    """Open and check an uploaded backup; nothing of the running hub changes. Unpacked into the root-only job folder,
    a summary for the page goes to `<data>/restore/summary.json` (no secrets in it)."""
    import pyrage
    key = next((line.strip() for line in identity.splitlines() if line.strip().startswith("AGE-SECRET-KEY-")), "")
    try:
        secret = pyrage.x25519.Identity.from_str(key)
    except Exception:
        raise Failed("bad_key")
    if not upload.is_file():
        raise Failed("no_upload")
    paths.jobs.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.jobs, 0o700)
    shutil.rmtree(paths.staging, ignore_errors=True)
    opened = paths.jobs / "restore.zip"
    try:
        try:
            pyrage.decrypt_file(str(upload), str(opened), [secret])
        except Exception:
            raise Failed("wrong_key")
        try:
            archive = zipfile.ZipFile(opened)
        except zipfile.BadZipFile:
            raise Failed("damaged")
        with archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or not all(_safe_name(n) for n in names if not n.endswith("/")):
                raise Failed("damaged")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (KeyError, ValueError):
                raise Failed("damaged")
            if manifest.get("format") != FORMAT or not isinstance(manifest.get("version"), int):
                raise Failed("damaged")
            if manifest["version"] > VERSION:
                raise Failed("newer")
            listed = manifest.get("files") or {}
            files = [n for n in names if not n.endswith("/") and n != "manifest.json"]
            if set(files) != set(listed) or "database/hub.db" not in listed:
                raise Failed("damaged")
            for name in files:
                target = paths.staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest, size = hashlib.sha256(), 0
                with archive.open(name) as source, open(target, "wb") as out:
                    for block in iter(lambda: source.read(CHUNK), b""):
                        digest.update(block)
                        size += len(block)
                        out.write(block)
                if digest.hexdigest() != listed[name].get("sha256") or size != listed[name].get("size"):
                    raise Failed("damaged")
        facts = describe(paths.staging / "database" / "hub.db")
        size = sum(v.get("size", 0) for v in listed.values())
        summary = {"created": manifest.get("created", ""), "hub": manifest.get("hub", ""), "owner": facts["owner"],
                   "counts": facts["counts"], "schema": facts["schema"], "size": size,
                   "tunnel": bool(read_env(paths.staging / "secrets.env").get("TUNNEL_TOKEN"))}
        (paths.staging / ".checked").write_text(json.dumps({"at": time.time()}))
    except BaseException as problem:
        shutil.rmtree(paths.staging, ignore_errors=True)
        if str(problem) != "wrong_key":   # with the wrong key the same upload may be tried again with the right one
            upload.unlink(missing_ok=True)
        raise
    finally:
        opened.unlink(missing_ok=True)
    upload.unlink(missing_ok=True)
    folder = paths.data / "restore"
    folder.mkdir(parents=True, exist_ok=True)
    _give_web(folder)
    (folder / "summary.json").write_text(json.dumps(summary))
    _give_web(folder / "summary.json")
    return {"summary": True}


def _children(folder: Path) -> list[Path]:
    return sorted(folder.iterdir()) if folder.is_dir() else []


def apply_restore(paths: Paths, now: float | None = None) -> dict:
    """Put a checked backup in place of everything: services stop, the current state moves to
    `<base>/before-restore-<stamp>/` (back again if anything goes wrong), the backup moves in, owners are set, the
    keys from secrets.env go into .env, the services start. The result goes into the new data (`jobs/restore.json`)."""
    if not (paths.staging / ".checked").exists():
        raise Failed("not_checked")
    stamp = datetime.datetime.fromtimestamp(now if now is not None else time.time()).strftime("%Y-%m-%d-%H%M%S")
    before = paths.base / f"before-restore-{stamp}"
    places = {"data": paths.data, "claude": paths.claude, "work": paths.work}
    moved: list[tuple[Path, Path]] = []   # (where it was, where it is now): moved back on a failure
    placed: list[Path] = []               # what came from the backup: removed again on a failure
    env_before = (paths.app / ".env").read_bytes() if (paths.app / ".env").exists() else None
    compose(paths, "stop", *SERVICES)
    try:
        before.mkdir(mode=0o700)
        for label, folder in places.items():
            (before / label).mkdir()
            for child in _children(folder):
                if label == "work" and child.name not in ("repos", "gitdirs", "tasks"):
                    continue   # the job folder (.hubctl) holds the backup being put back
                os.rename(child, before / label / child.name)
                moved.append((child, before / label / child.name))
        incoming = [(paths.staging / "database" / "hub.db", paths.data / "hub.db"),
                    (paths.staging / "files", paths.data / "files"), (paths.staging / "repos", paths.work / "repos")]
        incoming += [(child, paths.claude / child.name) for child in _children(paths.staging / "logins")]
        for source, target in incoming:
            if source.exists():
                os.rename(source, target)
                placed.append(target)
        _give_web(paths.data)
        os.chmod(paths.data / "hub.db", 0o600)
        os.chmod(paths.claude, 0o700)
        for root, dirs, names in os.walk(paths.claude):
            for name in dirs:
                os.chmod(os.path.join(root, name), 0o700)
            for name in names:
                os.chmod(os.path.join(root, name), 0o600)
        secrets = read_env(paths.staging / "secrets.env")
        changes: dict[str, str | None] = {key: secrets.get(key) for key in SECRET_KEYS}
        changes["COMPOSE_PROFILES"] = "tunnel" if secrets.get("TUNNEL_TOKEN") else None
        merge_env(paths.app / ".env", changes)
    except BaseException as problem:
        for target in placed:
            shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(missing_ok=True)
        for source, target in reversed(moved):
            os.rename(target, source)
        if env_before is not None:
            (paths.app / ".env").write_bytes(env_before)
        compose(paths, "up", "-d", "--no-build")
        raise Failed("apply") from problem
    shutil.rmtree(paths.staging, ignore_errors=True)
    (paths.data / "restore").mkdir(exist_ok=True)
    (paths.data / "restore" / "summary.json").unlink(missing_ok=True)
    write_result(paths, "restore", {"ok": True, "before": before.name, "at": time.time()})
    if not secrets.get("TUNNEL_TOKEN"):
        compose(paths, "rm", "-sf", "tunnel")
    compose(paths, "up", "-d", "--no-build")
    return {"before": before.name}


# --- settings in .env ----------------------------------------------------------------------------------------------
def apply_settings(paths: Paths, values: dict, saved=lambda: None) -> dict:
    """Write the allowed keys into .env and restart what reads them. An empty value removes the key. The tunnel runs
    (profile "tunnel") exactly when a token is set. `saved` is called between writing and restarting: the restart also
    restarts the web service that waits for the answer."""
    if not isinstance(values, dict) or not values or any(key not in SETTING_KEYS for key in values):
        raise Failed("bad_value")
    changes = {key: (str(value).strip() or None) for key, value in values.items()}
    merge_env(paths.app / ".env", changes)
    env = read_env(paths.app / ".env")
    profiles = [p for p in env.get("COMPOSE_PROFILES", "").split(",") if p and p != "tunnel"]
    if env.get("TUNNEL_TOKEN"):
        profiles.append("tunnel")
    merge_env(paths.app / ".env", {"COMPOSE_PROFILES": ",".join(profiles) or None})
    saved()
    if not env.get("TUNNEL_TOKEN"):
        compose(paths, "rm", "-sf", "tunnel")
    compose(paths, "up", "-d", "--no-build")
    return {"saved": sorted(values)}


# --- one job -------------------------------------------------------------------------------------------------------
def run(paths: Paths, job_id: int) -> int:
    """Do the job `<work>/.hubctl/<id>.json` (written by the runner, deleted here at once: it may hold a key) and leave
    the result for the hub. The exit code says how it went."""
    payload_file = paths.jobs / f"{int(job_id)}.json"
    try:
        job = json.loads(payload_file.read_text())
    except (OSError, ValueError):
        write_result(paths, str(job_id), {"ok": False, "reason": "no_job"})
        return 1
    finally:
        payload_file.unlink(missing_ok=True)
    action, data = job.get("action"), job.get("payload") or {}
    try:
        if action == "backup":
            result = make_backup(paths, str(data.get("recipient", "")))
        elif action == "restore-check":
            result = check_restore(paths, str(data.get("identity", "")), paths.data / "restore" / "upload.age")
        elif action == "restore-apply":
            result = apply_restore(paths)
            return 0   # the result is in the new data (jobs/restore.json); this job's database moved aside
        elif action == "settings":
            values = data.get("values")
            apply_settings(paths, values, lambda: write_result(paths, str(job_id), {"ok": True, "saved": sorted(values)}))
            return 0
        else:
            raise Failed("unknown")
    except Failed as problem:
        reason = str(problem)
        if action == "restore-apply":
            write_result(paths, "restore", {"ok": False, "reason": reason, "at": time.time()})
        else:
            write_result(paths, str(job_id), {"ok": False, "reason": reason})
        return 1
    except Exception as problem:   # never without an answer (CLAUDE.md: background work always reports its end)
        print(f"hubctl: {action} broke: {type(problem).__name__}: {problem}", file=sys.stderr, flush=True)
        write_result(paths, "restore" if action == "restore-apply" else str(job_id), {"ok": False, "reason": "broke"})
        return 1
    write_result(paths, str(job_id), {"ok": True, **result})
    return 0


if __name__ == "__main__":
    sys.exit(run(Paths(), int(sys.argv[1])))
