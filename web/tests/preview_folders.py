"""A throwaway hub with sample files in folders, to look at the file tile and its explorer in a browser (nothing real:
an empty database in a temporary folder). Run in the web image: python tests/preview_folders.py [de|en], then open
port 8000. Sign in with the e-mail and password printed at the start."""
import os
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, "/app")
os.environ.setdefault("HUB_DB", tempfile.mkdtemp() + "/p.db")
try:
    import pyrage  # noqa: E402
    os.environ.setdefault("HUB_VAULT_PUBLIC", str(pyrage.x25519.Identity.generate().to_public()))
except ImportError:
    pass
from app import db, files, projects, users  # noqa: E402

db.DB_PATH = os.environ["HUB_DB"]


def png(rgb: bytes, size: int = 64) -> bytes:
    raw = b"".join(b"\x00" + rgb * size for _ in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def put(user, project, name, data, folder=None):
    item = files.start_upload(user.id, project.id, name, len(data), folder_id=folder)
    files.append_chunk(user.id, item.id, 0, data)
    return files.finish_upload(user.id, item.id)


password = os.environ.get("PREVIEW_PASSWORD") or "Prev!" + os.urandom(6).hex()
user = users.create_user("preview@example.com", password, role="owner")
users.set_profile(user.id, "Janis", sys.argv[1] if len(sys.argv) > 1 else "de")
project = projects.create_project(user.id, "Roadster")
backgrounds = files.create_folder(user.id, project.id, "Hintergründe")
dark = files.create_folder(user.id, project.id, "Dunkel", backgrounds.id)
files.create_folder(user.id, project.id, "Hell", backgrounds.id)
display = files.create_folder(user.id, project.id, "Anzeige")
files.create_folder(user.id, project.id, "Zeiger")
put(user, project, "nacht.png", png(b"\x10\x18\x40"), dark.id)
put(user, project, "abend.png", png(b"\x60\x20\x50"), dark.id)
put(user, project, "tacho.png", png(b"\xe0\x80\x20"), display.id)
put(user, project, "logo.png", png(b"\x20\xa0\x60"))
docs = files.create_folder(user.id, project.id, "Datenblätter")
put(user, project, "Relais 12V.pdf", b"%PDF-1.4 sample", docs.id)
put(user, project, "Schaltplan.pdf", b"%PDF-1.4 sample")
code = files.create_folder(user.id, project.id, "Struktur")
put(user, project, "heizung.py", b"ON = True\n", code.id)
files.add_link(user.id, project.id, "https://example.org/relais", "Relais-Anleitung")
print(f"preview: preview@example.com / {password} , project {project.id}", flush=True)
import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
