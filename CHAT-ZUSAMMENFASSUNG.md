# Agent-Hub – Übergabe an einen neuen Chat

Stand: 20.11.2026 (Durchsicht des ganzen Systems und Umbau der KI-Pakete) · Zweck: Einstieg in einen neuen Chat. Quelle der Wahrheit: `PROJEKT.md` („Auf einen Blick“, Fahrplan in 11a), `PROTOKOLL.md` (alle Änderungen, neueste zuerst), `KONZEPT-AGENTEN.md` (9.2a Werkzeuge je KI, 9.3a Pakete je Rolle), `DESIGN.md`, `CLAUDE.md`. Die vorige Übergabe (bis 19.11.2026) liegt in `archiv/CHAT-ZUSAMMENFASSUNG-2026-11-19.md`.

## In einem Satz

Selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B, live unter `https://hub.janis-home.de`: Projekte, Board für Software, je Projekt ein Manager-Chat, Agentenkette (Programmierer, Tests, Prüfer, Freigabe, Doku), Dateiablage, Geräte über einen Vermittler. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was am 20.11.2026 passiert ist

- **Durchsicht** von Doku und Code mit echten Zahlen aus der Datenbank: Programmierer im Schnitt 108 000 Eingabe-Tokens je Lauf, Tester 109 000, Prüfer 62 000; 6 von 19 Aufgaben eskaliert, keine wegen eines schwachen Modells (leerer Arbeitsordner, weil der Code in der Ablage lag; kein Node; Folgepunkte nach einer Eskalation).
- **Gebaut und live** (Einzelheiten in PROTOKOLL.md, oberster Eintrag): Zugangsdaten nur bei klarer Ablehnung löschen; nach Lesen im Web warten neue Board-Punkte auf das Ja; Gateway nur mit nötigen Pfaden; Tester und Prüfer ohne Internet; Diff für Tester, Prüfer und Freigabe; `hub-test.sh` führt der Hub selbst aus; Node im Agenten-Image; Eskalation hält die Folgepunkte an; **Pakete je Rolle** (`web/app/prompts.py`); **Werkzeuge je KI im Katalog**; Erinnerung per Abschnitt; englische Namen der Erinnerungsdateien; Ansichten `/files` zwischengespeichert; jeder Runner-Auftrag meldet sein Ende; Altlasten entfernt; CLAUDE.md nach Themen geordnet; Änderungsprotokoll in PROTOKOLL.md.
- **Entschieden von Janis:** Automatik aus dem Chat bleibt (ohne Bestätigung); Schlüssel werden bei Ablehnung gelöscht, nie wenn der Server sie nicht lesen kann; jede KI soll anbindbar sein, mit eigenem Werkzeug oder Ersatz vom Hub (Kacheln Claude, Mistral, ChatGPT, „Eigene KI“).
- **Bewusst nicht gemacht:** WAL-Modus für SQLite (das Backup als root ließe Dateien zurück, die der Web-Dienst nicht öffnen kann; stattdessen 15 s Wartezeit). PROJEKT.md weiter verdichten (nur mechanisch geteilt, kein Inhalt gelöscht).

## Stand mitten im Auftrag (21.11.2026, Zwischenstand vor dem Komprimieren des Chats)

**Fertig und getestet, Deploy steht aus:** Branch `chatgpt` (ChatGPT über Codex, Modell-Listen, Werkzeug-Prüfung). Die ganze Web-Suite lief beim Schreiben; danach `bash ~/deploy-chatgpt.sh` auf dem Pi (Skript im Scratchpad als `deploy-chatgpt.sh`, baut zusätzlich `agent-hub-codex`). Die Runner-Tests (184) sind grün.

**In Arbeit (Branch `api-option`, auf `chatgpt` aufgesetzt):** erst `web/app/credentials.py` geschrieben, sonst nichts. Der Plan, von Janis am 21.11.2026 so bestellt:

