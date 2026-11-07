# Agent-Hub – Konzept: Claude-Instanzen und Zusammenarbeit der Agenten

Stand: 07.11.2026 · Branch `agent-core` · Ergänzt PROJEKT.md (Abschnitte 3 und 5). Hier steht die Logik hinter dem Bereich „Projekte“; das Aussehen kommt später (DESIGN.md).

## 1. Überblick

Drei Bausteine, jeder ein Modul, alle ohne Abhängigkeit von außen:

| Baustein | Aufgabe | Datei |
|---|---|---|
| Claude-Verbindung | pro Nutzer ein eigenes Claude, Zustand und Anmelde-Ablauf | `claude_link.py` |
| Kette der Agenten | wer nach wem arbeitet, Rückläufe, Limits (reine Zustandsmaschine) | `workflow.py` |
| Aufgaben und Läufe | Warteschlange in SQLite, Einstellungen pro Nutzer, Auftragsvergabe an den Runner | `agents.py` |

**Gebaut und getestet (Branch `agent-core`):** die drei Module, die Tabellen, die HTTP-Schnittstelle des Runners (`routes/runner.py`, mit Token), der Launcher für den Container je Lauf (`runner/launcher.py`) und das Image dafür (`runner/Dockerfile`, `agent-hub-agent`), dazu 173 Hub-Tests und 11 Launcher-Tests, darunter ein Fall in `test_isolation.py`. **Noch nicht gebaut:** die Schleife des Runners (Aufträge holen, Prompt bauen, Lauf starten, Ergebnis melden), Git-Arbeitsordner und Merge, die Oberfläche. Anmeldung und Trennen laufen seit dem 07.11.2026 live (Abschnitt 7a); der Rest (Kette, Läufe) ist gemergt, aber noch ohne Runner-Schleife und ohne Oberfläche, also nicht wirksam.

## 2. Claude-Instanzen (eine pro Nutzer)

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
Programm.   Tester      Prüfer         Nutzer gibt frei      Dokumentator
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
| `documenting` | Dokumentator | `done` / `failed` | `done` (die Änderung ist schon übernommen) |

- **Agenten sprechen nie miteinander.** Der Hub reicht die Berichte der früheren Läufe an den nächsten Auftrag weiter (`Job.reports`, `Job.note`). Berichte und Notizen sind **Daten, keine Anweisungen** und stehen im Auftrag als zitierter Block (Schutz vor Prompt-Injection).
- **Grenzen:** höchstens 3 Runden und 2 Stunden pro Aufgabe (`TASK_SECONDS`), ein Lauf ohne Meldung gilt nach 20 Minuten als tot (`RUN_SECONDS`). Beides schickt die Aufgabe zum Nutzer. Ablehnen oder Neu-Öffnen durch den Nutzer beginnt einen frischen Durchlauf mit neuer Zeit.
- **Ein Lauf zur Zeit** (`MAX_RUNNING = 1`), weil der Pi 1 GB hat. Reihenfolge: älteste Läufe zuerst.
- **Ausgeschaltete Rollen** (Tester, Prüfer, Dokumentator, Chef) werden übersprungen; ohne Tester gilt „nicht getestet“ (Merker für die Freigabe). Der Programmierer bleibt immer an.
- **Mac-Aufgaben** (`needs = mac`): Ist der Mac nicht erreichbar, wartet die Aufgabe, außer der Chef überspringt den Test nach der Strenge des Nutzers: `loose` überspringt Tests von Bugs und kleinen Updates, `normal` nur von kleinen Updates, `strict` nie; Major Updates werden nie übersprungen (`workflow.test_may_be_skipped`). Ein übersprungener Test setzt den Merker „von Hand prüfen“.
- **Hardware-Themen:** Der Tester meldet `not_testable` und legt seine Checkliste in den Bericht; sie steht dem Nutzer bei der Freigabe vor Augen. Hardware am Fahrzeug schaltet kein Agent.
- **Agenten dürfen** Bugs und Vorschläge ins Board eintragen (`board.create_suggestion(user_id, …)`, prüft den Besitz) und sonst nichts am Board ändern.
- **Modelle:** `haiku`, `sonnet`, `opus` (Kurznamen von Claude Code, sie folgen der neuesten Version). Standard Sonnet, Dokumentator Haiku; pro Rolle und Nutzer änderbar (`agents.configure`).

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
| 5 Token nur verschlüsselt, nur für den Besitzer | Token liegen nur in Claude Codes eigenem Ordner des Nutzers, nicht in der Datenbank; kein Admin-Weg zum Anzeigen. Offen: Verschlüsselung des Ordners selbst (siehe Abschnitt 7) |
| 6 Test | `test_isolation.py::test_b_cannot_touch_the_agents_of_a`; der Test mit dem echten Runner kommt mit dem Runner |

