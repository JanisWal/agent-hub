# Agent-Hub – Konzept: Claude-Instanzen und Zusammenarbeit der Agenten

Stand: 14.11.2026 (Abschnitt 9: Konzept für den KI-unabhängigen Ablauf) · zuerst 07.11.2026, Branch `agent-core` · Ergänzt PROJEKT.md (Abschnitte 3 und 5). Hier steht die Logik hinter dem Bereich „Projekte“; das Aussehen kommt später (DESIGN.md).

## 1. Überblick

Drei Bausteine, jeder ein Modul, alle ohne Abhängigkeit von außen:

| Baustein | Aufgabe | Datei |
|---|---|---|
| Claude-Verbindung | pro Nutzer ein eigenes Claude, Zustand und Anmelde-Ablauf | `claude_link.py` |
| Kette der Agenten | wer nach wem arbeitet, Rückläufe, Limits (reine Zustandsmaschine) | `workflow.py` |
| Aufgaben und Läufe | Warteschlange in SQLite, Einstellungen pro Nutzer, Auftragsvergabe an den Runner | `agents.py` |

**Gebaut und getestet (Branch `agent-core`):** die drei Module, die Tabellen, die HTTP-Schnittstelle des Runners (`routes/runner.py`, mit Token), der Launcher für den Container je Lauf (`runner/launcher.py`) und das Image dafür (`runner/Dockerfile`, `agent-hub-agent`), dazu 173 Hub-Tests und 11 Launcher-Tests, darunter ein Fall in `test_isolation.py`. **Noch nicht gebaut:** die Schleife des Runners (Aufträge holen, Prompt bauen, Lauf starten, Ergebnis melden), Git-Arbeitsordner und Merge, die Oberfläche. Anmeldung und Trennen laufen seit dem 07.11.2026 live (Abschnitt 7a); der Rest (Kette, Läufe) ist gemergt, aber noch ohne Runner-Schleife und ohne Oberfläche, also nicht wirksam.

## 2. Claude-Instanzen (eine pro Nutzer)

> **Stand 14.11.2026:** Die Anmeldung läuft nicht mehr über `claude auth login` und Claude Codes eigenen Ordner, sondern über `claude setup-token` (ein Jahr), verschlüsselt beim Runner, Läufe nur mit Ticket über den Gateway. Ablauf und Grenzen: PROJEKT.md Abschnitt 3, „Claude-Anmeldung und Tokens, so gebaut“. Der Text unten beschreibt den alten Weg.

