# Agent-Hub – Konzept: Claude-Instanzen und Zusammenarbeit der Agenten

Stand: 22.11.2026 (Abschnitt 10: die Kette neu gebaut, gilt vor 3 bis 5 und 9.4/9.5) · davor 20.11.2026 (Abschnitt 9.3a: Pakete je Rolle, 9.2a: Werkzeuge je KI; Abschnitte 2, 6a und „Dateizugriff 13.11.“ sind Geschichte, der heutige Stand steht jeweils oben im Hinweis) · davor 14.11.2026 (Abschnitt 9: Konzept für den KI-unabhängigen Ablauf) · zuerst 07.11.2026, Branch `agent-core` · Ergänzt PROJEKT.md (Abschnitte 3 und 5). Hier steht die Logik hinter dem Bereich „Projekte“; das Aussehen kommt später (DESIGN.md).

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

> **Stand 20.11.2026:** Läufe hängen keinen Claude-Ordner mehr ein (nur ein Ticket, seit 14.11.2026); neben dem Lauf gibt es den Testlauf (`launcher.build_test_command`, `hub-test.sh`, ohne KI und ohne Ticket) und den Lauf ohne Werkzeuge (`prompts.brief_run`). Der Rest des Abschnitts beschreibt den Bau vom 07.11.2026.

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

> Historisch (Stand 07.11.2026): Punkte 1 bis 4 sind gebaut; maßgeblich sind 9.9 und der Fahrplan in PROJEKT.md Abschnitt 11a.

1. ~~Runner-Schnittstelle (HTTP, Runner-Token) und Launcher (ein Container je Lauf)~~ gebaut. Als Nächstes die **Schleife des Runners** (`runner/runner.py`, Prompt je Rolle, Anmeldekanal, Aufräumen), der Arbeitsordner je Aufgabe (eigener Klon) und der Isolationstest mit zwei echten Nutzern; Ausrollen mit Netz `agent-hub-agents`, Runner-Token und Compose-Dienst (Janis’ Ja nötig).
2. Anmeldung in der Oberfläche („Claude verbinden“ in der Schublade statt des Platzhalters, Zustand „abgelaufen“).
3. Worktrees und Merge.
4. Station „Agenten“ in der Projektansicht (Aufgaben, Freigabe mit Klick-Aussagen, Verbrauch), danach Design.
5. Chef als Lauf (Priorisierung, Status für die Kachel), Tester-Checklisten, Mac-Runner.

## Dateizugriff der Agenten (Stand 13.11.2026)

> **Stand 20.11.2026:** gebaut als Kopie statt Hartlinks (`runner/view.py`, seit 16.11.2026), je Inhalt zwischengespeichert und mit dem Projekt gelöscht; `<read>` bleibt nur für KIs ohne Dateiwerkzeug. Der Text unten ist der Entwurf.

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
| `<ask kind="choice\|text" size="small\|large">Frage<option>…</option>…</ask>` | eine Rückfrage an den Nutzer (9.4) | **gebaut 19.11.2026** (`board-smooth`: Manager-Chat und Läufe, Antwort in „Wartet auf dich“) |
| `<task kind="bug\|minor\|major" title="…" from="user\|idea">Kontext, Abnahmekriterien</task>` | ein Stichpunkt fürs Board mit Kontext dahinter (9.5) | **gebaut 19.11.2026** (`manager-board`: Manager-Chat und Berichte der Läufe) |
| `<task-edit id="N" kind="…" title="…">neuer Kontext</task-edit>` | der Manager korrigiert einen Punkt, den der Programmierer noch nicht angefangen hat | **gebaut 19.11.2026** |
| `<status level="green\|yellow\|red">ein Satz</status>` | der Projektstand (9.7) | geplant |
| `RESULT: <wert>` als letzte Zeile | Ergebnis eines Agentenlaufs (`workflow.py`) | gebaut |

Grenzen (Vorschlag, beim Bau festzulegen): höchstens 3 `<ask>`, 5 `<task>`, 1 `<status>` je Antwort; Titel bis 200 Zeichen, Beschreibung bis 4 000, Frage bis 1 000, bis 6 Antwortmöglichkeiten zu je 200 Zeichen.

### 9.2a Werkzeuge je KI (Janis, 20.11.2026, gebaut)

- Im Katalog steht je Anbieter für jedes Werkzeug (`read`, `write`, `shell`, `search`, `fetch`, `look`), woher es kommt: `own` (das Programm der KI hat es), `hub` (der Hub reicht sein eigenes, vielleicht schwächeres Werkzeug), `none`. Heute: Claude Code alles `own`; Mistral Vibe alles `own`, nur `look` vom Hub (`runner/look_mcp.py`).
- Das Paket nennt nur die Werkzeuge, die es gibt (`prompts.tools_text`). Eine KI ohne Dateiwerkzeug bekommt die Liste der Dateien und fragt mit `<read>`; eine KI ganz ohne Werkzeuge bekommt alles Nötige im Paket.
- **Gebaut am 20.11.2026 (`own-ai`):** `runner/hub_tools.py` (look, Dateien lesen, suchen, schreiben, Shell, Webseiten) als MCP-Server für Programme, denen Werkzeuge fehlen, und `runner/hubloop.py` für KIs, die nur eine API im OpenAI-Format haben (die Schleife fährt der Hub im Container selbst, Werkzeugaufrufe der API oder als Text). Die „Eigene KI“ ist der Anbieter `custom` (seit 21.11.2026 „Weitere KI“ mit bis zu acht Plätzen, 9.2c): Adresse und Modell je Nutzer, Gateway 3132 mit der Adresse im Ticket.

### 9.2b ChatGPT, Modell-Listen, Werkzeug-Prüfung (21.11.2026, gebaut)

- **ChatGPT** läuft über Codex (das Programm, Modelle der GPT-Familie) mit der Anmeldung des ChatGPT-Kontos; alle Rollen, je Rolle ein passendes Modell (`catalog` "roles"). Tokens nur beim Runner, Läufe mit Ticket-Hülle über Gateway 3133 (`runner/codex.py`).
- **Modell-Listen** fragt der Runner täglich bei jeder KI mit den Zugangsdaten des Nutzers ab; der Hub macht daraus den Katalog und die Auswahl je Nutzer (`models.py`).
- **Werkzeug-Prüfung** (`toolcheck.py`): Ersatz vom Hub nur, wenn das Programm ein angefragtes Werkzeug dreimal in Folge lesbar nicht nennt; heute misst das nur Claude Code (`init`), die anderen bleiben beim Katalog.