1. **API-Option für Claude und ChatGPT** (Abo und Schlüssel nebeneinander):
   - Der Verknüpfen-Dialog wird zweispaltig (bis etwa 760 px, auf dem Handy untereinander): links „Mit Abo anmelden“ mit kurzer Info und dem heutigen Ablauf (ein Hauptknopf), rechts „Mit API-Schlüssel“: Schlüsselfeld, Hinweis „Kann Zusatzkosten verursachen. Prüfe die Preise und setze eine Ausgabengrenze bei deinem Anbieter.“ (allgemein, kein fester Preis), Einstellungen, normaler Knopf „Speichern“, Link „Schlüssel entfernen“.
   - Einstellungen je Nutzer und KI (`agent_settings` `api.<anbieter>.mode/scope/daily`): **Modus** „Erst wenn das Abo aufgebraucht ist“ (Standard) / „Immer statt Abo“ (das Abo-Kontingent bleibt) / „Aus“; **Bereich** Chat und Agenten / nur Agentenläufe / nur Chat; **Tagesgrenze** in Tausend Tokens (0 = keine). Weitere Sonderfälle bei Bedarf, Bedienung kompakt.
   - Technik: der Schlüssel ist eine eigene Verbindung (`ai_connections` `claude-api`, `chatgpt-api`), geprüft vom Runner (Anthropic `GET /v1/models` mit `x-api-key`, OpenAI `GET /v1/models`). Neue Spalten `chat_messages.credential`, `agent_runs.credential` („plan“ oder „api“). Wechsel Abo → Schlüssel bei Fehlerart `limit` innerhalb derselben KI, bevor die nächste KI einspringt (Chat und Läufe). Gateways erkennen die Art am echten Geheimnis: Claude `sk-ant-api…` → Kopf `x-api-key` statt OAuth, ChatGPT `sk-…` → `api.openai.com/v1/responses` statt `chatgpt.com/backend-api`; die Läufe bekommen weiter nur ein Ticket (Claude Code `ANTHROPIC_API_KEY=Ticket`, Codex eigener Anbieter mit `env_key`).
   - Designvorgaben prüfen: Glas, Lichtkante, `.has-select` für Auswahlfelder, ein Hauptknopf je Dialog, kein `title` per Skript, Texte in `i18n.py`.
2. **Allgemeine Kachel statt „Eigene KI“**, neuer Name „Weitere KI“ (Vorschlag; „allgemeine Anbindung“ verworfen, weil zu technisch): bleibt immer stehen, damit man jederzeit eine weitere verbindet; jede verbundene ist eine eigene Zeile mit selbst gewähltem Namen (mehrere je Nutzer). Ein Name je Verbindung, Modell aus `GET /models` als Drop-down statt Eintippen.
3. **Platzhalter** für KIs, bei denen sich ein eigener Adapter lohnt (eigenes Programm, eigene Abo-Anmeldung): **Gemini** (Gemini CLI, Google-Konto) und **GitHub Copilot** (Copilot CLI, GitHub-Abo); alles andere über die allgemeine Kachel.
4. **KI im Heimnetz:** Janis' Gedanke ist genau der Ansatz von `own-ai`: Eine Adresse im eigenen Netz des Servers gibt der Owner frei, **neu als Schalter in den Systemeinstellungen** (heute automatisch für die eigene KI des Owners); die lokale KI eines Kollegen bei ihm zu Hause ist von hier nicht erreichbar, außer sie ist öffentlich erreichbar (eigener Tunnel, HTTPS): dann braucht es keine Freigabe; eine KI auf einem Server im Internet ebenso nicht. **Später:** Geräte und KIs in fremden Netzen über ein VPN (Tailscale, Adressen 100.64/10, schon als Heimnetz-Adresse erlaubt), siehe PROJEKT.md Abschnitt 4 „Geräteliste und Netzwege“.
5. Danach alles ordentlich dokumentieren (PROTOKOLL.md, PROJEKT.md, DESIGN.md für den Dialog, CLAUDE.md).

