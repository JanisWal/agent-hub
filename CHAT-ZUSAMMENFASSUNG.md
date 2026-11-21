# Agent-Hub – Übergabe an einen neuen Chat

Stand: 21.11.2026 (ChatGPT, API-Schlüssel neben dem Abo, weitere KIs; davor 20.11.2026: Durchsicht des ganzen Systems und Umbau der KI-Pakete) · Zweck: Einstieg in einen neuen Chat. Quelle der Wahrheit: `PROJEKT.md` („Auf einen Blick“, Fahrplan in 11a), `PROTOKOLL.md` (alle Änderungen, neueste zuerst), `KONZEPT-AGENTEN.md` (9.2a Werkzeuge je KI, 9.3a Pakete je Rolle), `DESIGN.md`, `CLAUDE.md`. Die vorige Übergabe (bis 19.11.2026) liegt in `archiv/CHAT-ZUSAMMENFASSUNG-2026-11-19.md`.

## In einem Satz

Selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B, live unter `https://hub.janis-home.de`: Projekte, Board für Software, je Projekt ein Manager-Chat, Agentenkette (Programmierer, Tests, Prüfer, Freigabe, Doku), Dateiablage, Geräte über einen Vermittler. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was am 20.11.2026 passiert ist

- **Durchsicht** von Doku und Code mit echten Zahlen aus der Datenbank: Programmierer im Schnitt 108 000 Eingabe-Tokens je Lauf, Tester 109 000, Prüfer 62 000; 6 von 19 Aufgaben eskaliert, keine wegen eines schwachen Modells (leerer Arbeitsordner, weil der Code in der Ablage lag; kein Node; Folgepunkte nach einer Eskalation).
- **Gebaut und live** (Einzelheiten in PROTOKOLL.md, oberster Eintrag): Zugangsdaten nur bei klarer Ablehnung löschen; nach Lesen im Web warten neue Board-Punkte auf das Ja; Gateway nur mit nötigen Pfaden; Tester und Prüfer ohne Internet; Diff für Tester, Prüfer und Freigabe; `hub-test.sh` führt der Hub selbst aus; Node im Agenten-Image; Eskalation hält die Folgepunkte an; **Pakete je Rolle** (`web/app/prompts.py`); **Werkzeuge je KI im Katalog**; Erinnerung per Abschnitt; englische Namen der Erinnerungsdateien; Ansichten `/files` zwischengespeichert; jeder Runner-Auftrag meldet sein Ende; Altlasten entfernt; CLAUDE.md nach Themen geordnet; Änderungsprotokoll in PROTOKOLL.md.
- **Entschieden von Janis:** Automatik aus dem Chat bleibt (ohne Bestätigung); Schlüssel werden bei Ablehnung gelöscht, nie wenn der Server sie nicht lesen kann; jede KI soll anbindbar sein, mit eigenem Werkzeug oder Ersatz vom Hub (Kacheln Claude, Mistral, ChatGPT, „Eigene KI“).
- **Bewusst nicht gemacht:** WAL-Modus für SQLite (das Backup als root ließe Dateien zurück, die der Web-Dienst nicht öffnen kann; stattdessen 15 s Wartezeit). PROJEKT.md weiter verdichten (nur mechanisch geteilt, kein Inhalt gelöscht).

## Was am 21.11.2026 dazukam (Auftrag von Janis, alles in einem Deploy)

