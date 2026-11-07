# Agent-Hub – Konzept: Claude-Instanzen und Zusammenarbeit der Agenten

Stand: 07.11.2026 · Branch `agent-core` · Ergänzt PROJEKT.md (Abschnitte 3 und 5). Hier steht die Logik hinter dem Bereich „Projekte“; das Aussehen kommt später (DESIGN.md).

## 1. Überblick

Drei Bausteine, jeder ein Modul, alle ohne Abhängigkeit von außen:

| Baustein | Aufgabe | Datei |
|---|---|---|
| Claude-Verbindung | pro Nutzer ein eigenes Claude, Zustand und Anmelde-Ablauf | `claude_link.py` |
| Kette der Agenten | wer nach wem arbeitet, Rückläufe, Limits (reine Zustandsmaschine) | `workflow.py` |
| Aufgaben und Läufe | Warteschlange in SQLite, Einstellungen pro Nutzer, Auftragsvergabe an den Runner | `agents.py` |

**Gebaut und getestet (Branch `agent-core`):** alle drei Module, Tabellen, 25 neue Tests, darunter ein Fall in `test_isolation.py`. **Noch nicht gebaut:** der Runner selbst (Claude Code starten), die HTTP-Schnittstelle des Runners, die Oberfläche, Git-Worktrees und der Merge. Ohne Runner läuft die Kette nur in den Tests. Der Branch ist nicht in `main` gemergt und nicht ausgerollt.

## 2. Claude-Instanzen (eine pro Nutzer)

- **Zustand:** `none` → `connecting` → `connected` → `expired` → `connecting` … (Tabelle `claude_connections`). Die Datenbank speichert nur den Zustand und den kurzlebigen Anmelde-Link, **nie** Token oder Code.
- **Zugangsdaten** legt Claude Code selbst in den Ordner des Nutzers: `claude_link.config_dir(user_id)` = `/data/claude/<user_id>/` (`CLAUDE_CONFIG_DIR` und `HOME` seiner Läufe). Der Web-Container hängt diesen Ordner nicht ein, nur der Runner.
- **Ablauf der Anmeldung** (der Nutzer gibt nie Benutzername oder Passwort ein):
  1. Nutzer drückt „Claude verbinden“ → `begin(user_id)`, Zustand `connecting`.
  2. Der Runner sieht die Anfrage, startet `claude` mit dem Ordner dieses Nutzers und meldet den Anmelde-Link zurück → `set_login_url` (nur `https` zu claude.ai, claude.com oder anthropic.com, sonst abgelehnt).
  3. Die Maske zeigt den Link. Der Nutzer bestätigt bei Claude und gibt den angezeigten Code in die Maske ein.
  4. Der Code geht **flüchtig** (nur im Arbeitsspeicher, nie in die Datenbank, nie ins Log) an den Runner, der ihn Claude Code übergibt → `complete(user_id, ok)`.
  5. Wer 10 Minuten nichts bestätigt, fällt auf `none` zurück (`CONNECT_TIMEOUT`).
- **Abgelaufen:** Meldet Claude Code „nicht angemeldet“, setzt der Runner `mark_expired`. Die Aufgaben des Nutzers warten dann (`waiting_reason` = `no_claude`), die Maske zeigt „Verbindung abgelaufen“ mit Knopf zum Erneuern.
- **Trennen:** `disconnect(user_id)` löscht den Eintrag, der Runner löscht danach den Ordner.
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

**HTTP für den Runner (nächstes Modul):** Der Runner ruft nur aus und fragt nach, wie der Mac-Runner später auch (gleiche Schnittstelle): `POST /runner/claim`, `POST /runner/runs/{id}/finish`, dazu die Anmelde-Aufrufe. Er weist sich mit einem eigenen Runner-Token aus der `.env` aus (nur als Hash verglichen, nie mit Nutzer-Sitzungen vermischt). Die Pfade liegen auf dem internen Docker-Netz, nicht im Tunnel.