**Erkenntnisse aus diesem Chat (für spätere Entscheidungen):**
- Abo und API liefern dieselben Modelle und dieselbe Qualität bei gleichem Tokenverbrauch. Unterschiede: Kosten nach Verbrauch, keine Wochengrenze, sauberere Nutzungsbedingungen für Automatisierung, Schlüssel ohne Ablauf, alle Modelle, Ausgabengrenze beim Anbieter.
- Das Chat-Format von OpenAI ist der gemeinsame Standard fast aller Anbieter (auch Gemini und Anthropic per Kompatibilitätsadresse, lokal Ollama, LM Studio, vLLM); Unterschiede bei Werkzeugaufrufen, Bildern, Denkstufe.
- Codex: ist das Programm, die Modelle sind die GPT-Familie; das normale Chat-Backend von ChatGPT ist keine Schnittstelle für fremde Programme. Ob das Go-Abo Codex enthält, ist widersprüchlich dokumentiert; ohne Freigabe lehnt der Server jedes Programm ab (Meldung „Abo ohne Codex“); sich als die Desktop-App auszugeben scheidet aus (vorgetäuschte Programmkennung, wie bei Claude am 14.11.2026). Codex verbindet sich standardmäßig per WebSocket; mit eigenem Anbieter-Eintrag (`supports_websockets = false`) nimmt es einfache Anfragen; es nimmt die Ticket-Hülle an und erneuert nicht selbst (mit Schein-Server erprobt).
- Eigene Werkzeuge der KIs sind fast immer besser und sparsamer (darauf trainiert, im zwischengespeicherten Teil des Pakets); der Ersatz des Hubs kostet je Schritt 1000 bis 2000 Tokens mehr, die Textform am meisten. Deshalb Ersatz nur bei klarem Befund (`toolcheck.py`).

## Was am 21.11.2026 dazukam

- **ChatGPT über Codex** (`chatgpt`): Anmeldung mit dem ChatGPT-Konto per Gerätecode, Tokens erneuert nur der Runner, Läufe mit Ticket-Hülle über Gateway 3133; Modell-Listen täglich von jeder KI selbst; Werkzeug-Ersatz nur bei klarem Befund. **Noch nie echt gelaufen:** Janis meldet sich einmal an, dann prüfen: Chat, Agentenlauf, Modell-Liste, Go-Abo.

## Was als Nächstes ansteht

1. ~~Ersatzwerkzeuge~~ **live seit 20.11.2026, abends (`own-ai`):** „Eigene KI“ in der Schublade (jede API im OpenAI-Format, auch lokal beim Owner), `runner/hubloop.py`, `runner/hub_tools.py`, Gateway 3132, Werkzeugzeile unter jeder KI. **Noch nie echt gelaufen** (kein Konto bei einer solchen API verbunden); offen: Werkzeuge je KI auf `/admin` umschaltbar, Bilder für die eigene KI.
2. **Diff in der Oberfläche** bei der Freigabe (Daten liegen schon in `agent_tasks.diff`).
3. Ein echter Lauf mit `hub-test.sh` in einem JavaScript-Projekt und ein echter Prüfer-Lauf ohne Werkzeuge (nur mit Tests geprüft).
4. Die 6 eskalierten Aufgaben in den Testprojekten aufräumen (abbrechen oder neu starten); eskalierte Punkte mit Automatik halten ihr Projekt jetzt an.

## Wie Claude hier arbeitet

Deutsch antworten, kurz erklären, keine Verständnisfragen am Ende; erst Schnittstelle, dann Code; kleinste Lösung; ein Thema pro Commit, ein Branch pro Aufgabe; Routine ohne Rückfrage. Tests immer mit leerem `/data`; Diagnosebefehle geben nie Geheimnisse aus. Arbeitsplatz Mac: Klon vom Pi im Scratchpad, Tests mit `~/wtcl.sh <branch>` (Web) und `~/rtcl.sh <branch>` (Runner) auf dem Pi (eigene Worktrees `~/hub-test-cl`, `~/hub-test-clr`).