- **Zustand:** `none` → `connecting` → `connected` → `expired` → `connecting` … (Tabelle `claude_connections`). Die Datenbank speichert nur den Zustand und den kurzlebigen Anmelde-Link, **nie** Token oder Code.
- **Zugangsdaten** legt Claude Code selbst in den Ordner des Nutzers: `claude_link.config_dir(user_id)` = `/data/claude/<user_id>/` (`CLAUDE_CONFIG_DIR` und `HOME` seiner Läufe). Der Web-Container hängt diesen Ordner nicht ein, nur der Runner.
- **Ablauf der Anmeldung** (der Nutzer gibt nie Benutzername oder Passwort ein; Knopf „Verknüpfen“ in der Schublade, Dialog in DESIGN.md Abschnitt 10):
  1. Nutzer drückt „Verknüpfen“ → `POST /claude/connect` → `begin(user_id)`, Zustand `connecting`.
  2. Der Runner fragt alle 2 Sekunden `GET /runner/logins`, startet für diesen Nutzer einen Container mit `claude auth login --claudeai` (Pseudo-Terminal, nur sein Claude-Ordner eingehängt) und liest den Link aus der Ausgabe („If the browser didn't open, visit: …“, auch in einem OSC-8-Hyperlink) → `set_login_url` (nur `https` zu claude.ai, claude.com oder anthropic.com, sonst abgelehnt).
  3. Der Dialog fragt `GET /claude/status`, zeigt den Link und das Feld „Code“. Der Nutzer bestätigt bei Claude und gibt den Code ein → `POST /claude/code`.
  4. Der Code geht **flüchtig** (nur im Arbeitsspeicher des Hubs, nie in Datenbank oder Log) an den Runner, der ihn in das Terminal des Containers tippt („Paste code here if prompted >“). Beendet sich Claude Code mit Erfolg, meldet der Runner `complete(user_id, True)`, sonst (falscher Code, 90 Sekunden ohne Ergebnis) `False`.
  5. Wer 10 Minuten nichts bestätigt, fällt auf `none` zurück (`CONNECT_TIMEOUT`). Schließen des Dialogs bricht die Anmeldung ab.
  - **Geprüft auf dem Pi** (Wegwerf-Hub auf `127.0.0.1:8001`, Testkonto, echter Runner und echter Anmelde-Container): Link kommt von claude.com beim Hub an, die Schublade zeigt „Wird verknüpft“, ein absichtlich falscher Code endet als „nicht verknüpft“, kein Container bleibt übrig. **Nicht geprüft:** der Erfolgsweg mit einem echten Code (das kann nur Janis mit seinem Konto) und ob die Anmeldung dauerhält.
- **Abgelaufen:** Meldet Claude Code „nicht angemeldet“, setzt der Runner `mark_expired`. Die Aufgaben des Nutzers warten dann (`waiting_reason` = `no_claude`), die Maske zeigt „Verbindung abgelaufen“ mit Knopf zum Erneuern.
- **Trennen:** `disconnect(user_id)` setzt den Eintrag auf „wipe“: für den Nutzer ist es sofort `none`, der Runner löscht daraufhin den Claude-Ordner (`GET /runner/wipes`, `POST /runner/wipes/{id}/done`) und erst dann vergisst der Hub die Zeile. Der Runner meldet „fertig“ nur, wenn der Ordner wirklich weg ist; sonst bleibt „wipe“ und er versucht es erneut. So bleibt nie eine gespeicherte Anmeldung zurück, obwohl der Nutzer getrennt hat (der Web-Container kommt an den Ordner nicht heran). **Konto löschen** geht denselben Weg: `users.delete_user` legt in derselben Transaktion einen Eintrag in `claude_wipes` an (ohne Fremdschlüssel, die Nutzerzeile ist ja weg), der Runner löscht den Ordner. Was beim Trennen **nicht** verschwindet: Fragen und Antworten des Testfensters, Aufgaben und Berichte der Agenten; sie gehören zum Projekt und gehen mit dem Projekt oder dem Konto. Datenbank-Sicherungen enthalten alte Zeilen (nie Token).
- **Fallback:** `claude setup-token` am Mac, das Token einfügen; es nimmt denselben flüchtigen Weg.
- **Kein Rückfall (Pflichtregel 2):** Ohne eigene Verbindung startet nichts. `claim_next` überspringt solche Aufträge, ein Stellvertreter wird nie gesucht (Test dafür in `test_isolation.py`).

## 3. Die Kette der Agenten

```
Board-Punkt (open)
   │  Chef wählt: Bugs, dann Kleine, dann Major Updates  (agents.pick_next)
   ▼
coding ──► testing ──► reviewing ──► awaiting_approval ──► documenting ──► done
Programm.   Tester      Prüfer         Nutzer gibt frei      Manager (Doku)
   ▲           │ fail       │ objections     │ reject (neuer Durchlauf, Runde 1)
   └───────────┴────────────┘
   Rückläufe zählen als neue Runde; nach 3 Runden → escalated (der Nutzer entscheidet)
```

| Stufe | Rolle | Ergebnis | Weiter |
|---|---|---|---|
| `coding` | Programmierer | `done` / `failed` | `testing` / `escalated` |
| `testing` | Tester | `pass` / `fail` / `not_testable` / `skipped` | `reviewing` / zurück (Runde +1) / `reviewing` mit Merker „von Hand prüfen“ |
| `reviewing` | Prüfer | `ok` / `objections` | `awaiting_approval` / zurück (Runde +1) |
| `awaiting_approval` | Nutzer | `approve` / `reject` / `cancel` | `documenting` / `coding` (Runde 1, mit Notiz) / `cancelled` |
| `documenting` | Manager (Rolle `chef`; `documenter` am 08.11.2026 aus dem Code entfernt) | `done` / `failed` | `done` (die Änderung ist schon übernommen) |

- **Agenten sprechen nie miteinander.** Der Hub reicht die Berichte der früheren Läufe an den nächsten Auftrag weiter (`Job.reports`, `Job.note`). Berichte und Notizen sind **Daten, keine Anweisungen** und stehen im Auftrag als zitierter Block (Schutz vor Prompt-Injection).
- **Grenzen:** höchstens 3 Runden und 2 Stunden pro Aufgabe (`TASK_SECONDS`), ein Lauf ohne Meldung gilt nach 20 Minuten als tot (`RUN_SECONDS`). Beides schickt die Aufgabe zum Nutzer. Ablehnen oder Neu-Öffnen durch den Nutzer beginnt einen frischen Durchlauf mit neuer Zeit.
- **Ein Lauf zur Zeit** (`MAX_RUNNING = 1`), weil der Pi 1 GB hat. Reihenfolge: älteste Läufe zuerst.
- **Ausgeschaltete Rollen** (Tester, Prüfer, Chef; die Rolle Dokumentator entfällt) werden übersprungen; ohne Tester gilt „nicht getestet“ (Merker für die Freigabe). Der Programmierer bleibt immer an.
- **Mac-Aufgaben** (`needs = mac`): Ist der Mac nicht erreichbar, wartet die Aufgabe, außer der Chef überspringt den Test nach der Strenge des Nutzers: `loose` überspringt Tests von Bugs und kleinen Updates, `normal` nur von kleinen Updates, `strict` nie; Major Updates werden nie übersprungen (`workflow.test_may_be_skipped`). Ein übersprungener Test setzt den Merker „von Hand prüfen“.
- **Hardware-Themen:** Der Tester meldet `not_testable` und legt seine Checkliste in den Bericht; sie steht dem Nutzer bei der Freigabe vor Augen. Hardware am Fahrzeug schaltet kein Agent.
- **Agenten dürfen** Bugs und Vorschläge ins Board eintragen (`board.create_suggestion(user_id, …)`, prüft den Besitz) und sonst nichts am Board ändern.
- **Modelle:** seit 14.11.2026 aus `catalog.py` (Liste je Anbieter, Modell und Stufe, Baustein `ui.model_picker`), nicht mehr fest im Code; pro Rolle und Nutzer änderbar (`agents.configure`). Künftig auch „Automatisch“ (Abschnitt 9.8).

## 4. Datenmodell (neu, SQLite)

- `claude_connections`: user_id (Schlüssel, Cascade), status, login_url, updated_at.
- `agent_settings`: user_id, key, value. Schlüssel `model.<rolle>`, `enabled.<rolle>`, `strictness`.
- `agent_tasks`: id, project_id (Cascade), item_id (wird bei gelöschtem Punkt leer), title und kind (Abschrift des Punktes), needs (`any`/`mac`), status, round, manual_check, note, created_at, deadline, finished_at. Branch: `agent/task-<id>` (vom Server berechnet).
- `agent_runs`: id, task_id (Cascade), role, model, status (`queued`/`running`/`done`/`failed`/`cancelled`), result, report (höchstens 20 000 Zeichen), tokens_in, tokens_out, seconds, Zeitstempel. Daraus kommt die eigene Verbrauchsanzeige (`agents.usage`).

## 5. Schnittstellen

**Nutzerseite** (alle mit `user_id`, Fremdes ist „nicht gefunden“): `start_task`, `list_tasks`, `get_task`, `task_runs`, `decide(approve|reject|cancel)`, `pick_next`, `waiting_reason`, `usage`, `settings`, `configure`; `claude_link.begin/status/login_url/disconnect`.

**Runnerseite** (vertrauter Code, **ohne** `user_id` als Parameter; der Nutzer kommt aus der Datenbank):
- `claim_next(can_mac) -> Job | None`: nächster startbarer Lauf. `Job` enthält nur: run_id, user_id, project_id, task_id, role, model, branch, title, kind, round, note, reports.
- `finish_run(run_id, result, report, tokens_in, tokens_out, seconds) -> bool`.
- `claude_link.set_login_url`, `complete`, `mark_expired`.

**HTTP für den Runner (gebaut, `routes/runner.py`):** Der Runner ruft nur aus und fragt nach, wie der Mac-Runner später auch (gleiche Schnittstelle).

| Aufruf | Zweck |
|---|---|
| `POST /runner/claim` (`can_mac`) | nächster Auftrag oder `job: null` |
| `POST /runner/runs/{id}/finish` (`result`, `report`, `tokens_in`, `tokens_out`, `seconds`) | Ergebnis melden; 400 bei unpassendem Ergebnis, 409 wenn der Lauf schon vorbei ist |
| `GET /runner/logins` | Nutzer mit laufender Anmeldung (mit oder ohne Link) |
| `POST /runner/logins/{user_id}/url` · `/code` · `/done` · `/expired` | Link melden, Code einmalig abholen, Anmeldung abschließen, Verbindung als abgelaufen melden |

Schutz, weil die Seite öffentlich ist: (1) Anfragen durch den Tunnel (Header `CF-Connecting-IP`) bekommen 404, auch mit richtigem Token; (2) Token im Header `Authorization: Bearer`, der Hub kennt nur seinen SHA-256 (`HUB_RUNNER_TOKEN_HASH` in der `.env`, leer = Schnittstelle aus, 404); (3) falsche Token zählen pro IP mit eigenem Zähler (10 Fehlversuche sperren eine Stunde). Ein Test prüft, dass jede Route am Schutz hängt. Der Code, den der Nutzer nach der Anmeldung eintippt, bleibt im Arbeitsspeicher des Hubs (5 Minuten, einmal abholbar, nie in Datenbank oder Log); das setzt einen einzigen Hub-Prozess voraus (so läuft `uvicorn` jetzt).

## 6. Trennung der Konten, so umgesetzt

| Pflichtregel (PROJEKT.md Abschnitt 3) | Umsetzung |
|---|---|
| 1 Ordner pro Nutzer | `config_dir(user_id)`; Janis’ bestehende Anmeldung wird sein Ordner `/data/claude/<seine id>/` |
| 2 Kein Rückfall | `claim_next` nimmt nur Läufe von Nutzern mit Zustand `connected` |
| 3 Lauf sieht nur seinen Nutzer | **Entschieden (Janis, 07.11.2026): ein eigener Container je Lauf**, Sicherheit geht vor Schlankheit. Aufbau in Abschnitt 6a. Verworfen: Prozess unter eigener Unix-Kennung im gemeinsamen Runner-Container (schlanker, aber alle Läufe teilen sich Container und Dateisystem). |
| 4 Nutzer vom Server | `Job.user_id` kommt aus `agent_tasks` → `projects`, `finish_run` und `claim_next` nehmen keinen Nutzer entgegen |
| 5 Token nur verschlüsselt, nur für den Besitzer | Seit 14.11.2026: Token aus `claude setup-token`, verschlüsselt in `token.enc` im Ordner des Nutzers (Schlüssel nur im Runner, `runner/tokens.py`); Läufe bekommen nur ein Ticket, der Gateway im Egress-Proxy setzt den Token ein (PROJEKT.md Abschnitt 3); kein Admin-Weg zum Anzeigen |
| 6 Test | `test_isolation.py::test_b_cannot_touch_the_agents_of_a`; der Test mit dem echten Runner kommt mit dem Runner |

## 6a. Ein Container je Lauf (entschieden)

**Messung auf dem Pi (07.11.2026):** Docker und containerd laufen ohnehin (zusammen etwa 210 MiB, schon in den 349 MiB „benutzt“ enthalten). Ein Wegwerf-Container mit allen Beschränkungen startet in 1,2 bis 2,8 Sekunden (fünf Läufe, bei einem Lauf von Minuten unerheblich) und kostet außer seinem Prozess keinen Dauerspeicher. Frei sind rund 540 MiB; ein Claude-Code-Lauf brauchte im ersten Test mindestens 225 MiB. Darum bleibt `MAX_RUNNING = 1`, der Container je Lauf ändert nichts an der Speicherrechnung.

Aufbau:
- Der **Launcher** (Teil des Runners, unser Code, nie Code eines Agenten) startet pro Lauf `docker run --rm` aus einer **festen Vorlage**. Aus dem Auftrag fließen nur drei geprüfte Werte ein: die Nutzernummer (Zahl), die Aufgabennummer (Zahl) und Modell und Stufe (nach festem Muster; ob sie in der Liste stehen, prüft der Hub mit `catalog.check`, seit 14.11.2026). Berichte, Titel und Notizen gelangen nie in die Befehlszeile, nur als Datei in den Arbeitsordner.
- **Eingehängt** sind genau zwei Ordner: der Worktree dieser Aufgabe (lesen/schreiben) und `/data/claude/<user_id>/` (lesen/schreiben, als `CLAUDE_CONFIG_DIR`). Nichts sonst: weder `hub.db`, `.env`, Backups, Tresor noch Ordner anderer Nutzer.
- **Beschränkungen:** `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only` mit `tmpfs` für `/tmp`, eigener Benutzer ohne Root (UID `10000 + user_id`, damit auch die Ordner-Rechte `0700` zusätzlich greifen), `--memory` (z. B. 480m, ohne Swap), `--pids-limit`, `--rm`, Zeitlimit durch `RUN_SECONDS`.
- **Netz (geändert 07.11.2026):** `agent-hub-agents` ist ein **internes** Docker-Netz ohne Route nach draußen (auch nicht ins Heimnetz oder zum Pi). Der einzige Ausgang ist der Dienst `egress` (`runner/egress.py`): Port 3128 „web“ nur für öffentliche Hosts auf Port 443, Port 3129 „api“ nur für Anthropic; die Läufe bekommen `HTTPS_PROXY` passend zu ihrem Zweck (Web-Chat 3128, alles andere 3129). Das löst die frühere offene Frage nach dem Heimnetz: Geräte-Aufgaben (Tresor-Vermittler) brauchen später einen eigenen, freigegebenen Weg. Gemessen auf dem Pi: direkt kein Zugriff, über 3128 nur öffentliche Hosts (192.168.x, 10.x, 169.254.x, Egress selbst und der Hub werden abgelehnt), über 3129 nur Anthropic.
- **Docker-Socket:** Der Launcher braucht ihn und hat damit faktisch Root auf dem Pi. Gegenmaßnahmen: Der Socket hängt **nur** im Runner, nie im `web`-Container und nie im Lauf-Container; der Launcher nimmt keine freien Argumente an (feste Vorlage, geprüfte Werte, wird getestet); Aufträge und Berichte sind Daten. Später möglich: ein Socket-Proxy, der nur Start, Warten, Log und Löschen erlaubt (eine zusätzliche Abhängigkeit, erst bei Bedarf).
- **Image `agent-hub-agent`** (`runner/Dockerfile`, neu): Das alte `agent-hub-runner` taugt nicht, dort liegt Claude Code im Home von UID 1000, den Läufen (UID 10000+id) fehlt der Zugriff. Das neue Image installiert Claude Code nach `/opt/claude-install` (für alle lesbar), Auto-Update aus. Das alte Image bleibt unberührt.
- **Geprüft auf dem Pi (07.11.2026)** mit dem echten Befehl der Vorlage (nur das Netz war `none`): Der Lauf ist UID 10002, `/` ist schreibgeschützt, sichtbar sind nur `/work` (schreibbar) und `/claude`, es gibt kein `/data` und keinen Docker-Socket, `claude --version` läuft (2.1.319). Nicht geprüft: ein echter Lauf mit Anmeldung, das Netz `agent-hub-agents` (wird beim Ausrollen angelegt, das ist eine Netzwerk-Änderung und wartet auf Janis’ Ja).
- **Berechtigungen im Lauf:** `--dangerously-skip-permissions`, weil der Agent nur den Arbeitsordner und seinen Claude-Ordner sieht und im Container nicht Root ist (so ist es im Container üblich). Das ist die eine Stelle in der Vorlage, die man bei Bedenken auf `acceptEdits` mit Werkzeugliste umstellen kann.
- **Ergebnis des Agenten:** Er beendet seine Antwort mit einer letzten Zeile `RESULT: <Wert>` (Werte je Rolle wie in Abschnitt 3). Fehlt sie, ist der Wert falsch, ist die Ausgabe kein lesbares JSON oder meldet Claude Code einen Fehler, gilt `failed` und die Aufgabe geht zu dir (`parse_output`). Jede Rolle darf `failed` melden. **Ungeprüft:** das genaue JSON von `claude -p --output-format json` (Felder `result`, `usage`); der Leser ist tolerant, aber erst der erste echte Lauf bestätigt es (PROJEKT.md Abschnitt 3 verlangt diese Prüfung).
- **Git im Lauf:** Der Agent committet nicht, der Runner committet danach von außen. Ein Git-Worktree taugt dafür schlecht, weil seine `.git`-Datei auf einen Ordner außerhalb zeigt, der nicht eingehängt ist. Vorschlag für das Modul „Arbeitsordner“: pro Aufgabe ein eigener Klon des Projekt-Repos (`git clone --shared` spart Platz), dann ist der Ordner in sich geschlossen. **So gebaut (15.11.2026):** statt eines Klons ein getrenntes Git-Verzeichnis beim Runner (`gitdirs/<Aufgabe>.git`) und ein Ordner nur mit den Dateien (`tasks/<Aufgabe>/`), der allein eingehängt wird; so kann ein Agent über `.git/config` oder Hooks nichts beim Runner auslösen (`runner/workspace.py`).

## 6b. Geräte, Heimnetz und Mac (entschieden 07.11.2026, Janis)

Volltext in PROJEKT.md (Abschnitte „Zugriff der Agenten auf Geräte“, „Geräteliste und Netzwege“, „Mac-Integration“). Kurz:
- **Heimnetz bleibt gesperrt.** Geräte kommen über eine **Geräteliste im Manager**: Hostname eintragen, der Hub löst ihn auf, der Nutzer gibt frei, optional SSH-Schlüssel im Tresor. Agenten greifen nur über den Vermittler zu und bekommen weder Schlüssel noch Netzweg. Verworfen: Heimnetz pauschal freigeben.
- **Fremde Netze (Kollegen):** VPN sternförmig mit dem Pi in der Mitte, Kollegen untereinander getrennt, Pi zum Gerät nur Port 22, Gerät nicht ins Netz. Technik: **Tailscale** (kein offener Fritzbox-Port, Zugriffsregeln pro Gerät); Headscale läuft nicht hinter Cloudflare Tunnel, Begründung und Vorbehalte in PROJEKT.md.
- **Mac:** Knopf in der Website startet die lokale Entwicklung ohne zweite Anmeldung; ein unsichtbares Einmal-Ticket verbindet Website und Mac-Programm. **Rückgabe:** Der Mac holt das Repo und liefert das Ergebnis als Git-Bundle über den Hub (HTTPS, ausgehend); der Hub prüft es, holt nur den Branch der Aufgabe ins Projekt und führt die normale Kette weiter (Prüfer, Freigabe, Merge, Doku durch den Manager). Ohne Ergebnis wartet die Aufgabe wieder auf den Mac. Vorschlag für den Mac (nicht entschieden): eigener macOS-Benutzer für den Runner und Firewall-Regel nur für ihn, die das Heimnetz sperrt.

## 7. Offene Entscheidungen (Janis)

1. ~~**Isolation im Runner**~~ entschieden: Container je Lauf (Abschnitt 6a).
2. ~~**Schutz der Claude-Ordner im Ruhezustand**~~ entschieden (Claude, von Janis überlassen, 14.11.2026): verschlüsseln (`token.enc`, Fernet, Schlüssel `HUB_TOKEN_KEY` nur im Runner); das Backup behält Ordner und `.env`, damit eine Wiederherstellung ohne neues Verknüpfen läuft (das Backup ist selbst verschlüsselt).
3. **Nutzungsbedingungen** für Claude Code in eigenen Tools und ob die Anmeldung dauerhaft hält (steht seit Anfang in PROJEKT.md Abschnitt 11, bleibt Voraussetzung für den ersten Livegang).
4. **Speicher:** Pi 4B mit 1 GB: Tests mit Sonnet, langen Läufen und Git-Worktrees stehen aus. `MAX_RUNNING = 1` ist die Vorsorge.
5. **Merge bei Freigabe:** Der Hub (nicht der Agent) übernimmt den Branch in `main` des Projekt-Repos, bevor der Manager die Doku nachführt. Eigenes Modul „Worktrees und Merge“.
6. **Strenge** als Tabelle in Abschnitt 3 ist mein Vorschlag; die drei Stufen aus PROJEKT.md waren bisher nicht ausgeführt.
7. ~~**Rechte pro Rolle (Web und Code)**~~ entschieden (Janis, 07.11.2026): **alle Agenten dürfen ins Internet** in den besprochenen Grenzen (nur über `egress`, nie Heimnetz, Geräte nur über Vermittler). Bei Code im selben Lauf geht Web nur zu einer Liste von Seiten (PyPI, npm, GitHub, Dokumentation); das ist Claudes Auslegung von „wie besprochen“ und noch zu bestätigen. Der Chat bleibt „Web oder Code“. Die genaue Seitenliste und eine dritte Proxy-Richtlinie („Liste“) entstehen beim Bau der Läufe.
8. ~~**VPN-Technik**~~ entschieden: Tailscale (Abschnitt 6b). Vor dem Bau zu prüfen: Nutzungsbedingungen (nicht gewerblich), Etiketten im kostenlosen Tarif.
9. **Manager legt Projektstand in Git ab** (PROJEKT.md, Manager-Tab): Der Hub committet und pusht für ihn, nur in einen Bereich für Projektdokumente und Aufgaben, nie in den Code. Entschieden (Janis, 07.11.2026): Die Rolle Dokumentator entfällt, der Manager übernimmt die Doku. Hardware-To-Dos und -Checklisten liegen beim Manager, nicht auf dem Board.
10. **Eingriffstiefe des Managers** (vollautomatisch, Rückfrage bei Großem, Rückfrage auch bei Kleinem; der Manager entscheidet fallweise, ob eine Frage nötig ist) und das Fenster „Wartet auf dich“ (Ort offen). Details in PROJEKT.md.

## 7a. Ausrollen der Verknüpfung (erledigt am 07.11.2026 mit Janis’ Ja)

Ausgerollt: Compose-Dienst `runner` (Image `agent-hub-hub-runner`), Netz `agent-hub-agents`, Ordner `/opt/agent-hub/claude`, Token in der `.env`, `agent-core` in `main`. Beim Ausrollen entstand Neues, das Sicherheit und Netzwerk betrifft (so war der Plan; Stand danach in PROJEKT.md, Abschnitt 12):
1. Ordner `/opt/agent-hub/claude` (Besitzer root, Modus 0700), **außerhalb** von `data/`, damit der Web-Container ihn nicht sieht.
2. Ein Runner-Token: zufällig erzeugt, in `.env` als `RUNNER_TOKEN` und sein SHA-256 als `HUB_RUNNER_TOKEN_HASH` (nie ausgegeben, nie im Git).
3. Docker-Netz `agent-hub-agents` (legt Compose an) und der Dienst `runner` mit dem Docker-Socket (nur dieser Dienst).
4. `main` bekommt `agent-core` (neue Tabellen, neue Routen), Backup der Datenbank vorher, `docker compose up -d --build web runner`, Prüfung von `/health` und der Live-Seite.
5. Janis’ bestehende Anmeldung (Volume `agent-hub_claude-home` des alten Runners) wird **nicht** übernommen: Er verknüpft einfach über den Knopf neu. Das alte Volume und der alte Runner bleiben unberührt, bis er sie löschen lässt.
Rückweg: `docker compose stop runner`, die Verknüpfung ist dann „nicht erreichbar“, nichts anderes ändert sich; Code per `git revert`.

## 8. Reihenfolge der nächsten Module

1. ~~Runner-Schnittstelle (HTTP, Runner-Token) und Launcher (ein Container je Lauf)~~ gebaut. Als Nächstes die **Schleife des Runners** (`runner/runner.py`, Prompt je Rolle, Anmeldekanal, Aufräumen), der Arbeitsordner je Aufgabe (eigener Klon) und der Isolationstest mit zwei echten Nutzern; Ausrollen mit Netz `agent-hub-agents`, Runner-Token und Compose-Dienst (Janis’ Ja nötig).
2. Anmeldung in der Oberfläche („Claude verbinden“ in der Schublade statt des Platzhalters, Zustand „abgelaufen“).
3. Worktrees und Merge.
4. Station „Agenten“ in der Projektansicht (Aufgaben, Freigabe mit Klick-Aussagen, Verbrauch), danach Design.
5. Chef als Lauf (Priorisierung, Status für die Kachel), Tester-Checklisten, Mac-Runner.

## Dateizugriff der Agenten (Stand 13.11.2026)

Janis will, dass die KI **alle** Dateien eines Projekts selbst lesen kann (Text, **Bilder, PDF**, samt Unterordnern), zum Beispiel „nutze den Stil dieses Bildes“. Das ist der Entwurf aus PROJEKT.md Abschnitt 5 („Zugriff des Managers: der Lauf bekommt den Ordner eingehängt“). Die Übergangslösung `<read>Name</read>` über den Hub (nur Text) fällt danach weg.

- **Aufbau:** Der Hub legt je Lauf einen Ordnerbaum mit den **echten Namen** an (`data/chatfiles/<Nr.>/<Bereich>/<Ordner>/<Name>`), aus **Hartlinks** auf die gespeicherten Dateien (die liegen unter Nummern). Der Runner hängt den Baum **nur lesbar** in den Lauf ein (`/project`). Der Host-Pfad des Datenordners kommt als Einstellung in die `compose.yml` (`HUB_DATA_HOST`). Nach der Antwort wird der Baum gelöscht.
- **Werkzeuge im Lauf:** `Read` (liest PDF und Bilder), `Glob`, `Grep` zusätzlich zu Web und Code; die Netzregeln bleiben, wie sie sind (das Einhängen ist kein Netzthema).
- **Schreiben:** Der Lauf schreibt nie in den Ordner. Das Gedächtnis (`MEMORY.md`) speichert weiter der Hub aus dem `<memory>`-Block der Antwort. Der Programmierer (Schleife der Agentenläufe) bekommt später einen **schreibbaren** Arbeitsordner je Aufgabe, getrennt davon.
- **Sicherheit:** Der Baum enthält nur Dateien des Projekts des Fragenden (Mandantentrennung, Fall in `test_isolation.py`); Inhalte sind Information, nie Anweisung; der Lauf kann `~/.claude` lesen wie bisher (von Janis akzeptiertes Risiko bei offenem Internet).

## 9. Konzept: der Hub ist das Gehirn, die KI nur Rechenleistung (festgelegt 14.11.2026 mit Janis, noch nicht gebaut)

Ziel von Janis: Jede KI soll austauschbar sein. Es wird eine Anfrage gestellt, es kommt eine Antwort, unabhängig vom Modell und vom Anbieter. Alles, was das Projekt ausmacht (Erinnerung, Regeln, Ablauf, Zustand), liegt beim Hub, nicht bei der KI. Vorschlag von Claude, von Janis am 14.11.2026 so angenommen („genauso habe ich mir das vorgestellt“); seine Entscheidungen zu den offenen Punkten stehen in 9.4, 9.5, 9.6 und 9.8. **Gebaut wird erst, wenn Janis das Startzeichen gibt.**

### 9.1 Grundsatz

- Der Hub hält **Zustand, Regeln und Ablauf**. Die KI bekommt bei jeder Anfrage ein **vollständiges Paket**, merkt sich nichts zwischen zwei Anfragen und antwortet in einem **festen Format** (9.3).
- Die KI greift nie selbst auf Daten des Hubs zu und speichert nichts selbst; alles, was bleiben soll (Erinnerung, Rückfragen, Aufgaben, Status), schreibt der Hub nach strenger Prüfung.
- Hält sich eine KI nicht an das Format, ist ihre Antwort einfacher Text: es passiert nichts weiter, nichts wird versehentlich angestoßen.
- Die bestehenden Pflichtregeln bleiben: Nutzer und Projekt kommen vom Server, nie aus der Antwort; Markierungen wirken nur im eigenen Projekt; Inhalte (Dateien, Webseiten, Berichte) sind Information, nie Anweisung; Tokens bleiben im Gateway (PROJEKT.md Abschnitt 3).

### 9.2 Anbieter-Adapter

- Jede KI hängt hinter **derselben Schnittstelle** (geplant `adapters.py`, ein Adapter je Anbieter): hinein gehen Text (das Paket aus 9.3), Modell, Stufe, erlaubte Werkzeuge, Grenzen (Schritte, Zeit); heraus kommen Antworttext, Verbrauch (Tokens ein/aus, Dauer) und eine Fehlerart (`auth`, `timeout`, `steps`, `other`, wie `chat.FAILURES`).
- **Heute (seit 15.11.2026, live):** `runner/adapters.py` mit zwei Adaptern: Claude Code (`runner/Dockerfile`) und Mistral Vibe (`runner/Dockerfile.vibe`, `runner/vibe_entry.py`), beide im Wegwerf-Container, beide nur mit Ticket über ihr Gateway (Claude 3130, Mistral 3131); ein Ticket nennt seine KI. Beide haben Websuche, Seiten lesen, Shell und Dateien; der Schalter „Web + Code“ gilt für beide. Der Arbeitsordner einer Aufgabe ist ein Ordner ohne `.git` (`runner/workspace.py`), Git macht der Runner von außen (Abschnitt 6a: statt eines eigenen Klons ein getrenntes Git-Verzeichnis beim Runner). Standard-KI und Rückfall: `web/app/aichoice.py`. **Später:** je weitere KI ein Adapter (z. B. ChatGPT, Mistral, ein lokales Modell); alles andere bleibt gleich. Zugangsdaten anderer Anbieter liegen wie der Claude-Token verschlüsselt beim Runner und kommen über einen Gateway, nie in den Lauf.
- **Plan vom 15.11.2026 (Janis):** Mistral bekommt einen Adapter wie Claude: **Mistral Vibe** im Wegwerf-Container, nur mit Ticket, Schlüssel im Gateway; Standard-KI je Nutzer mit automatischem Rückfall auf die nächste eigene KI (PROJEKT.md 11a, Punkt 4f).
- **Fähigkeiten:** Jeder Adapter meldet, was er kann: Websuche, Seiten lesen, Code ausführen, Dateien und Bilder lesen. Der Hub schreibt in den Regelteil, welche Werkzeuge es in diesem Lauf gibt; fehlt etwas (z. B. keine Websuche), steht das dort, und die KI arbeitet ohne.
- **Modelle und Stufen** kommen je Anbieter aus `catalog.py` (gebaut), gewählt mit `ui.model_picker` (gebaut).

### 9.3 Das Paket jeder Anfrage und das Antwortformat

**Aufbau, immer in dieser Reihenfolge, anbieterneutral (kein „CLAUDE.md“, keine Eigenheit eines Anbieters):**

1. **Rolle und Regeln** (vom Hub, je Rolle: Manager, Programmierer, Tester, Prüfer): wer du bist, was du darfst und was nie, die Selbstständigkeit des Nutzers als Regeltext (9.5), welche Werkzeuge es gibt, das Antwortformat. Erster Satz: **„Lies zuerst den Ordner Erinnerungen, zuerst MEMORY.md, dann arbeite.“**
2. **Erinnerung:** der ganze Ordner Erinnerungen (`<memory-folder>`, gebaut, höchstens 40 000 Zeichen). Der Hub legt die Dateien **mit bei**, damit auch eine KI ohne Werkzeuge sie hat. Dateinamen und Sprache des Inhalts sind der KI gleich (9.10).
3. **Lage im Projekt:** offene Board-Punkte, fällige Prüfungen, offene und beantwortete Rückfragen (9.4), der letzte Status (9.7), bei Agentenläufen die Berichte der früheren Läufe dieser Aufgabe (gebaut als `Job.reports`, als zitierte Daten).
4. **Auftrag:** die Frage im Chat, die Aufgabe eines Laufs oder der Anlass einer Manager-Runde (9.6).

**Antwortformat:** feste Markierungen, die jede KI schreiben kann. Der Hub liest sie streng (erlaubte Werte, Länge, Anzahl je Antwort, nur im eigenen Projekt) und schneidet sie aus dem Text, den der Nutzer liest.

| Markierung | Zweck | Stand |
|---|---|---|
| `<memory file="NAME.md">…</memory>` | eine Erinnerungsdatei ganz neu schreiben (höchstens 3 je Antwort) | gebaut |
| `<read>Name</read>` | eine weitere Datei anfordern (Übergang bis zum eingehängten Ordner, PROJEKT.md 11b) | gebaut |
| `<ask kind="choice\|text" size="small\|large">Frage<option>…</option>…</ask>` | eine Rückfrage an den Nutzer (9.4) | geplant |
| `<task kind="bug\|minor\|major" title="…">Beschreibung, Abnahmekriterien</task>` | eine Aufgabe fürs Board (9.5) | geplant |
| `<status level="green\|yellow\|red">ein Satz</status>` | der Projektstand (9.7) | geplant |
| `RESULT: <wert>` als letzte Zeile | Ergebnis eines Agentenlaufs (`workflow.py`) | gebaut |

Grenzen (Vorschlag, beim Bau festzulegen): höchstens 3 `<ask>`, 5 `<task>`, 1 `<status>` je Antwort; Titel bis 200 Zeichen, Beschreibung bis 4 000, Frage bis 1 000, bis 6 Antwortmöglichkeiten zu je 200 Zeichen.

### 9.4 Rückfragen, unabhängig von der KI („Wartet auf dich“)

- Claudes eigenes Nachfragen wird **nicht** genutzt (in `-p` ohnehin nicht möglich); jede KI fragt über `<ask>`.
- **Rückfragen sind technische Fragen während der Arbeit** (z. B. „Relais mit 12 V oder 24 V?“, „Datenbankfeld als Zahl oder Text?“). Was als Nächstes gebaut wird, gehört dagegen aufs **Board** (9.5). So unterscheiden sich die beiden, obwohl beide bestimmen, wie es weitergeht (Janis, 14.11.2026).
- Der Hub speichert jede Frage (geplante Tabelle `questions`: id, project_id, task_id oder leer, role, text, kind, options, size, status `open`/`answered`/`dropped`, answer, created_at, answered_at), zeigt sie in der Kachel „Wartet auf dich“ und zählt sie in deren Zahl. Eine Aufgabe, zu der eine Frage offen ist, **wartet** (`waiting_reason = question`).
- **Antworten (Janis, 14.11.2026):** Knöpfe mit den vorgeschlagenen Antworten **und** ein freies Feld für eine eigene. Eine Ja/Nein-Frage oder eine mit wenigen kurzen Möglichkeiten wird direkt unten in der Kachel beantwortet; eine Frage mit vielen Möglichkeiten oder viel Text (`size="large"`, oder vom Hub nach Länge erkannt) öffnet groß (die Kachel vergrößert sich wie die Dateien-Kachel), damit man den Überblick hat.
- Die Antwort geht mit der nächsten Anfrage dieser Aufgabe oder dieses Projekts zurück (Block „Antworten auf deine Rückfragen“) und landet im Chat-Archiv.

### 9.5 Selbstständigkeit und Aufgaben verteilen (Board)

- **Aufgaben, die der Manager vorschlägt, kommen immer aufs Board** (`<task>` → Board-Punkt mit Hinweis „vom Manager“, Janis, 14.11.2026). Die Selbstständigkeit entscheidet nur über die **Genehmigung**:

| | Entscheidet selbst | Fragt bei Großem | Fragt auch bei Kleinem |
|---|---|---|---|
| **Bug** | direkt freigegeben, wird behoben | direkt freigegeben | direkt freigegeben |
| **Kleines Update** (kleine Zusatzfunktion) | Vorschlag, Janis genehmigt | Vorschlag | Vorschlag |
| **Major Update** (z. B. „Projekte teilen“, ein eigener Abschnitt) | Vorschlag, Janis genehmigt | Vorschlag | Vorschlag |
| **Technische Detailfrage** während der Arbeit | der Manager klärt sie selbst und schreibt die Entscheidung in die Erinnerung | Rückfrage nur bei Großem (Architektur, Kosten, Löschen, Hardware, Sicherheit) | Rückfrage vor jeder Entscheidung |

  **Bugs werden immer direkt behoben**, egal was eingestellt ist; **Updates (klein und groß) fragen immer** erst über das Board, auch bei „Entscheidet selbst“. Die Stufe unterscheidet sich also nur darin, wie viele technische Rückfragen kommen.
- Ein genehmigter Punkt läuft durch die bestehende Kette (Abschnitt 3): Programmierer → Tester → Prüfer → Freigabe durch den Nutzer → Manager führt Doku und Erinnerung nach. Jede Rolle bekommt ihren eigenen Regelteil (9.3), die Aufgabe, die Erinnerung und ihren Arbeitsordner (eigener Branch). Den Lauf startet der Runner (Schleife der Agentenläufe, PROJEKT.md 11a Punkt 6), das Ergebnis wertet der Hub aus (`workflow.py`).
- Auch Programmierer, Tester und Prüfer dürfen `<ask>` stellen (z. B. der Tester: „Ist das Verhalten so gewollt?“); es gilt dieselbe Selbstständigkeit.

### 9.6 Regelmäßige Durchläufe (Manager-Runde)

- Den Zeitplan hält **der Hub**, nicht die KI. **Nicht nach Uhrzeit, sondern nach Fälligkeit** (Janis, 14.11.2026; die Fälligkeit hängt nur indirekt an der Uhr).
- **Anlässe einer Manager-Runde:** (1) eine regelmäßige Prüfung wird fällig (Tabelle `checks`, gebaut, mit Länge und Wochentagen); (2) eine Aufgabe ist fertig (nach der Freigabe oder als `escalated`); (3) eine Rückfrage wurde beantwortet, auf die keine laufende Aufgabe wartet. Mehrere Anlässe zur selben Zeit werden zu einer Runde zusammengefasst.
- In der Runde geht der Manager Board, offene Aufgaben, fällige Prüfungen und Antworten durch und antwortet im selben Format: `<status>`, `<task>`, `<ask>`, `<memory file=…>`. Eine erledigte Prüfung markiert der Hub als erledigt, wenn der Manager es in seinem Bericht sagt (Form beim Bau festlegen).
- Ein Lauf zur Zeit (Pi mit 1 GB), Kontingent schonen; später richtet sich die Häufigkeit nach dem Verbrauch (9.8).

### 9.7 Status des Projekts

- Der Manager setzt ihn mit `<status level="green|yellow|red">` und einem Satz. Der Hub zeigt ihn als **Lampe und Satz** auf der Status-Kachel des Managers und auf der Projektkachel im Dashboard, mit Zeitpunkt.
- **Was der Hub selbst sicher weiß, zählt zusätzlich:** ein gescheiterter Lauf, eine eskalierte Aufgabe oder eine unbeantwortete Rückfrage machen den Status **mindestens gelb**; eine abgelaufene Claude-Verbindung macht ihn rot. So hängt der Status nicht allein an der KI.
- Geplante Tabelle `project_status` (project_id, level, text, source `manager`/`hub`, created_at); der Verlauf bleibt zum Nachschauen.

### 9.8 Modell je Rolle, mit Automatik (PROJEKT.md 11a, Punkt 4e)

- Für Manager, Programmierer, Tester und Prüfer wählt man Modell und Stufe selbst (Baustein `ui.model_picker`) **oder „Automatisch“**: dann entscheidet der Manager je Aufgabe, welches Modell und welche Stufe die Rolle bekommt (Markierung beim Bau festlegen, z. B. ein Attribut an `<task>`), in den Grenzen der Liste aus `catalog.py`.
- **Später, fortgeschritten (Janis):** die Wahl berücksichtigt das restliche Kontingent und die Zeit bis zum Zurücksetzen (viel übrig kurz vor dem Zurücksetzen = großzügiger, wenig übrig = sparsam). Setzt die Verbrauchsanzeige voraus (PROJEKT.md 11a, Punkt 7).
- Der Prüfer soll, sobald eine zweite KI verbunden ist, eine andere KI nutzen als der Programmierer (PROJEKT.md 11a, Punkt 4b).

### 9.9 Reihenfolge der Umsetzung (Stand 15.11.2026)

1. Antwortformat und strenges Lesen im Manager-Chat: `<ask>`, `<status>`, `<task>` (Parser wie `memory.parse_answer`, Tests mit Fremdprojekten in `test_isolation.py`). **Offen.**
2. Kachel „Wartet auf dich“ mit Antworten (Knöpfe, freies Feld, groß bei großen Fragen) und der Regeltext der Selbstständigkeit. **Offen.**
3. Status-Kachel und Projektkachel. **Offen.**
4. Schleife der Agentenläufe samt Verteilen der Aufgaben (Board → Kette), Arbeitsordner je Aufgabe. **Gebaut 15.11.2026** (`ai-default`): Start auf der Board-Karte, Freigabe auf der Karte, Merge durch den Runner, Manager dokumentiert. Noch nicht: der Manager verteilt Aufgaben selbst (`<task>`, Punkt 1).
5. Zeitplan der Manager-Runden nach Fälligkeit. **Offen.**
6. Modell je Rolle mit Automatik. **Teilweise:** Modell und Stufe je Rolle und je KI gebaut, „Automatisch“ offen.
7. Ein zweiter Anbieter-Adapter als Beweis, dass alles ohne Claude geht. **Gebaut 15.11.2026** (Mistral Vibe).

### 9.10 Dateien der Erinnerung: Namen und Sprache

- **Dateinamen immer englisch:** `MEMORY.md`, `PROJECT.md`, `ROADMAP.md`, `RULES.md`. **Inhalt** (Überschriften, Text) in der Sprache, die beim Anlegen des Projekts eingestellt ist. Begründung: Die Namen sind technische Schlüssel, auf die Regelteil, Hub und Tests sich beziehen, und sehen in jedem Projekt gleich aus; den Inhalt lesen Menschen. Verworfen: übersetzte Namen (jede Stelle bräuchte beide), gemischte Namen (MEMORY neben REGELN). Vorschlag von Claude am 14.11.2026, von Janis im selben Zug angenommen.
- **`ARCHIVE.md` (seit 15.11.2026, live):** die Geschichte des Projekts (was es gab, was verworfen oder geändert wurde, warum). Sie wächst nur: Der Hub hängt an, was der Manager hineinschreibt, mit Datum (PROJEKT.md, Änderungsprotokoll `memory-archive`).
- **Noch umzusetzen:** `memory.SKELETON` legt heute für deutsche Projekte `PROJEKT.md` und `REGELN.md` an; das wird auf die englischen Namen umgestellt, und in bestehenden Projekten werden diese beiden Dateien einmalig umbenannt (Inhalt bleibt).
