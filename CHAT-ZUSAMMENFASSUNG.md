# Agent-Hub – Übergabe an einen neuen Chat

Stand: 14.11.2026 (letzter Merge `download-marked`, 366 Web-Tests grün) · Zweck: Einstieg in einen neuen Chat oder auf einem anderen Rechner. Quelle der Wahrheit: `PROJEKT.md` („Auf einen Blick“, **Abschnitt 11b für die Dateiablage**, Änderungsprotokoll in Abschnitt 12), `KONZEPT-AGENTEN.md` (Agenten, Netz, Geräte, Mac, Dateizugriff), `DESIGN.md` (Gestaltung) und `CLAUDE.md` (Regeln). Frühere Übergaben liegen im Ordner `archiv/`.

## In einem Satz

Ein selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B (1 GB, per WLAN), live unter `https://hub.janis-home.de`: Projekte als Kacheln, Board für Software, pro Projekt ein Manager (Chat mit dem eigenen Claude) und eine Dateiablage, später feste KI-Agenten. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was am 13./14.11.2026 dazugekommen ist (Einzelheiten im Änderungsprotokoll)

- **Hochladen neu** (`upload-stream`): Der Server schreibt jede Anfrage beim Eintreffen direkt auf die Platte (`files.Run`) und behält bei einem Abbruch alle ganzen Blöcke, die ankamen; der Browser fragt nach einem Fehler, was da ist, und schickt nur den Rest. Große Dateien brechen nicht mehr ab.
- **Tunnel auf HTTP/2** (mit Janis’ Ja, Einstellung außerhalb des Repos in `/home/admin/cloudflared/compose.yml`, Sicherung `compose.yml.before-http2`): Über QUIC (UDP) per WLAN kamen insgesamt nur 0,3 MB/s an, jetzt etwa 5 MB/s. Das ist die Grenze von Janis’ Anschluss bis Cloudflare (Speedtest von Cloudflare: 42,8 Mbit/s hinauf). Mehr Anfragen gleichzeitig (12 statt 6) brachten nichts, nur Last auf dem Pi. Arbeitsspeicher ist nicht der Engpass.
- **Einstellung „Hochladen“** (`upload-settings`): Verwaltungsseite, Block System (nur Owner): Gleichzeitig (Standard 6) und Größtes Stück (Standard 32 MB; Stufen unter den Cloudflare-Grenzen je Anfrage: Free/Pro 100 MB, Business 200, Enterprise 500). Je Feld ein **„i“** (`.info-dot`) mit der Erklärung als eigener Hinweis, kein fester Textblock. Neue Tabelle `server_settings`, Modul `serversettings.py`.
- **Gleiche Namen** (`same-names`): Vor dem Hochladen prüft der Server die Namen im Zielbereich; Dialog „Gibt es schon“ mit Beide behalten („Name (2)“), Ersetzen (alte Datei erst nach vollständigem Upload gelöscht), Überspringen. Umbenennen auf einen vorhandenen Namen wird abgelehnt.
- **Mehrere Markierte heraus** (`zip-out`, `download-marked`): beim Hinausziehen als ein ZIP, das beim Senden entsteht (Chrome, Edge); die Zeilen fliegen dabei wie im Finder zu einem Stapel zusammen. In jedem Browser: das dezente Download-Symbol links neben dem Papierkorb, solange Dateien markiert sind.
- **Bestätigt:** Originale werden immer unverändert gespeichert; Vorschaubilder sind eigene kleine JPEGs (96 px).
- **Aufgeräumt** (mit Janis’ Ja): alter Compose-Ordner in `/opt/agent-hub`, doppelte Tunnel-Compose mit `whoami`, alte Images (etwa 1 GB), das Volume `agent-hub_claude-home`, 85 gemergte lokale und 3 gemergte GitHub-Branches; im Code ungenutzte Upload-Werte in `files.js`.

## Entscheidungen von Janis (alle in PROJEKT.md oder DESIGN.md)