## 6a. Ein Container je Lauf (entschieden)

**Messung auf dem Pi (07.11.2026):** Docker und containerd laufen ohnehin (zusammen etwa 210 MiB, schon in den 349 MiB „benutzt“ enthalten). Ein Wegwerf-Container mit allen Beschränkungen startet in 1,2 bis 2,8 Sekunden (fünf Läufe, bei einem Lauf von Minuten unerheblich) und kostet außer seinem Prozess keinen Dauerspeicher. Frei sind rund 540 MiB; ein Claude-Code-Lauf brauchte im ersten Test mindestens 225 MiB. Darum bleibt `MAX_RUNNING = 1`, der Container je Lauf ändert nichts an der Speicherrechnung.

Aufbau:
- Der **Launcher** (Teil des Runners, unser Code, nie Code eines Agenten) startet pro Lauf `docker run --rm` aus einer **festen Vorlage**. Aus dem Auftrag fließen nur drei geprüfte Werte ein: die Nutzernummer (Zahl), die Aufgabennummer (Zahl) und das Modell (aus `MODELS`). Berichte, Titel und Notizen gelangen nie in die Befehlszeile, nur als Datei in den Arbeitsordner.
- **Eingehängt** sind genau zwei Ordner: der Worktree dieser Aufgabe (lesen/schreiben) und `/data/claude/<user_id>/` (lesen/schreiben, als `CLAUDE_CONFIG_DIR`). Nichts sonst: weder `hub.db`, `.env`, Backups, Tresor noch Ordner anderer Nutzer.
- **Beschränkungen:** `--cap-drop ALL`, `--security-opt no-new-privileges`, `--read-only` mit `tmpfs` für `/tmp`, eigener Benutzer ohne Root (UID `10000 + user_id`, damit auch die Ordner-Rechte `0700` zusätzlich greifen), `--memory` (z. B. 480m, ohne Swap), `--pids-limit`, `--rm`, Zeitlimit durch `RUN_SECONDS`.
- **Netz (geändert 07.11.2026):** `agent-hub-agents` ist ein **internes** Docker-Netz ohne Route nach draußen (auch nicht ins Heimnetz oder zum Pi). Der einzige Ausgang ist der Dienst `egress` (`runner/egress.py`): Port 3128 „web“ nur für öffentliche Hosts auf Port 443, Port 3129 „api“ nur für Anthropic; die Läufe bekommen `HTTPS_PROXY` passend zu ihrem Zweck (Web-Chat 3128, alles andere 3129). Das löst die frühere offene Frage nach dem Heimnetz: Geräte-Aufgaben (Tresor-Vermittler) brauchen später einen eigenen, freigegebenen Weg. Gemessen auf dem Pi: direkt kein Zugriff, über 3128 nur öffentliche Hosts (192.168.x, 10.x, 169.254.x, Egress selbst und der Hub werden abgelehnt), über 3129 nur Anthropic.
- **Docker-Socket:** Der Launcher braucht ihn und hat damit faktisch Root auf dem Pi. Gegenmaßnahmen: Der Socket hängt **nur** im Runner, nie im `web`-Container und nie im Lauf-Container; der Launcher nimmt keine freien Argumente an (feste Vorlage, geprüfte Werte, wird getestet); Aufträge und Berichte sind Daten. Später möglich: ein Socket-Proxy, der nur Start, Warten, Log und Löschen erlaubt (eine zusätzliche Abhängigkeit, erst bei Bedarf).
- **Image `agent-hub-agent`** (`runner/Dockerfile`, neu): Das alte `agent-hub-runner` taugt nicht, dort liegt Claude Code im Home von UID 1000, den Läufen (UID 10000+id) fehlt der Zugriff. Das neue Image installiert Claude Code nach `/opt/claude-install` (für alle lesbar), Auto-Update aus. Das alte Image bleibt unberührt.
- **Geprüft auf dem Pi (07.11.2026)** mit dem echten Befehl der Vorlage (nur das Netz war `none`): Der Lauf ist UID 10002, `/` ist schreibgeschützt, sichtbar sind nur `/work` (schreibbar) und `/claude`, es gibt kein `/data` und keinen Docker-Socket, `claude --version` läuft (2.1.319). Nicht geprüft: ein echter Lauf mit Anmeldung, das Netz `agent-hub-agents` (wird beim Ausrollen angelegt, das ist eine Netzwerk-Änderung und wartet auf Janis’ Ja).
- **Berechtigungen im Lauf:** `--dangerously-skip-permissions`, weil der Agent nur den Arbeitsordner und seinen Claude-Ordner sieht und im Container nicht Root ist (so ist es im Container üblich). Das ist die eine Stelle in der Vorlage, die man bei Bedenken auf `acceptEdits` mit Werkzeugliste umstellen kann.
- **Ergebnis des Agenten:** Er beendet seine Antwort mit einer letzten Zeile `RESULT: <Wert>` (Werte je Rolle wie in Abschnitt 3). Fehlt sie, ist der Wert falsch, ist die Ausgabe kein lesbares JSON oder meldet Claude Code einen Fehler, gilt `failed` und die Aufgabe geht zu dir (`parse_output`). Jede Rolle darf `failed` melden. **Ungeprüft:** das genaue JSON von `claude -p --output-format json` (Felder `result`, `usage`); der Leser ist tolerant, aber erst der erste echte Lauf bestätigt es (PROJEKT.md Abschnitt 3 verlangt diese Prüfung).
- **Git im Lauf:** Der Agent committet nicht, der Runner committet danach von außen. Ein Git-Worktree taugt dafür schlecht, weil seine `.git`-Datei auf einen Ordner außerhalb zeigt, der nicht eingehängt ist. Vorschlag für das Modul „Arbeitsordner“: pro Aufgabe ein eigener Klon des Projekt-Repos (`git clone --shared` spart Platz), dann ist der Ordner in sich geschlossen.