## 6. Trennung der Konten, so umgesetzt

| Pflichtregel (PROJEKT.md Abschnitt 3) | Umsetzung |
|---|---|
| 1 Ordner pro Nutzer | `config_dir(user_id)`; Janis’ bestehende Anmeldung wird sein Ordner `/data/claude/<seine id>/` |
| 2 Kein Rückfall | `claim_next` nimmt nur Läufe von Nutzern mit Zustand `connected` |
| 3 Lauf sieht nur seinen Nutzer | **Vorschlag:** Ein Runner-Container (ohne `hub.db`, `.env`, Backups, Tresor) startet jeden Lauf als eigenen Prozess unter einer eigenen Unix-Kennung je Nutzer (z. B. `10000 + user_id`), Ordner `0700`, `HOME` und `CLAUDE_CONFIG_DIR` auf seinen Ordner, Arbeitsordner nur der Worktree dieser Aufgabe. Verworfen: Docker-Socket für einen Container je Lauf (würde dem Runner Root auf dem Pi geben). Entscheidung und Test stehen aus. |
| 4 Nutzer vom Server | `Job.user_id` kommt aus `agent_tasks` → `projects`, `finish_run` und `claim_next` nehmen keinen Nutzer entgegen |
| 5 Token nur verschlüsselt, nur für den Besitzer | Token liegen nur in Claude Codes eigenem Ordner des Nutzers, nicht in der Datenbank; kein Admin-Weg zum Anzeigen. Offen: Verschlüsselung des Ordners selbst (siehe Abschnitt 7) |
| 6 Test | `test_isolation.py::test_b_cannot_touch_the_agents_of_a`; der Test mit dem echten Runner kommt mit dem Runner |

## 7. Offene Entscheidungen (Janis)

1. **Isolation im Runner:** eigene Unix-Kennung je Nutzer in einem Runner-Container (Vorschlag) oder ein Container je Lauf mit Docker-Socket (stärker, aber Root-Risiko).
2. **Schutz der Claude-Ordner im Ruhezustand:** Dateirechte `0700` reichen gegen andere Nutzer, nicht gegen jemanden mit Zugriff auf die SD-Karte oder das Backup. Optionen: Ordner beim Backup ausschließen (Vorschlag, dann muss man sich nach einer Wiederherstellung neu anmelden) oder verschlüsseln.
3. **Nutzungsbedingungen** für Claude Code in eigenen Tools und ob die Anmeldung dauerhaft hält (steht seit Anfang in PROJEKT.md Abschnitt 11, bleibt Voraussetzung für den ersten Livegang).
4. **Speicher:** Pi 4B mit 1 GB: Tests mit Sonnet, langen Läufen und Git-Worktrees stehen aus. `MAX_RUNNING = 1` ist die Vorsorge.
5. **Merge bei Freigabe:** Der Hub (nicht der Agent) übernimmt den Branch in `main` des Projekt-Repos, bevor der Dokumentator läuft. Eigenes Modul „Worktrees und Merge“.
6. **Strenge** als Tabelle in Abschnitt 3 ist mein Vorschlag; die drei Stufen aus PROJEKT.md waren bisher nicht ausgeführt.

## 8. Reihenfolge der nächsten Module

1. Runner-Schnittstelle (HTTP, Runner-Token) und Runner-Programm für den Pi, mit Isolationstest für zwei Nutzer.
2. Anmeldung in der Oberfläche („Claude verbinden“ in der Schublade statt des Platzhalters, Zustand „abgelaufen“).
3. Worktrees und Merge.
4. Station „Agenten“ in der Projektansicht (Aufgaben, Freigabe mit Klick-Aussagen, Verbrauch), danach Design.
5. Chef als Lauf (Priorisierung, Status für die Kachel), Tester-Checklisten, Mac-Runner.