### 9.2c Abo oder Schlüssel, weitere KIs (21.11.2026, gebaut)

- **Abo oder API-Schlüssel** ist eine Frage des Zugangs, nicht der KI: dieselben Modelle, dasselbe Paket, dieselben Werkzeuge. Der Hub wählt je Auftrag den Weg (`credentials.py`: Modus, Bereich, Tagesgrenze des Nutzers), der Runner holt das passende Geheimnis, das Gateway setzt es ein. Wechsel nur vom Abo zum Schlüssel derselben KI, dann erst die nächste KI (`aichoice`).
- **Weitere KIs** sind ein Anbieter (`custom`) mit bis zu acht Plätzen je Nutzer; das Modell nennt den Platz (`own-3`), Adresse und Modell der fremden API kommen aus der Datenbank des Hubs, nie aus dem Lauf. Rolle, Paket und Werkzeuge wie bei jeder KI ohne eigenes Programm (`hubloop.py`, Werkzeuge vom Hub).
- **Schleife nach dem Taschenrechner-Test (`robust-loop`):** Die Aufgabe ist die Einheit: was zu ihr gehört, erledigt der Programmierer im Lauf, Tester und Prüfer melden es als Ergebnis. Rollen legen nur Fehler außerhalb der Aufgabe und neue Funktionen an; Umgebungsprobleme sind Hinweise (`<env>`). Scheitert ein Lauf an der KI statt an der Arbeit (`failures.py`), geht er mit Schlüssel oder nächster KI weiter. Programmierer und Tester haben einen Testbrowser (`hub-browser`).
- **Eigener Adapter lohnt sich**, wenn die KI ein Programm mit eigenen Werkzeugen und eine Abo-Anmeldung hat (heute Claude Code, Mistral Vibe, Codex; als Platzhalter Gemini CLI und GitHub Copilot CLI). Sonst reicht der allgemeine Weg.

### 9.3a Pakete je Rolle (Janis, 20.11.2026, gebaut in `web/app/prompts.py`)

Jede Rolle bekommt nur, was sie braucht; die Regeln stehen vorne (gleich für eine Rolle, der Anbieter kann sie zwischenspeichern), dann Erinnerung, Lage, Auftrag.

| Rolle | Regeln und Markierungen | Kontext |
|---|---|---|
| Manager im Chat | Board (`<task>`, `<task-edit>`), Rückfragen (`<ask>`), Erinnerung (`<memory-edit>` mit `<section>`, `<memory file>`); Geräte (`<device>`) nur bei Geräten mit freigegebenen Aktionen; `<read>` nur ohne Dateiwerkzeug | MEMORY.md ganz, andere Erinnerungsdateien bis 8000 Zeichen, ARCHIVE.md nur genannt; Board, Prüfungen, Geräte, „Für dich“ nur, wenn es welche gibt; letzte 6 Fragen |
| Programmierer | Rolle, Funde (`<task>`, `<ask>`), `RESULT`, `hub-test.sh` pflegen | RULES.md, Aufgabe mit Kontext, Berichte seit seinem letzten Lauf |
| Tester (nur ohne `hub-test.sh`) | Rolle, Funde, `RESULT` | Aufgabe, Diff, Bericht des Programmierers |
| Prüfer | Rolle, Funde, `RESULT`; bei kleinem Diff ohne Werkzeuge | RULES.md, Aufgabe, Diff, Testergebnis |
| Manager nach der Freigabe | Erinnerung, `RESULT`; ohne Werkzeuge | MEMORY.md, ROADMAP.md, Aufgabe, Berichte, Übersicht des Diffs |

Der Hub liest aus einer Antwort nur die Markierungen der Rolle (`prompts.ALLOWED`). Hat der Manager im Web gelesen, warten seine neuen Board-Punkte auf das Ja.

### 9.4 Rückfragen, unabhängig von der KI („Wartet auf dich“)

- **So gebaut (19.11.2026, `board-smooth`):** Tabelle `questions` (`questions.py`), höchstens 10 offene je Projekt, gleiche Frage nur einmal. Manager-Chat und Läufe lesen `<ask>`; die Kachel zeigt die Frage mit den Antworten als Pillen und einem freien Feld. Eine Antwort an den Manager geht sofort als nächste Chat-Nachricht los („Antwort auf deine Rückfrage …“); läuft gerade eine Frage, kommt sie mit der nächsten im Block `<answers>`. Eine Antwort an eine Rolle kommt mit dem nächsten Lauf dieser Aufgabe. **Abweichung vom Plan:** die Aufgabe wartet nicht auf die Antwort (die Rolle tut, was am sichersten ist, und fragt; die Antwort wirkt ab dem nächsten Lauf). Freigeben, „Noch eine Runde“ mit Bemerkung und Abbrechen gibt es ebenfalls direkt in der Kachel.
- Claudes eigenes Nachfragen wird **nicht** genutzt (in `-p` ohnehin nicht möglich); jede KI fragt über `<ask>`.
- **Rückfragen sind technische Fragen während der Arbeit** (z. B. „Relais mit 12 V oder 24 V?“, „Datenbankfeld als Zahl oder Text?“). Was als Nächstes gebaut wird, gehört dagegen aufs **Board** (9.5). So unterscheiden sich die beiden, obwohl beide bestimmen, wie es weitergeht (Janis, 14.11.2026).
- Der Hub speichert jede Frage (geplante Tabelle `questions`: id, project_id, task_id oder leer, role, text, kind, options, size, status `open`/`answered`/`dropped`, answer, created_at, answered_at), zeigt sie in der Kachel „Wartet auf dich“ und zählt sie in deren Zahl. Eine Aufgabe, zu der eine Frage offen ist, **wartet** (`waiting_reason = question`).
- **Antworten (Janis, 14.11.2026):** Knöpfe mit den vorgeschlagenen Antworten **und** ein freies Feld für eine eigene. Eine Ja/Nein-Frage oder eine mit wenigen kurzen Möglichkeiten wird direkt unten in der Kachel beantwortet; eine Frage mit vielen Möglichkeiten oder viel Text (`size="large"`, oder vom Hub nach Länge erkannt) öffnet groß (die Kachel vergrößert sich wie die Dateien-Kachel), damit man den Überblick hat.
- Die Antwort geht mit der nächsten Anfrage dieser Aufgabe oder dieses Projekts zurück (Block „Antworten auf deine Rückfragen“) und landet im Chat-Archiv.

