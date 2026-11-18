"""A throwaway hub to look at the thoughts in the manager chat in a browser (nothing real: an empty database in a
temporary folder, no AI). One answered question with thoughts, one that is being answered; after /tmp/go appears, the
running one gets a thought every two seconds and its answer after twenty. Run in the web image:
python tests/preview_chat.py [de|en], then open port 8000 with the login printed at the start."""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, "/app")
os.environ.setdefault("HUB_DB", tempfile.mkdtemp() + "/p.db")
try:
    import pyrage  # noqa: E402
    os.environ.setdefault("HUB_VAULT_PUBLIC", str(pyrage.x25519.Identity.generate().to_public()))
except ImportError:
    pass
from app import chat, claude_link, db, projects, users  # noqa: E402

db.DB_PATH = os.environ["HUB_DB"]
password = os.environ.get("PREVIEW_PASSWORD") or "Prev!" + os.urandom(6).hex()
user = users.create_user("preview@example.com", password, role="owner")
users.set_profile(user.id, "Janis", sys.argv[1] if len(sys.argv) > 1 else "de")
project = projects.create_project(user.id, "Roadster")
claude_link.begin(user.id)
claude_link.complete(user.id, True)
first = chat.send(user.id, project.id, "Welches Relais nehme ich für die Sitzheizung?")
chat.claim_next()
chat.add_thoughts(first.id, "\n\nDie Sitzheizung zieht etwa 4 A je Sitz bei 12 V. Zwei Sitze, also rund 8 A, dazu "
                  "Einschaltstrom.\n\nIm Projekt steht ein Datenblatt für ein 30-A-Relais; das reicht mit Reserve. "
                  "Ich sollte noch auf die Sicherung hinweisen.")
chat.finish(first.id, True, "Nimm das **30-A-Relais** aus deinem Datenblatt, das hat genug Reserve. "
            "Sichere jeden Sitz einzeln mit 10 A ab.")
second = chat.send(user.id, project.id, "Und wie schließe ich es an?")
chat.claim_next()
chat.add_thoughts(second.id, "\n\nEr fragt nach dem Anschluss. Zuerst Klemme 30, 85, 86 und 87 klären.")
STEPS = ["Klemme 30 kommt über die Sicherung an Dauerplus.", "Klemme 87 geht zu den Heizmatten.",
         "Die Spule (85/86) schaltet der Schalter im Armaturenbrett.", "Eine Freilaufdiode ist bei einem Relais mit "
         "eingebauter Diode nicht nötig.", "Ich fasse das in vier Schritten zusammen."]


def later():
    while not os.path.exists("/tmp/go"):
        time.sleep(0.5)
    for step in STEPS:
        time.sleep(2)
        chat.add_thoughts(second.id, " " + step)
    time.sleep(6)
    chat.finish(second.id, True, "1. Klemme 30 über eine 20-A-Sicherung an Dauerplus.\n2. Klemme 87 zu den Heizmatten.\n"
                "3. Klemme 86 an den Schalter, 85 an Masse.\n4. Prüfen, bevor die Sitze wieder eingebaut werden.")


threading.Thread(target=later, daemon=True).start()
print(f"preview: preview@example.com / {password} , project {project.id}", flush=True)
import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
