"""Renders the project page with sample files for a look in the browser (throwaway database, nothing real)."""
import os
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, "/app")
from app import db, files, projects, users  # noqa: E402
from app.routes import projects as project_routes  # noqa: E402

out = Path(sys.argv[1])
lang = sys.argv[2] if len(sys.argv) > 2 else "de"
db.DB_PATH = tempfile.mkdtemp() + "/p.db"
files.FILES_DIR = out / "files"
files.free_bytes = lambda: 10 ** 12


def png(w=96, h=96):
    rows = b"".join(b"\x00" + b"".join(bytes((230 - y, 130 + x // 2, 90 + (x + y) // 3)) for x in range(w)) for y in range(h))
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


user = users.create_user("janis@example.com", "Aaaa!pass12")
users.set_profile(user.id, "Janis", lang)
user = users.get_by_id(user.id)
project = projects.create_project(user.id, "Roadster")


def put(name, data):
    item = files.start_upload(user.id, project.id, name, len(data))
    files.append_chunk(user.id, item.id, 0, data)
    return files.finish_upload(user.id, item.id)


put("stand.md", b"# Stand\n\nHeizung verkabelt.\n")
put("ideen.md", b"- Relais pruefen\n")
put("controller.py", b"print(1)\n")
put("schaltplan-heizung.png", png())
put("einbau-test.mp4", b"\x00" * 148_000)
put("sprachmemo.m4a", b"x" * 1_100_000)
put("Anleitung Relais.pdf", b"x" * 2_400_000)
put("sehr-langer-dateiname-der-nicht-in-die-zeile-passt-und-abgeschnitten-werden-muss.pdf", b"x" * 5)
files.add_link(user.id, project.id, "https://docs.example.com/relay-guide", "Relais-Anleitung")
files.add_link(user.id, project.id, "https://www.youtube.com/watch?v=abc", "YouTube-Video")
for n in range(1, 31):
    put(f"bild-{n:02d}.png", png())

# Sample agent runs for the role views (15.11.2026): one task waits for approval, one is with the tester right now.
from app import agents, board, claude_link  # noqa: E402
claude_link.begin(user.id)
claude_link.complete(user.id, True)
REPORTS = {
    "programmer": "Relais-Steuerung gebaut: `relay.py` schaltet über GPIO 17, mit Unittest.\n\n- Entprellen 50 ms\n- Offen: nichts",
    "tester": "Alle 6 Tests laufen durch. Von Hand geprüft: Ein, Aus, schnelles Umschalten.",
    "reviewer": "Sauber aufgebaut. Kleinigkeit: die Pin-Nummer als Konstante oben in der Datei.",
}
first = board.create_item(user.id, project.id, "minor", "Relais per Knopf schalten")
agents.start_task(user.id, project.id, first.id)
for role, result in (("programmer", "done"), ("tester", "pass"), ("reviewer", "ok")):
    job = agents.claim_next(can_mac=True)
    agents.finish_run(job.run_id, result, REPORTS[role], tokens_in=52317, tokens_out=2049, seconds=28)
second = board.create_item(user.id, project.id, "bug", "Anzeige flackert beim Start")
agents.start_task(user.id, project.id, second.id)
job = agents.claim_next(can_mac=True)
agents.finish_run(job.run_id, "done", "Flackern behoben: Puffer wird vor dem ersten Bild geleert.", tokens_in=40100,
                  tokens_out=900, seconds=19)
agents.claim_next(can_mac=True)   # the tester's run is going

from app import todos  # noqa: E402
todos.create(user.id, project.id, "Sicherung 10 A im Motorraum nachrüsten")
todos.create(user.id, project.id, "Temperaturfühler an der Heizung festkleben", source="tester")
done = todos.create(user.id, project.id, "Kabel zur Heizung verlegen")
todos.finish(user.id, done, "Entlang des Rahmens verlegt, mit Kabelbindern alle 20 cm.\nStecker noch offen.")
(out / "index.html").write_text(project_routes.project_view(project.id, user), encoding="utf-8")
shutil.copytree("/app/app/static", out / "static", dirs_exist_ok=True)
os.system(f"chmod -R a+rwX {out}")
print("project", project.id)