### 9.5 Selbstständigkeit und Aufgaben verteilen (Board)

- **So gebaut (19.11.2026, `manager-board`, Janis):** Der Manager zerlegt im Chat, was umgesetzt werden soll, in **kleine, einzeln machbare Häppchen** und legt jedes als kurzen **Stichpunkt** mit **Kontext im Hintergrund** (`board_items.details`) in die passende Spalte. Was der Nutzer im Chat will (`from="user"`), braucht **keine Bestätigung**; ebenso Punkte, die der Nutzer von Hand anlegt. Beide laufen **von selbst** los (`board_items.auto`, `agents.autostart`): je Projekt eine Aufgabe zur Zeit, Bugs vor kleinen vor großen Updates, in der Reihenfolge des Boards. Was der Manager selbst vorschlägt (`from="idea"`) oder einer Rolle im Lauf auffällt (`<task>` im Bericht, `runtask.FOUND_RULE`), wartet als **Vorschlag** auf das Ja des Nutzers; ein Bug kommt direkt aufs Board. Ein angenommener Vorschlag läuft dann von selbst. Ein abgebrochener Punkt startet nie wieder von selbst. Der Manager sieht die Punkte mit Nummer und Stand (wartet, in Arbeit, Vorschlag) und darf einen noch nicht angefangenen mit `<task-edit>` korrigieren. Der Programmierer bekommt den Kontext im `<task>`-Block seines Auftrags.
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
- **So gebaut (Stand 22.11.2026):** Den Satz schreibt ein kleiner Auftrag des Hubs (`statusnote.py`, günstigstes Modell, ohne Werkzeuge, nur ein Auszug der Lage), nicht der Manager im Chat. Bei laufender Arbeit alle 2 Minuten, sonst selten; „neu schreiben“ ohne Grenze; neben den Agentenläufen, aber nach einer Frage des Nutzers. Einzelheiten in PROJEKT.md 3 („Geschriebener Status“).

### 9.8 Modell je Rolle, mit Automatik (PROJEKT.md 11a, Punkt 4e)

- Für Manager, Programmierer, Tester und Prüfer wählt man Modell und Stufe selbst (Baustein `ui.model_picker`) **oder „Automatisch“**: dann entscheidet der Manager je Aufgabe, welches Modell und welche Stufe die Rolle bekommt (Markierung beim Bau festlegen, z. B. ein Attribut an `<task>`), in den Grenzen der Liste aus `catalog.py`.
- **Später, fortgeschritten (Janis):** die Wahl berücksichtigt das restliche Kontingent und die Zeit bis zum Zurücksetzen (viel übrig kurz vor dem Zurücksetzen = großzügiger, wenig übrig = sparsam). Setzt die Verbrauchsanzeige voraus (PROJEKT.md 11a, Punkt 7).
- Der Prüfer soll, sobald eine zweite KI verbunden ist, eine andere KI nutzen als der Programmierer (PROJEKT.md 11a, Punkt 4b).

### 9.9 Reihenfolge der Umsetzung (Stand 15.11.2026; seit 20.11.2026 zusätzlich 9.2a und 9.3a gebaut)

1. Antwortformat und strenges Lesen im Manager-Chat: `<ask>`, `<status>`, `<task>` (Parser wie `memory.parse_answer`, Tests mit Fremdprojekten in `test_isolation.py`). **Teilweise (15.11.2026, `reply-format`):** der strenge Leser steht (`web/app/reply.py`, reine Funktion, Grenzen wie in 9.3); offen: Speichern, Anschluss an Chat und Manager-Runde, Fremdprojekt-Tests.
2. Kachel „Wartet auf dich“ mit Antworten (Knöpfe, freies Feld) und der Regeltext der Selbstständigkeit. **Gebaut 19.11.2026** (`board-smooth`); offen: groß öffnen bei langen Fragen.
3. Status-Kachel und Projektkachel. **Offen.**
4. Schleife der Agentenläufe samt Verteilen der Aufgaben (Board → Kette), Arbeitsordner je Aufgabe. **Gebaut 15.11.2026** (`ai-default`): Start auf der Board-Karte, Freigabe auf der Karte, Merge durch den Runner, Manager dokumentiert. **Seit 19.11.2026** (`manager-board`): der Manager verteilt die Aufgaben selbst (`<task>`), Punkte starten von selbst.
5. Zeitplan der Manager-Runden nach Fälligkeit. **Offen.**
6. Modell je Rolle mit Automatik. **Teilweise:** Modell und Stufe je Rolle und je KI gebaut, „Automatisch“ offen.
7. Ein zweiter Anbieter-Adapter als Beweis, dass alles ohne Claude geht. **Gebaut 15.11.2026** (Mistral Vibe).

### 9.10 Dateien der Erinnerung: Namen und Sprache

- **Dateinamen immer englisch:** `MEMORY.md`, `PROJECT.md`, `ROADMAP.md`, `RULES.md`. **Inhalt** (Überschriften, Text) in der Sprache, die beim Anlegen des Projekts eingestellt ist. Begründung: Die Namen sind technische Schlüssel, auf die Regelteil, Hub und Tests sich beziehen, und sehen in jedem Projekt gleich aus; den Inhalt lesen Menschen. Verworfen: übersetzte Namen (jede Stelle bräuchte beide), gemischte Namen (MEMORY neben REGELN). Vorschlag von Claude am 14.11.2026, von Janis im selben Zug angenommen.
- **`ARCHIVE.md` (seit 15.11.2026, live):** die Geschichte des Projekts (was es gab, was verworfen oder geändert wurde, warum). Sie wächst nur: Der Hub hängt an, was der Manager hineinschreibt, mit Datum (PROJEKT.md, Änderungsprotokoll `memory-archive`).
- **Umgesetzt 20.11.2026:** `memory.SKELETON` legt in jeder Sprache `PROJECT.md` und `RULES.md` an; bestehende Projekte wurden einmalig umbenannt (Inhalt blieb, `db._prepare`, Merker `done.memory_names`).