- Kein Direktweg im Heimnetz: eine einheitliche Lösung über den Tunnel, große Uploads sind selten.
- Keine Prüfsumme über ganze Dateien (die Übertragung ist abgesichert, der Hub zählt nur ganze Blöcke).
- Erklärungen für schwierige Einstellungen über ein „i“, nicht als fester Textblock (DESIGN.md Abschnitt 4).
- Bewegungen beim Ziehen „Apple-like“ (Federn, DESIGN.md Abschnitt 6).

## Einstieg in einen neuen Chat

1. `CLAUDE.md` (Regeln), dann `PROJEKT.md` „Auf einen Blick“ und **Abschnitt 11b**, dann diese Datei.
2. Für Agenten, Netz, Geräte, Mac und den Dateizugriff der KI: `KONZEPT-AGENTEN.md`. Für Oberflächen: `DESIGN.md`.
3. Code: Der iCloud-Ordner enthält nur die Doku; der Code liegt im Klon auf dem Pi (`/opt/agent-hub/workspaces/agent-hub`, `main`). Auf dem PC gibt es kein Git.
4. **Als Nächstes (Janis’ Reihenfolge):** Ordner und Unterordner mit Leiste **samt Hochladen ganzer Ordner** (Plan in PROJEKT.md 11b, Punkt 1), danach der KI-Zugriff über den eingehängten Ordner (Punkt 2).

## Wie Claude hier arbeitet (Kurzfassung)

- Deutsch antworten, kurz erklären, **keine Verständnisfragen am Ende**; erst Schnittstelle zeigen, dann Code; kleinste Lösung; ein Thema pro Commit, ein Branch pro Aufgabe.
- Commit, Merge, Push, Deploy und Tests ohne Rückfrage, danach berichten. Fragen nur bei Berechtigungen, Sicherheit, Design und Features. `sudo`, Netz, Löschen vorher bestätigen lassen.
- **ssh vom PC:** Skript schreiben, `scp` nach `/tmp`, `bash /tmp/skript.sh`; nie verschachtelte Anführungszeichen.
- **Tests:** immer mit leerem `/data` (`-v "$(mktemp -d -p "$HOME"):/data"`; `/tmp` auf dem Pi ist zu klein für große Testdateien); HTTP-Test `web/tests/integration_files.py` in einem Wegwerf-Container ohne Port; Upload-Motor mit `web/tests/upload_engine/` (acht Szenarien, lokal auf dem PC).
- **Vorschau** der Oberfläche: `web/tests/preview_files.py` im Container rendern, per `scp -r` auf den PC, `py -m http.server <Port> --bind 127.0.0.1`, im eingebauten Browser ansehen. Achtung Browser-Cache: Die Seite bindet Skripte mit Inhalts-Hash ein; nach Änderungen einen neuen Port nehmen oder die Adresse in der Vorschau ändern.
- **Messen beim Upload:** `docker compose logs web | grep "upload run"` (Bytes, Sekunden, MB/s je Anfrage), im Browser `window.__uploadLog`.
- Nach Doku-Änderungen `CLAUDE.md`, `PROJEKT.md`, `DESIGN.md`, `KONZEPT-AGENTEN.md` und diese Datei in den iCloud-Projektordner kopieren.

## Wo wir stehen

- **Live und getestet:** siehe „Auf einen Blick“; 366 Web-Tests grün; Upload-Motor acht Browser-Szenarien grün; HTTP-Test der Dateiablage grün.
- **Nicht geprüft:** „Ersetzen“ an einem echten Upload, Ablegen des ZIPs auf dem Desktop und der Download über das Symbol im echten Browser, Hell-Stil und Handy der neuen Einstellung, Berührung am Handy.
- **Offen bei Janis:** die am 13.11.2026 verlorenen Dateien aus dem Backup holen (braucht `sudo`), Tunnel-Token erneuern, eine Gruppe doppelter Namen in den echten Daten (eine Datei umbenennen oder löschen).
- **Offen, nicht gebaut:** Ordner und Unterordner samt Ordner-Upload, KI-Zugriff über den eingehängten Ordner, Verschieben Markierter, Geräteliste, Schleife der Agentenläufe, Statusmeldung und Kachel-Infos, Verbrauchsanzeige, Mac-Programm, Superadmin, modulare Modellauswahl.