## 6b. Geräte, Heimnetz und Mac (entschieden 07.11.2026, Janis)

Volltext in PROJEKT.md (Abschnitte „Zugriff der Agenten auf Geräte“, „Geräteliste und Netzwege“, „Mac-Integration“). Kurz:
- **Heimnetz bleibt gesperrt.** Geräte kommen über eine **Geräteliste im Manager**: Hostname eintragen, der Hub löst ihn auf, der Nutzer gibt frei, optional SSH-Schlüssel im Tresor. Agenten greifen nur über den Vermittler zu und bekommen weder Schlüssel noch Netzweg. Verworfen: Heimnetz pauschal freigeben.
- **Fremde Netze (Kollegen):** VPN sternförmig mit dem Pi in der Mitte, Kollegen untereinander getrennt, Pi zum Gerät nur Port 22, Gerät nicht ins Netz. Technik: **Tailscale** (kein offener Fritzbox-Port, Zugriffsregeln pro Gerät); Headscale läuft nicht hinter Cloudflare Tunnel, Begründung und Vorbehalte in PROJEKT.md.
- **Mac:** Knopf in der Website startet die lokale Entwicklung ohne zweite Anmeldung; ein unsichtbares Einmal-Ticket verbindet Website und Mac-Programm. **Rückgabe:** Der Mac holt das Repo und liefert das Ergebnis als Git-Bundle über den Hub (HTTPS, ausgehend); der Hub prüft es, holt nur den Branch der Aufgabe ins Projekt und führt die normale Kette weiter (Prüfer, Freigabe, Merge, Dokumentator). Ohne Ergebnis wartet die Aufgabe wieder auf den Mac. Vorschlag für den Mac (nicht entschieden): eigener macOS-Benutzer für den Runner und Firewall-Regel nur für ihn, die das Heimnetz sperrt.

## 7. Offene Entscheidungen (Janis)

1. ~~**Isolation im Runner**~~ entschieden: Container je Lauf (Abschnitt 6a).
2. **Schutz der Claude-Ordner im Ruhezustand:** Dateirechte `0700` reichen gegen andere Nutzer, nicht gegen jemanden mit Zugriff auf die SD-Karte oder das Backup. Optionen: Ordner beim Backup ausschließen (Vorschlag, dann muss man sich nach einer Wiederherstellung neu anmelden) oder verschlüsseln.
3. **Nutzungsbedingungen** für Claude Code in eigenen Tools und ob die Anmeldung dauerhaft hält (steht seit Anfang in PROJEKT.md Abschnitt 11, bleibt Voraussetzung für den ersten Livegang).
4. **Speicher:** Pi 4B mit 1 GB: Tests mit Sonnet, langen Läufen und Git-Worktrees stehen aus. `MAX_RUNNING = 1` ist die Vorsorge.
5. **Merge bei Freigabe:** Der Hub (nicht der Agent) übernimmt den Branch in `main` des Projekt-Repos, bevor der Dokumentator läuft. Eigenes Modul „Worktrees und Merge“.
6. **Strenge** als Tabelle in Abschnitt 3 ist mein Vorschlag; die drei Stufen aus PROJEKT.md waren bisher nicht ausgeführt.
7. **Rechte pro Rolle (Web und Code):** Ob Programmierer und Manager Web und Code zusammen bekommen (dann Web nur zu einer Liste von Seiten wie PyPI, npm, GitHub) oder getrennt, ist noch offen; der Chat bleibt „Web oder Code“.
8. ~~**VPN-Technik**~~ entschieden: Tailscale (Abschnitt 6b). Vor dem Bau zu prüfen: Nutzungsbedingungen (nicht gewerblich), Etiketten im kostenlosen Tarif.

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