## 10. Die Kette neu (Janis' Ablauf, gebaut und live seit 22.11.2026, Branch `chain`)

Anlass: Durchsicht der echten Läufe (7 von 10 Eskalationen waren unlösbare Merge-Konflikte). Janis: alles zur Kette neu aufbauen, Funktionierendes übernehmen, keine Altlasten. Ersetzt die Abschnitte 3 bis 5 und 9.4/9.5, soweit sie die Kette betreffen. **Abweichungen beim Bau:** die kurzen Aufträge des Managers (`decide`, `explain`) gehen vor die Arbeitsläufe; sind alle KIs des Nutzers verbraucht, wartet der Lauf in der Warteschlange (auch ein Lauf auf dem API-Schlüssel wartet nicht auf das ruhende Abo); „Abbrechen“ steht im Programmierer-Tab nur in der Aufgabenkachel; der Vergleich „derselbe Einwand zweimal“ wurde nicht gebaut (bei langen Berichten unzuverlässig), stattdessen gilt „nach einer Rückgabe nichts geändert“ als festgefahren.

### 10.1 Ablauf (Janis)

1. **Manager-Chat:** Der Nutzer beschreibt, was er will. Der Manager fragt nach, was ihm auffällt, **direkt im Chat** (normaler Text; kein `<ask>` im Chat, nichts unter „Wartet auf dich“). Er legt die Teile mit `<task from="user">` aufs Board; die starten ohne Bestätigung. Eigene Ideen (`from="idea"`) und neue Funktionen, die einer Rolle auffallen, sind Vorschläge mit Annehmen/Ablehnen; ein Fehler einer Rolle kommt direkt aufs Board.
2. **Das Board ist die Warteschlange.** Je Projekt eine Aufgabe zur Zeit. Reihenfolge: Fehler zuerst (in Board-Reihenfolge), dann kleine und große Updates gemeinsam: von den beiden Spaltenköpfen der mit der kleineren Nummer (früher angelegt) zuerst; Ziehen innerhalb einer Spalte gilt weiter.
3. **Übernimmt der Programmierer, verlässt der Punkt das Board** (`board_items.status = 'working'`). Sichtbar ist er unter „Gerade“ im Tab der Rolle, die dran ist (er wandert Programmierer → Tester → Prüfer), und in den Läufen.
4. **Kette:**
```
coding ──► [hub-test.sh] ──► testing ──► reviewing ──► merging ──► documenting ──► done
  ▲      rot │                  │ fail        │ objections
  └──────────┴──────────────────┴─────────────┘   jede Rückgabe: returns + 1
```
   Nach jeder Rückgabe läuft die ganze Kette wieder: Programmierer → Tests → Tester → Prüfer. Prüfer ok → der Runner führt zusammen → der Manager führt die Erinnerung nach → fertig, Punkt ins Archiv. **Keine Freigabe durch den Nutzer mehr, kein „Noch eine Runde“.** Ausgeschaltete Rollen werden übersprungen (ohne Tester: Merker „von Hand prüfen“).
5. **Rückfragen einer Rolle:** Hängt ihr Weg an einer Entscheidung, endet sie mit `<ask>` und `RESULT: question`; die Aufgabe hält an (`hold = 'question'`). Der Manager bekommt die Frage (kurzer Lauf ohne Werkzeuge mit MEMORY.md, PROJECT.md, RULES.md, der Aufgabe und der Frage) und
   - entscheidet selbst: `<decide>Antwort</decide>`, die Rolle läuft mit der Antwort weiter, oder
   - fragt den Nutzer: schreibt die Frage neu, einfach, ohne Technik-Überschrift, mit Vorschlag: `<ask>Frage<option recommended>Vorschlag</option><option>B</option></ask>`. „Wartet auf dich“ zeigt die Möglichkeiten als Knöpfe (der Vorschlag hervorgehoben) und ein eigenes Feld. Die Antwort setzt die Rolle fort.
   - Selbstständigkeit: „Entscheidet selbst“ = der Manager entscheidet jede Frage; „Fragt bei Großem“ = Kleines entscheidet er (z. B. Anordnung der Knöpfe), Großes kommt zum Nutzer (Technik, Daten, Kosten, Löschen, Hardware, Sicherheit); „Fragt auch bei Kleinem“ = jede Frage kommt zum Nutzer, immer neu formuliert. Ist der Manager ausgeschaltet, kommt die Frage unverändert.
   - Eine Frage ohne `RESULT: question` (die Rolle hat trotzdem fertig gemacht) geht denselben Weg, hält aber nicht an; die Antwort bekommt der nächste Lauf der Aufgabe.
   - Wartezeit zählt nicht fürs Zeitlimit der Aufgabe.

### 10.2 Schutzmechanismen