- **ChatGPT über Codex** (`chatgpt`): Anmeldung mit dem ChatGPT-Konto per Gerätecode, ohne API; Tokens erneuert nur der Runner; Läufe mit Ticket-Hülle über Gateway 3133. **Modell-Listen** täglich von jeder KI selbst, je Nutzer (auch Claude: keine Modelle mehr fest im Code). **Werkzeug-Prüfung:** Ersatz vom Hub nur, wenn das Programm ein Werkzeug dreimal in Folge lesbar nicht nennt; Fehler im Lauf zählen nie (Schutz davor, dass ein Fehler von uns dauerhaft den Ersatz einschaltet).
- **API-Schlüssel neben dem Abo** (`api-option`): zweigeteilter Verknüpfen-Dialog bei Claude und ChatGPT (links Abo, rechts Schlüssel mit Modus „Erst wenn das Abo aufgebraucht ist“ / „Immer statt Abo“ / „Aus“, Bereich, Tagesgrenze, Hinweis „Kann Zusatzkosten verursachen“ ohne Preis). Wechsel nur Abo → Schlüssel derselben KI, nie zurück, dann die nächste KI.
- **Weitere KIs** (`more-ais`): bis zu acht je Nutzer mit eigenem Namen, offene Kachel „Weitere KI“ bleibt stehen, Platzhalter Gemini und GitHub Copilot, Schalter „KI im Heimnetz“ für den Owner in den Systemeinstellungen. KIs in fremden Netzen später über VPN: Plan in PROJEKT.md 4 („KIs in fremden Netzen“).
- Beim Testen gefunden und behoben: Gateway 3133 nahm auch ein bloßes Abo-Ticket an; jetzt gilt die Hülle nur für das Abo, das bloße Ticket nur für einen Schlüssel.
- **Noch nie echt gelaufen:** ChatGPT-Anmeldung und -Lauf (braucht Janis' Anmeldung), Go-Abo, Anthropic `/v1/models` mit dem Abo-Token, ein API-Schlüssel gegen Anthropic oder OpenAI, eine weitere KI gegen eine echte API.

**Erkenntnisse aus diesem Chat (für spätere Entscheidungen):**
- Abo und API liefern dieselben Modelle und dieselbe Qualität bei gleichem Tokenverbrauch. Unterschiede: Kosten nach Verbrauch, keine Wochengrenze, sauberere Nutzungsbedingungen für Automatisierung, Schlüssel ohne Ablauf, alle Modelle, Ausgabengrenze beim Anbieter.
- Das Chat-Format von OpenAI ist der gemeinsame Standard fast aller Anbieter (auch Gemini und Anthropic per Kompatibilitätsadresse, lokal Ollama, LM Studio, vLLM); Unterschiede bei Werkzeugaufrufen, Bildern, Denkstufe. Ein eigener Adapter lohnt nur bei einem Programm mit eigenen Werkzeugen und Abo-Anmeldung (Gemini CLI, GitHub Copilot CLI).
- Codex ist das Programm, die Modelle sind die GPT-Familie; das normale Chat-Backend von ChatGPT ist keine Schnittstelle für fremde Programme. Ob das Go-Abo Codex enthält, ist widersprüchlich dokumentiert; ohne Freigabe lehnt der Server ab (Meldung „Abo ohne Codex“). Sich als die Desktop-App auszugeben scheidet aus (vorgetäuschte Programmkennung). Codex verbindet sich standardmäßig per WebSocket; mit eigenem Anbieter-Eintrag (`supports_websockets = false`) nimmt es einfache Anfragen, nimmt die Ticket-Hülle an und erneuert nicht selbst (mit Schein-Server erprobt). `--with-access-token` braucht ein Agenten-JWT, für Privatkonten unbrauchbar.
- Eigene Werkzeuge der KIs sind fast immer besser und sparsamer (darauf trainiert, im zwischengespeicherten Teil des Pakets); der Ersatz des Hubs kostet je Schritt 1000 bis 2000 Tokens mehr, die Textform am meisten.
- Heimnetz: Die KI eines Kollegen bei ihm zu Hause ist vom Server aus nicht erreichbar; öffentlich erreichbar (eigener Tunnel, https) braucht sie keine Freigabe. Das Heimnetz des Servers gibt nur der Owner frei, und nur für seine eigenen KIs.

## Was als Nächstes ansteht

1. **Echte Probe mit Janis:** ChatGPT anmelden (Gerätecode), eine Chat-Frage und ein Agentenlauf, Modell-Liste ansehen; optional ein API-Schlüssel und eine weitere KI (z. B. ein lokales Ollama mit „KI im Heimnetz“).
2. Das Aussehen des zweigeteilten Dialogs und der Schublade in Hell und Dunkel am Bildschirm prüfen.
3. Weitere KI: Modell aus `GET /models` als Auswahl statt Eintippen; Bilder; Werkzeuge je KI auf `/admin` umschaltbar.
4. **Diff in der Oberfläche** bei der Freigabe (Daten liegen schon in `agent_tasks.diff`).
5. Ein echter Lauf mit `hub-test.sh` in einem JavaScript-Projekt und ein echter Prüfer-Lauf ohne Werkzeuge.
6. Die 6 eskalierten Aufgaben in den Testprojekten aufräumen.
7. Später: Adapter für Gemini und GitHub Copilot; KIs und Geräte in fremden Netzen über Tailscale (PROJEKT.md 4).

## Wie Claude hier arbeitet

Deutsch antworten, kurz erklären, keine Verständnisfragen am Ende; erst Schnittstelle, dann Code; kleinste Lösung; ein Thema pro Commit, ein Branch pro Aufgabe; Routine ohne Rückfrage. Tests immer mit leerem `/data`; Diagnosebefehle geben nie Geheimnisse aus. Arbeitsplatz Mac: Klon vom Pi im Scratchpad, Tests mit `~/wtcl.sh <branch>` (Web) und `~/rtcl.sh <branch>` (Runner) auf dem Pi (eigene Worktrees `~/hub-test-cl`, `~/hub-test-clr`).
