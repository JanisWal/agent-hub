# Agent-Hub – Übergabe an einen neuen Chat

Stand: 14.11.2026, abends (letzter Merge `docs-signin`, 390 Web-Tests und 86 Runner-Tests grün) · Zweck: Einstieg in einen neuen Chat oder auf einem anderen Rechner. Quelle der Wahrheit: `PROJEKT.md` („Auf einen Blick“, Abschnitt 3 „Claude-Anmeldung und Tokens, so gebaut“, Abschnitt 11b Dateiablage, Änderungsprotokoll in Abschnitt 12), `KONZEPT-AGENTEN.md`, `DESIGN.md` und `CLAUDE.md` (Regeln). Frühere Übergaben liegen im Ordner `archiv/`.

## In einem Satz

Ein selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B (1 GB, per WLAN), live unter `https://hub.janis-home.de`: Projekte als Kacheln, Board für Software, pro Projekt ein Manager (Chat mit dem eigenen Claude) und eine Dateiablage, später feste KI-Agenten. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was am 14.11.2026 dazugekommen ist (Einzelheiten im Änderungsprotokoll)

- **Arbeitsplatz Mac:** eigener SSH-Schlüssel `~/.ssh/id_agenthub` (Kennung `agent-hub-claude-mac`); Klon im Scratchpad, Branches per `git push` auf den Pi, dort Merge. Hilfsskripte im Home des Pi: `~/t.sh <branch>` (Web-Tests, leeres `/data`), `~/rt.sh <branch>` (Runner-Tests im frisch gebauten Test-Image), `~/prev.sh <branch>` (Vorschau). Das Terminal der Claude-App erreicht den Pi nicht (macOS „Lokales Netzwerk“); Befehle mit Passwort im Terminal von macOS.
- **Claude-Anmeldung, neu und stabil:** `claude setup-token` (ein Jahr), Token verschlüsselt (`token.enc`, Schlüssel `HUB_TOKEN_KEY` nur im Runner), Läufe bekommen nur ein Ticket, der Gateway im Egress-Proxy (Port 3130) setzt den Token ein. „Läuft bald ab · Erneuern“ 30 Tage vor Ende. **Janis und Nutzer 5 müssen einmal neu verknüpfen** (alte Verknüpfungen wurden einmalig „abgelaufen“).
- **Zweite Runde Oberfläche:** kurze Fehlertexte im Chat, „Abgelaufen“ sofort in der Schublade, Modell/Stufe als Kapsel, „Web + Code“ als runder Globus-Knopf (Kopf in einer Reihe), Eingabe wächst bis drei Zeilen, runder Senden-Knopf, Stationen im Segmentschalter-Design, Trenner lässt eine Kachel bis auf die Überschrift nachgeben, Fortschritt je Datei beim Hochladen, Bereichsname ohne „…“.
- **So wenig Neuladen wie möglich** (Designregel): `AgentHub.swap` tauscht Seitenteile, Uploads halten jedes Neuladen an (`AgentHub.hold`).
- **Vorschaubilder für jedes Bild** (im Browser, nie auf dem Server): auch TIFF, HEIC (Safari), Kamera-RAW (`static/tiffthumb.js`); RAW gehört zu Medien (7 DNG verschoben).

## Entscheidungen (alle in PROJEKT.md, DESIGN.md oder CLAUDE.md)

- Anmeldung über `setup-token` statt eigener Erneuerung wie bei Hermes (Erneuerungs-Token gelten nur einmal, vorgetäuschte Programmkennung).
- Tokens nie in einem Lauf, nie im Klartext auf der Karte; das Backup behält Ordner und Schlüssel (selbst verschlüsselt).
- Vorschaubilder nur im Browser (keine fremden Dateien auf dem Server zerlegen).

## Wie Claude hier arbeitet (Kurzfassung)

- Deutsch antworten, kurz erklären, keine Verständnisfragen am Ende; erst Schnittstelle zeigen, dann Code; kleinste Lösung; ein Thema pro Commit, ein Branch pro Aufgabe.
- Commit, Merge, Push, Deploy und Tests ohne Rückfrage, danach berichten. Fragen nur bei Berechtigungen, Sicherheit, Design und Features. `sudo`, Netz, Löschen vorher bestätigen lassen.
- Tests immer mit leerem `/data`; Diagnosebefehle geben nie Geheimnisse aus. In Skripten kein `umask 077` vor Git-Befehlen (am 14.11.2026 wurden so Code-Dateien nur für root lesbar, der Proxy startete nicht).
- Nach Doku-Änderungen `CLAUDE.md`, `PROJEKT.md`, `DESIGN.md`, `KONZEPT-AGENTEN.md` und diese Datei in den iCloud-Projektordner kopieren.

## Wo wir stehen

- **Live und getestet:** siehe „Auf einen Blick“; Gateway live geprüft (Ticket → Anthropic, unbekanntes Ticket → 403, kein direkter Weg aus dem Lauf), `setup-token` gibt auf dem Pi den Link aus.
- **Verknüpfen repariert (`signin-fix`, `signin-enter`):** Enter wird getrennt vom Code gedrückt (vorher kam der Code nie an), abgelehnte Codes scheitern sofort, Ladepunkte im Dialog, abgelaufene Tokens löscht der Runner selbst (die alten Dateien von Nutzer 5 sind weg).
- **Nicht geprüft:** ein echter Chat mit dem neuen Token (braucht Janis’ Verknüpfen), eine echte Kamera-DNG, Hell-Stil, Handy, echter Upload mit vielen Dateien.
- **Offen bei Janis:** neu verknüpfen; die alten Anmeldedateien von Nutzer 5 (Klartext, nicht mehr benutzt) löschen lassen, falls er nicht neu verknüpft; die am 13.11.2026 verlorenen Dateien aus dem Backup (`sudo`); Tunnel-Token erneuern.
- **Konzept festgelegt (14.11.2026, abends):** KI-unabhängiger Ablauf in KONZEPT-AGENTEN.md Abschnitt 9 (Adapter, Antwortformat, Rückfragen, Aufgaben, Manager-Runden, Status). Noch nicht gebaut; vorher will Janis etwas anderes erledigen. Klein und offen: Erinnerungsdateien auf englische Namen umstellen (9.10).
- **Danach:** Ordner und Unterordner mit Leiste samt Ordner-Upload (PROJEKT.md 11b, Punkt 1, aufgeschoben), KI-Zugriff über den eingehängten Ordner (Punkt 2).