| Fall | Bisher | Neu |
|---|---|---|
| `main` hat sich bewegt | Konflikt beim Merge, jede neue Runde scheitert wieder | Vor jedem Programmierer-Lauf holt der Runner `main` in den Branch. Bei Konflikt bleiben die Marker in den Dateien, das Paket nennt sie, der Programmierer löst sie; danach prüft der Runner, dass keine Marker übrig sind (sonst Rückgabe). Konflikt beim Merge nach dem Prüfer: zurück zum Programmierer, nicht zum Nutzer. |
| Mehrere Aufgaben eines Projekts | Start von Hand und Wiederöffnen umgingen die Regel | Eine je Projekt, durchgesetzt an einer Stelle (`agents.take_next`); kein Start von Hand mehr, jeder offene Punkt läuft von selbst. |
| Reihenfolge | klein vor groß | wie in 10.1, Punkt 2 |
| `RESULT:` fehlt | gescheitert, Eskalation | kurzer Nachfrage-Lauf derselben KI ohne Werkzeuge (Bericht, erlaubte Werte, „nur die Zeile“); fehlt sie wieder: Entscheidung |
| Einwand, den der Programmierer nicht beheben kann (fehlende Datei, Gerät, echte Daten) | verbrannte Runden | Regel für Tester und Prüfer: Einwand nur für das, was sich in `/work` ändern lässt; Fehlendes als `<env>`, Merker „von Hand prüfen“, hält nicht auf |
| festgefahren | lief bis zum Rundenende | nach einer Rückgabe ändert der Programmierer nichts: Entscheidung (der Wortvergleich zweier Einwände ist nicht gebaut) |
| zu viele Rückgaben | 3 Runden, dann Endzustand „eskaliert“ | höchstens 6 Rückgaben je Aufgabe, dann Entscheidung |
| Rolle meldet `failed`, Lauf ohne Meldung, Container weg | Eskalation | einmal von selbst wiederholen, beim zweiten Mal Entscheidung |
| KI am Limit, Anmeldung abgelehnt | Schlüssel, dann nächste KI | bleibt (`failures.py`); ist keine KI frei, wartet die Aufgabe ohne Eskalation |
| Runner startet neu | Läufe hingen bis zum Zeitlimit, dann Eskalation | der Runner meldet sich beim Start (`POST /runner/hello`), der Hub stellt dessen laufende Läufe zurück in die Warteschlange |
| Programmierer ändert nichts und meldet fertig | Tester und Prüfer prüften nichts | Entscheidung („nichts geändert“, mit seinem Bericht) |
| viele Rückfragen | – | höchstens 3 anhaltende Rückfragen je Aufgabe, dann Entscheidung |
| Notschalter | beendete die Container, der Lauf begann von vorn | friert ein statt zu beenden (10.8) |
| Zeit | 20 min je Lauf, 2 h je Aufgabe, Ticket gilt 1 h | kein festes Zeitlimit für Arbeit, die vorankommt (10.8) |

**Entscheidung** (`hold = 'decision'`): Die Aufgabe steht, das Projekt wartet. Der Manager erklärt in einfachen Worten, was hakt, und empfiehlt einen Weg (`<stuck recommend="again|accept|cancel">`). „Wartet auf dich“ zeigt die Erklärung und drei Knöpfe, die Empfehlung leuchtet: **Weiter** (optionaler Hinweis an den Programmierer, Rückgaben zurück auf 0), **So übernehmen** (zusammenführen mit Merker „von Hand prüfen“), **Abbrechen** (Punkt in den Papierkorb).

### 10.3 Daten (eine Migration, vorher an einer Kopie der echten Datenbank geprobt)

- `agent_tasks`: id, project_id, item_id, title, kind, **stage** (coding, testing, reviewing, merging, documenting, done, cancelled), **hold** ('', question, todo, decision), **hold_why**, **held_since**, **returns**, **asks**, manual_check, **hint** (Hinweis aus „Weiter“), deadline, created_at, finished_at, diff_stat, diff, tests, tests_exit. Weg: status, round, note, merged. `needs` (any, mac) bleibt (10.8).
- `agent_runs`: zusätzlich **purpose** (work, decide, explain, result, doc); die Manager-Läufe behalten die Rolle `chef`.
- `questions`: zusätzlich **via** (manager: wartet auf den Manager; user), **recommended** (Nummer der Option), **answered_by** (manager, user). Fragen des Manager-Chats und Hinweise (`kind = 'note'`) entfallen; offene Hinweise werden einmalig Einträge in „Für dich“.
- `board_items.status`: zusätzlich `working`. `projects.review_focus` (Text aus dem Prüfer-Tab, geht mit dem Projekt).
- Umwandlung einmalig: offene alte Aufgaben (eskaliert, wartet auf Freigabe) werden `hold = 'decision'` („Aufgabe von vor dem Umbau“); fertige und abgebrochene bleiben. Einstellung `strictness` weg; alte Schlüssel `model.<rolle>` einmal umgeschrieben, der Rückfall in `agents._choice` entfällt.

### 10.4 Schnittstellen

`workflow.py` (rein, ohne Datenbank):
```python
STAGES = ("coding", "testing", "reviewing", "merging", "documenting")
STAGE_ROLE = {"coding": "programmer", "testing": "tester", "reviewing": "reviewer", "documenting": "chef"}
RESULTS = {"programmer": ("done", "question", "blocked", "failed"),
           "tester": ("pass", "fail", "not_testable", "question", "blocked", "failed"),
           "reviewer": ("ok", "objections", "question", "blocked", "failed"), "chef": ("done", "failed")}
MAX_RETURNS, MAX_ASKS = 6, 3

@dataclass(frozen=True)
class Step:
    stage: str; hold: str; returns: int; manual_check: bool; why: str = ""

def after_run(stage, returns, manual_check, result, enabled, *, stuck=False, changed=True, retried=False) -> Step
def after_tests(returns, manual_check, passed: bool, enabled) -> Step
def after_merge(ok: bool, returns, manual_check, enabled) -> Step
def after_decision(choice: str, returns, manual_check, enabled, changed: bool) -> Step   # again | accept | cancel
```
`agents.py`:
```python
take_next(conn, now) -> int          # nächster Punkt je freiem Projekt; ersetzt start_task, start_item, autostart, pick_next
claim_next(can_mac: bool, now=None) -> Job | None
finish_run(run_id, result, report, tokens_in=0, tokens_out=0, seconds=0, now=None,
           change=None, tests=None, markers_left=False) -> bool   # result "none" = Zeile fehlt
answer_question(user_id, question_id, text) -> bool
decide(user_id, task_id, choice, hint="") -> bool     # nur bei hold = decision
cancel(user_id, task_id) -> bool                      # jederzeit, Punkt in den Papierkorb
requeue_running(now=None) -> int                      # Runner-Neustart
pending_merges() / merge_done(task_id, ok)
current_task(user_id, project_id, role=None) -> Task | None
```
Weg: start_task, start_item, autostart, pick_next, item_task, tasks_by_item, waiting_tasks, waiting_reason, _auto_approve, _skip_waiting_tests, Strenge, `Job.note`, Freigabe, `deadline`.
`prompts.py`: Manager-Chat ohne `ASK`; `run()` mit Prüf-Schwerpunkt, Hinweis des Nutzers und Konflikt-Text; neu `decide(conn, question)` und `explain(conn, task)`; Regeln für `RESULT: question` und `<env>` statt Einwand. `reply.py`: `<decide>`, `<stuck recommend>`, `<option recommended>`.
Runner: `Workspace.prepare(...) -> (Path, list[str])` (Konfliktdateien); der Job bringt den Konflikt-Text aus `prompts.py` mit, der Runner hängt nur die Dateinamen an; nach dem Lauf übrige Marker → `markers_left`; fehlende Zeile → Ergebnis `none`; `POST /runner/hello` beim Start; Merge als eigene Stufe.

