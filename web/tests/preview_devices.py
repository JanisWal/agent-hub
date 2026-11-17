"""A throwaway hub with sample devices and a written status, to look at the Manager view in a browser (nothing real:
an empty database in a temporary folder). Run in the web image: python tests/preview_devices.py, then open port 8000.
Sign in with the e-mail and password printed at the start."""
import os
import sys
import tempfile
import time

sys.path.insert(0, "/app")
os.environ.setdefault("HUB_DB", tempfile.mkdtemp() + "/p.db")
import pyrage  # noqa: E402

os.environ.setdefault("HUB_VAULT_PUBLIC", str(pyrage.x25519.Identity.generate().to_public()))
from app import board, db, devices, projects, users  # noqa: E402

db.DB_PATH = os.environ["HUB_DB"]
password = os.environ.get("PREVIEW_PASSWORD") or "Prev!" + os.urandom(6).hex()
user = users.create_user("preview@example.com", password, role="owner")
users.set_profile(user.id, "Janis", sys.argv[1] if len(sys.argv) > 1 else "de")
project = projects.create_project(user.id, "Roadster")
board.create_item(user.id, project.id, "bug", "Heizung schaltet nicht ab")
pi = devices.create(user.id, project.id, "Server", "server.fritz.box", "Der Hub selbst", kind="raspberry_pi", ssh_user="pi")
devices.trust_host(user.id, pi.id, "ssh-ed25519 AAAA", "SHA256:4Hn0bQm2x9LkFz1o0c8uR6sWkq3yTt7VYpZcE5aJx2M", "192.168.178.20")
devices.set_system(user.id, pi.id, "debian", "Debian GNU/Linux 13 (trixie)", True)
devices.set_updates(user.id, pi.id, found=4)
display = devices.create(user.id, project.id, "Küche", "kueche.fritz.box", "Raspberry Pi, wird mein Display", kind="raspberry_pi")
devices.set_ip_hint(user.id, display.id, "192.168.178.31")
for name, kind in (("Werkstatt-PC", "windows_pc"), ("NAS", "linux_server"), ("MacBook", "mac"), ("ESP32 Heizung", "microcontroller"),
                   ("Fritzbox", "router"), ("Steckdose", "other"), ("Linux-Laptop", "linux_pc"), ("Build-Server", "windows_server")):
    devices.create(user.id, project.id, name, name.lower().replace(" ", "-").replace("ü", "ue") + ".local", kind=kind)
devices.set_ai(user.id, pi.id, ["reboot", "updates_check"], False)
with db.connect() as conn:
    devices.request_action(conn, user.id, project.id, "Server", "reboot", "Nach dem Kernel-Update ist ein Neustart nötig.")
    devices.set_icon_ai(conn, project.id, "NAS", "dev_storage")
with db.connect() as conn:
    conn.execute("INSERT INTO project_status (project_id, level, title, text, source, created_at) VALUES (?, 'green',"
                 " 'Heizungssteuerung im Test', 'Die Abschaltung ist eingegrenzt, ein Fehler am Relais ist offen. Als"
                 " Nächstes der Test am Fahrzeug.', 'ai', ?)", (project.id, int(time.time()) - 900))
print(f"preview: preview@example.com / {password} , project {project.id}", flush=True)
import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
