# Agent-Hub – Übergabe an einen neuen Chat

Stand: 20.11.2026 (Durchsicht des ganzen Systems und Umbau der KI-Pakete) · Zweck: Einstieg in einen neuen Chat. Quelle der Wahrheit: `PROJEKT.md` („Auf einen Blick“, Fahrplan in 11a), `PROTOKOLL.md` (alle Änderungen, neueste zuerst), `KONZEPT-AGENTEN.md` (9.2a Werkzeuge je KI, 9.3a Pakete je Rolle), `DESIGN.md`, `CLAUDE.md`. Die vorige Übergabe (bis 19.11.2026) liegt in `archiv/CHAT-ZUSAMMENFASSUNG-2026-11-19.md`.

## In einem Satz

Selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B, live unter `https://hub.janis-home.de`: Projekte, Board für Software, je Projekt ein Manager-Chat, Agentenkette (Programmierer, Tests, Prüfer, Freigabe, Doku), Dateiablage, Geräte über einen Vermittler. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was am 20.11.2026 passiert ist

- **Durchsicht** von Doku und Code mit echten Zahlen aus der Datenbank: Programmierer im Schnitt 108 000 Eingabe-Tokens je Lauf, Tester 109 000, Prüfer 62 000; 6 von 19 Aufgaben eskaliert, keine wegen eines schwachen Modells (leerer Arbeitsordner, weil der Code in der Ablage lag; kein Node; Folgepunkte nach einer Eskalation).
- **Gebaut und live** (Einzelheiten in PROTOKOLL.md, oberster Eintrag): Zugangsdaten nur bei klarer Ablehnung löschen; nach Lesen im Web warten neue Board-Punkte auf das Ja; Gateway nur mit nötigen Pfaden; Tester und Prüfer ohne Internet; Diff für Tester, Prüfer und Freigabe; `hub-test.sh` führt der Hub selbst aus; Node im Agenten-Image; Eskalation hält die Folgepunkte an; **Pakete je Rolle** (`web/app/prompts.py`); **Werkzeuge je KI im Katalog**; Erinnerung per Abschnitt; englische Namen der Erinnerungsdateien; Ansichten `/files` zwischengespeichert; jeder Runner-Auftrag meldet sein Ende; Altlasten entfernt; CLAUDE.md nach Themen geordnet; Änderungsprotokoll in PROTOKOLL.md.
- **Entschieden von Janis:** Automatik aus dem Chat bleibt (ohne Bestätigung); Schlüssel werden bei Ablehnung gelöscht, nie wenn der Server sie nicht lesen kann; jede KI soll anbindbar sein, mit eigenem Werkzeug oder Ersatz vom Hub (Kacheln Claude, Mistral, ChatGPT, „Eigene KI“).
- **Bewusst nicht gemacht:** WAL-Modus für SQLite (das Backup als root ließe Dateien zurück, die der Web-Dienst nicht öffnen kann; stattdessen 15 s Wartezeit). PROJEKT.md weiter verdichten (nur mechanisch geteilt, kein Inhalt gelöscht).

## Was am 21.11.2026 dazukam

- **ChatGPT über Codex** (`chatgpt`): Anmeldung mit dem ChatGPT-Konto per Gerätecode, Tokens erneuert nur der Runner, Läufe mit Ticket-Hülle über Gateway 3133; Modell-Listen täglich von jeder KI selbst; Werkzeug-Ersatz nur bei klarem Befund. **Noch nie echt gelaufen:** Janis meldet sich einmal an, dann prüfen: Chat, Agentenlauf, Modell-Liste, Go-Abo.

## Was als Nächstes ansteht

1. ~~Ersatzwerkzeuge~~ **live seit 20.11.2026, abends (`own-ai`):** „Eigene KI“ in der Schublade (jede API im OpenAI-Format, auch lokal beim Owner), `runner/hubloop.py`, `runner/hub_tools.py`, Gateway 3132, Werkzeugzeile unter jeder KI. **Noch nie echt gelaufen** (kein Konto bei einer solchen API verbunden); offen: Werkzeuge je KI auf `/admin` umschaltbar, Bilder für die eigene KI.
2. **Diff in der Oberfläche** bei der Freigabe (Daten liegen schon in `agent_tasks.diff`).
3. Ein echter Lauf mit `hub-test.sh` in einem JavaScript-Projekt und ein echter Prüfer-Lauf ohne Werkzeuge (nur mit Tests geprüft).
4. Die 6 eskalierten Aufgaben in den Testprojekten aufräumen (abbrechen oder neu starten); eskalierte Punkte mit Automatik halten ihr Projekt jetzt an.

## Wie Claude hier arbeitet

Deutsch antworten, kurz erklären, keine Verständnisfragen am Ende; erst Schnittstelle, dann Code; kleinste Lösung; ein Thema pro Commit, ein Branch pro Aufgabe; Routine ohne Rückfrage. Tests immer mit leerem `/data`; Diagnosebefehle geben nie Geheimnisse aus. Arbeitsplatz Mac: Klon vom Pi im Scratchpad, Tests mit `~/wtcl.sh <branch>` (Web) und `~/rtcl.sh <branch>` (Runner) auf dem Pi (eigene Worktrees `~/hub-test-cl`, `~/hub-test-clr`).