### 10.5 Oberfläche

- **Board:** nur wartende Punkte und Vorschläge, kompakte Zeilen (Stichpunkt, Kontext zum Aufklappen); keine Aufgabenkarten, kein Start-, Freigabe- oder „Noch eine Runde“-Knopf. Vorschläge: zwei eckige Knöpfe mit weichen Ecken (Rundung 8 px, 30 px hoch), „Annehmen“ grün leuchtend (`--go`), „Ablehnen“ rot leuchtend (`--danger`), Ablehnen legt in den Papierkorb. Eine Zeile oben sagt, woran die Agenten gerade sind oder worauf sie warten.
- **Rollen-Tabs:** „Gerade“ zeigt die Aufgabe im Tab der Rolle, die dran ist, mit „Abbrechen“. Prüfer-Tab: Feld „Worauf achten“ (leer = Korrektheit, Sicherheit, Struktur).
- **„Wartet auf dich“:** neu formulierte Fragen (Möglichkeiten als Knöpfe, Vorschlag hervorgehoben, eigenes Feld), Entscheidungen (Erklärung, drei Knöpfe), Keine Freigaben, keine Umgebungshinweise (die stehen in „Für dich“, 10.8). Antworten erscheinen nie im Manager-Chat.

### 10.6 Entscheidungen mit Vorgabe (gelten, wenn Janis nichts anderes sagt)

1. `hub-test.sh` grün → der Tester läuft trotzdem (prüft das Verhalten, auch im Testbrowser, und kennt das Testergebnis); rot → direkt zurück, ohne KI-Tester. Verworfen: Tester bei grün überspringen (spart Tokens, aber dann prüft nur der Programmierer seine eigenen Tests).
2. Prüf-Schwerpunkt je Projekt im Prüfer-Tab. Verworfen: Abschnitt in RULES.md (unsichtbar).
3. Abgebrochen → Papierkorb (wiederherstellbar). Verworfen: zurück aufs Board (liefe sofort wieder los).
4. Die Rolle heißt in den Daten weiter `chef`; Umbenennen wäre nur Kosmetik quer durch Chat und Einstellungen.

### 10.7 Bau

Drei Branches übereinander, ein Deploy (Hub und Runner gehören zusammen): `chain-core` (Migration, workflow, agents, prompts, reply, Routen, Tests), `chain-runner` (workspace, runner, Tests), `chain-ui` (Board, „Wartet auf dich“, Rollen-Tabs, i18n, DESIGN.md). Dann Migration an einer Kopie der echten Datenbank, Backup, Deploy, ein echter Lauf im Testprojekt. Tests zu Freigabe, Strenge und Start von Hand gehen mit dem Code.

### 10.8 Ergänzungen nach Janis' Rückmeldung (22.11.2026)

**„Für dich“ statt „Wartet auf dich“ für Handarbeit.** Fehlt einer Rolle etwas, das nur der Nutzer beschaffen oder tun kann (Dateien hochladen, ein Gerät anschließen, ein Konto anlegen), meldet sie es mit `<env>`; der Hub legt einen Eintrag in „Für dich“ an (`todos`, Quelle = die Rolle, `task_id`), nie in „Wartet auf dich“. Ob es ohne weitergeht, entscheidet die Rolle selbst mit der Aufgabe vor Augen: geht es, arbeitet sie weiter und lässt das Fehlende offen; geht nichts Sinnvolles, endet sie mit `RESULT: blocked`, die Aufgabe hält an (`hold = 'todo'`). Hakt der Nutzer den Eintrag ab (mit der Notiz, was er getan hat), läuft die Aufgabe weiter, die Notiz steht im Paket. Ebenso landet die Checkliste eines Testers bei `not_testable` als Eintrag in „Für dich“ („Von Hand prüfen: …“). „Wartet auf dich“ ist damit nur noch für Entscheidungen da.

**Antworten nie im Manager-Chat.** Eine Antwort in „Wartet auf dich“ geht an die Rolle oder die Entscheidung, zu der sie gehört; der Chat bekommt keine Nachricht mehr (`routes/manager.answer_question` sendet nichts an `chat.send`).

**Mac bleibt vorgesehen** (PROJEKT.md 4, „Mac-Integration“; das Mac-Programm wird später gebaut). Es bleiben `agent_tasks.needs` (`any`, `mac`) und `claim_next(can_mac)`, dieselbe Schnittstelle für Pi- und Mac-Runner. Der Manager markiert Aufgaben, die ein Apple-Gerät brauchen, mit `<task needs="mac">`. Programmierer und Tester einer solchen Aufgabe laufen nur auf einem Runner mit `can_mac`; Prüfer, Merge und Doku auf dem Pi. Ohne Mac wartet sie sichtbar („wartet auf Mac“), ohne Eskalation. Der Knopf „Lokale Ressourcen verwenden“ (Einmal-Ticket, `agenthub://`) kommt mit dem Mac-Programm. Weg fällt nur das Überspringen von Tests nach der Strenge (ein ungetesteter Mac-Code wäre genau das, was nicht passieren soll).

**Zeit: arbeiten lassen, solange es vorangeht.**
- Heute endet ein Lauf nach 20 Minuten (Einstellung `run_minutes`), eine Aufgabe nach 2 Stunden, und das Ticket eines Laufs gilt nur eine Stunde (`tokens.TICKET_AGE`): ein langer Lauf verlöre mitten in der Arbeit den Zugang.
- Neu: Läufe geben ihre Ausgabe laufend aus (`stream-json` wie im Chat, für alle Adapter). Der Runner beendet einen Lauf nur bei **Stillstand**: keine Ausgabe für eine einstellbare Zeit (Standard 15 min, Auswahl 10 bis 60). Solange Zeilen kommen, läuft er.
- **Höchstdauer je Lauf** nur gegen Ausreißer, großzügig und einstellbar (Standard 4 h, Auswahl 1 bis 12 h). Das Gesamtzeitlimit der Aufgabe entfällt (gegen Endlosschleifen stehen die Grenzen für Rückgaben und Rückfragen).
- Der Runner meldet jeden lebenden Lauf einmal je Minute beim Hub (`POST /runner/runs/{id}/alive`, dabei die neuen Gedanken für die Läufe-Ansicht) und frischt dabei das Ticket auf; tot ist ein Lauf für den Hub erst ohne Meldung (Runner weg).
- Endet ein Lauf an Stillstand oder Höchstdauer, gilt die Arbeit nicht als verloren: der Runner committet den Stand, derselbe Schritt startet noch einmal mit dem Hinweis „dein letzter Lauf wurde nach … beendet, der Stand ist gespeichert, mach dort weiter“. Erst beim zweiten Mal kommt eine Entscheidung (dort: **Weiter** = noch ein Lauf).
- Fest bleibt nur die Zeit der Projekttests (`hub-test.sh`): sie laufen ohne KI und brauchen eine Grenze.

**Pausieren friert ein, beendet nichts.** „KIs pausieren“ hält die laufenden Container an (`docker pause`, die Prozesse stehen still, Arbeitsspeicher und Dateien bleiben), startet nichts Neues und lässt den Manager-Chat frei; „KIs fortfahren“ macht weiter (`docker unpause`), ohne Neustart. Während der Pause stehen Stillstand und Höchstdauer still, das Ticket bleibt gültig. Ein angehaltener Lauf zählt nicht als belegter KI-Platz, damit der Chat geht (auf dem kleinen Server teilen sich dann beide den Speicher). Bricht eine Verbindung der KI während einer langen Pause ab, versucht ihr Programm es selbst noch einmal; scheitert der Lauf trotzdem, greift der Weg von oben (Stand committet, derselbe Schritt noch einmal). Die Tabelle `run_stops` wird zu Paus- und Weiter-Aufträgen für den Runner.

### 10.9 Erste Rückmeldungen von Janis nach dem Umbau (22.11.2026, abends)

- **Was gleich gut lief:** Im Manager-Chat „gib mir Vorschläge für den Taschenrechner“, dann „füge das dem Board hinzu“: die Punkte standen ohne Bestätigung auf dem Board, der Programmierer holte sie sich der Reihe nach, unter „Gerade“ wurden es weniger, der Tester meldete „bestanden“, der Prüfer „in Ordnung“. Die 11 alten Entscheidungen hat Janis durchgeklickt (danach kam keine neue), Selbstständigkeit steht bei ihm auf „Entscheidet selbst“. Der Taschenrechner ist sein Maßstab für die Kette.
- **Folge des Durchklickens:** Die alten Taschenrechner-Aufgaben (10, 11, 15–19) liefen danach parallel im selben Projekt, weil sie von vor dem Umbau stammen (`take_next` legt neue Aufgaben nur an, wenn das Projekt frei ist; alte offene laufen weiter). Ihre Konflikte untereinander löst der Programmierer über `main` im Branch.
- **Gebaut am selben Abend (`roles-on`):** Tester, Prüfer und Manager immer an (Schalter weg); „Gerade“ im Programmierer-Tab in einer Zeile (MacBook, 1470 × 956 geprüft); „Worauf achten“ als Markdown mit Hineinziehen einer Datei und Pfeil zum Herunterladen, nur für den Prüfer, nie in den Dateien; der Status-Pfeil dreht rund (Kreis des Symbols auf 12 | 12); die Trenner rasten an einem feinen Raster ein (Regel für alle Trenner, auch nach jedem Neuladen). Einzelheiten in PROTOKOLL.md.
- **Frage nach den Tokens** („Wie zuverlässig? Pro KI? Geschätzt? Geht etwas unter?“) und die Antwort darauf: 10.10.
- Janis' letzter Satz einer Sprachnachricht war abgeschnitten („Und Objektive, Rabatte und …“), vermutlich ein Fehler der Spracherkennung; nichts daraus umgesetzt.

### 10.10 Verbrauch zuverlässig zählen (Janis, 22.11.2026: „dieser Wert soll zuverlässig sein“)

**Befund vorher:** Geschätzt wurde nichts, die Zahlen kamen aus den Programmen der KIs (Claude Code: `usage` im Ergebnis, Eingabe = Eingabe + in den Zwischenspeicher geschrieben + daraus gelesen; Codex: Summe der Züge; Vibe: aus dem Export der Sitzung; die Schleife des Hubs: Summe der API-Antworten). Es ging aber Verbrauch unter:
- beendete Läufe (Stillstand, Höchstdauer, Abbrechen, Runner-Neustart, abgestürzter Container) zählten 0, weil die Summe erst ganz am Ende kommt;
- Statustexte und Ordnerpläne: ihre Zeilen in `chat_messages` werden nach dem Speichern gelöscht, samt Zahlen;
- Chat-Antworten nach „Chatverlauf löschen“ und ab der 101. Nachricht (das Archiv hat keine Tokens);
- eine Chat-Antwort, die in die Zeit lief, zählte 0;
- das Lesen aus dem Zwischenspeicher zählte bei Claude voll als Eingabe (es wiegt beim Kontingent weniger);
- je KI war nichts sichtbar (nur die Summe je Rolle im Tab).

**Lösung (gebaut und live seit 22.11.2026, `usage`):**
- **Ein Verbrauchsbuch** `ai_usage` (`web/app/usage.py`): eine Zeile je Aufruf einer KI, geschrieben genau dort, wo der Runner ein Ende meldet (`chat.finish`, `agents.finish_run`, also auch Status, Ordnerpläne, Nachfragen, kurze Aufträge des Managers, Wiederholungen nach einem Wechsel der KI). Spalten: Nutzer, Projekt, KI, Modell, Abo oder Schlüssel, Art (`chat`, `status`, `folders`, `run`), Rolle, Zweck, Eingabe gesamt, Ausgabe, davon aus dem Zwischenspeicher gelesen und dorthin geschrieben, Sekunden, `partial` (aus einem beendeten Lauf mitgezählt), Zeitpunkt. Wird nie mit dem Chatverlauf gelöscht; geht mit dem Konto (`ON DELETE CASCADE`), bei einem gelöschten Projekt bleibt die Zeile ohne Projekt (sie gehört zum Konto).
- **Teilverbrauch:** Der Runner zählt mit, was er im Stream sieht: bei Claude Code die `usage` jeder fertigen Antwort (`type: assistant`, je Nachricht einmal), bei Codex und der Schleife des Hubs eine Zeile `{"usage_so_far": …}`, die ihre Startskripte nach jedem Zug ausgeben. Endet ein Lauf ohne Ergebnis (oder eine Chat-Antwort durch die Zeitgrenze), meldet er diese Summe (`partial`). Vibe meldet seinen Verbrauch erst am Ende (Export der Sitzung): ein beendeter Vibe-Lauf zählt weiter 0 (bekannte Lücke).
- **Zwischenspeicher getrennt:** `tokens_in` bleibt die ganze Eingabe; `cache_read` und `cache_write` sind der Anteil davon (heute nur Claude Code, die anderen melden 0).
- **Rückblick einmalig:** die bisherigen Zahlen aus `agent_runs` und `chat_messages` kommen als Zeilen ins Buch (Zwischenspeicher dort unbekannt, also 0).
- **Anzeige:** im Tab jeder Rolle der Verbrauch dieser Rolle im Projekt aus dem Buch (Läufe, Ein/Aus, davon Zwischenspeicher, Zeit); in der Schublade unter jeder verbundenen KI „Heute … · 7 Tage …“.
- **Verworfen:** die Zahlen in `agent_runs` und `chat_messages` weiter flicken (drei Stellen mit eigenen Regeln, und gelöschte Zeilen nehmen ihre Zahlen mit).

### 10.11 Selbst weitermachen: fehlende Dateien und Sichtprüfungen (Janis, 22.11.2026, nachts)

**Rückmeldung:** Beim Kassenbuch bestanden die Rollen immer wieder auf einer CSV-Datei und einer Skizze, die es nicht gibt; Janis musste es dem Manager sagen und die überholten Einträge in „Für dich“ einzeln löschen. Beim Taschenrechner bekam er gesagt, er solle prüfen, wie es im Browser aussieht, obwohl die Rollen einen eigenen Test-Browser haben. Wunsch: Fehlt eine Datei, macht die Rolle von selbst ohne weiter oder legt eine eigene an; Sichtprüfungen macht sie selbst.

**Befund in der Datenbank:** Programmierer und Tester nutzten `hub-browser`, aber nur für Text und Fehler; der Tester ließ „Fokusrahmen und Kontrast nicht visuell geprüft“ offen. Der Prüfer (ohne Werkzeuge, kleiner Diff) machte daraus mit `<env>` Einträge in „Für dich“ („Fokusrahmen im Browser visuell prüfen“, „Grundlagen fehlen“). Der Manager empfahl in seiner Erklärung einer Entscheidung, die Rücktaste „selbst kurz im Browser zu prüfen“; „So übernehmen“ hieß in seinem Text „er prüft es von Hand“. Die Regeln selbst luden dazu ein: `<env>` nannte „Dateien hochladen“ als Beispiel, Tester und Prüfer sollten „eine fehlende Datei“ mit `<env>` melden. Alle verbundenen KIs haben das Werkzeug zum Ansehen von Bildern, die Modelle sehen Bilder, der Test-Browser ist an.

**Lösung (nur Regeltexte in `web/app/prompts.py`, Branch `self-reliant`):**
- **Fehlende Datei** (`RUN_FILES`): Eine Datei, die die Aufgabe nennt und die nicht da ist (CSV, Skizze, Beispieldaten), hält nie auf und wird nie verlangt: die Rolle legt eine kleine eigene Probe in /work an, als solche benannt (z. B. `sample-data.csv`), oder macht ohne weiter und sagt es einmal im Bericht.
- **`<env>` nur für die echte Welt** (`ENV_RULE`): Gerät anschließen oder schalten, Konto anlegen, etwas außerhalb von /work installieren, echte Daten, die eine Probe nicht ersetzen kann. Nie für eine fehlende Datei, eine Sichtprüfung im Browser oder eine Prüfung, die eine andere Rolle machen kann.
- **Sichtprüfung selbst** (`BROWSER`): Aussehen prüft die Rolle selbst mit `--shot` und sieht sich das Bild an (Aufbau, Kontrast, Abgeschnittenes); `--press Tab` vor `--shot` zeigt den Fokusrahmen, `--size 390x844` ein Telefon. Der Prüfer bekommt den Browser jetzt auch, wenn er Werkzeuge hat (großer Diff).
- **Tester:** „schau an, was ein Mensch sieht“; nicht prüfbar ist nur, was Hardware, ein Gerät oder echte Daten braucht (dafür bleibt `not_testable`).
- **Prüfer:** vertraut dem, was der Tester ausgeführt und gesehen hat; ein wichtiger Punkt, den noch niemand geprüft hat, ist ein Einwand (der Programmierer prüft ihn mit seinen Werkzeugen), nie Arbeit für den Nutzer; eine Probe statt einer fehlenden Datei ist in Ordnung.
- **Manager:** im Chat ist eine nicht hochgeladene Datei keine Voraussetzung eines Board-Punkts (der Programmierer macht eine Probe); bei einer Rückfrage einer Rolle (`decide`) heißt eine fehlende Datei „Probe machen oder ohne weiter“, eine Sichtprüfung ist Sache der Rollen; in der Erklärung einer Entscheidung (`explain`) empfiehlt er nie, Aussehen oder Verhalten von Hand zu prüfen oder eine Datei zu liefern, nur Hardware und echte Daten brauchen den Nutzer.
- **Verworfen:** ein Filter im Hub, der `<env>`-Einträge mit Wörtern wie „Browser“ oder „CSV“ verwirft (rät an Sprache herum und schluckt echte Fälle); ein eigener Zustand „Probe statt Datei“ (die Regel reicht, der Bericht nennt es).
