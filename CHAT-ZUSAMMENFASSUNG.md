# Agent-Hub – Übergabe an einen neuen Chat

Stand: 13.11.2026, Ende der Sitzung (letzter Merge `file-select-range`, 351 Web-Tests grün) · Zweck: Einstieg in einen neuen Chat oder auf einem anderen Rechner. Quelle der Wahrheit: `PROJEKT.md` („Auf einen Blick“, **Abschnitt 11b für die Dateiablage**, Änderungsprotokoll in Abschnitt 12), `KONZEPT-AGENTEN.md` (Agenten, Netz, Geräte, Mac, Dateizugriff), `DESIGN.md` (Gestaltung) und `CLAUDE.md` (Regeln). Frühere Übergaben liegen im Ordner `archiv/`.

## In einem Satz

Ein selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B (1 GB, per **WLAN**), live unter `https://hub.janis-home.de`: Projekte als Kacheln, Board für Software, pro Projekt ein Manager (Chat mit dem eigenen Claude) und eine **Dateiablage**, später feste KI-Agenten. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was seit der Übergabe vom 08.11.2026 dazugekommen ist (Auswahl, Einzelheiten in PROJEKT.md Abschnitt 12)

- **Verwaltung:** Rollen Owner, Admin, Nutzer, Einladung und Passwort-Reset per Mail, Seite `/admin`, Neustart und Ausschalten für den Owner, manuelles Backup, nächtliches verschlüsseltes Backup auf den USB-Stick (`deploy/backup.sh`, Stick nur für root lesbar).
- **Manager:** Regelmäßige Prüfungen mit Wochentagen, Manager-Chat mit Einstellungen pro Agent, **Gedächtnis** (`MEMORY.md` wird vor jeder Frage gelesen und nachgeführt, der Hub speichert).
- **Dateiablage** (der große Teil dieser Sitzung): fünf Reiter als Segmentschalter, Zeilen als Glas-Karten, Vorschau, Leser, Betrachter mit Pfeilen, **Upload-Motor** `upload.js` (Fortsetzen, Anfragegröße nach Tempo, Messung), mehrere Dateien mit Abbrechen, Ziehen hinein und hinaus, Markieren (Umschalt Bereich, Strg/Cmd einzeln), **drei Kreise** (Papierkorb als Schalter oder „Markierte löschen“, Vollbild, Plus), weiche Bewegungen, Einstellung „Rückfrage beim Löschen“ am Konto.

## Zwei Vorfälle, die man kennen muss

1. **Testläufe haben echte Dateien gelöscht** (13.11.2026). Ursache: Der Testbefehl hängte den echten `./data` ein und die Aufräumfunktion lief mit festem Pfad. Behoben: Der Dateiordner hängt an der Datenbank, der Testbefehl hängt ein leeres `/data` ein (**Pflicht**, steht in `CLAUDE.md`). Verloren: hochgeladene Dateien und Vorschaubilder; Rückweg wäre das nächtliche Backup auf dem Stick (braucht `sudo`, Janis entscheidet).
2. **Ein Diagnosebefehl zeigte den Tunnel-Token** (gekürzt, nicht gespeichert). Janis kann ihn im Cloudflare-Dashboard erneuern. Diagnosebefehle geben nie Geheimnisse aus (`CLAUDE.md`).

## Entscheidungen von Janis seit dem 08.11.2026 (alle in PROJEKT.md oder DESIGN.md)

- Dateiablage: jeder Dateityp, jede Größe; fünf Bereiche (Erinnerungen, Code, Medien, Dokumente, Links), automatisch nach Endung einsortiert, von Hand umsortierbar; kein Papierkorb; Hochladen in Stücken; Löschen fragt nach (abschaltbar über den roten Kreis), **mehrere Dateien fragen immer**.
- **Die KI soll alle Dateien selbst lesen** (auch Bilder und PDF, Unterordner inklusive), über einen **eingehängten Ordner** (PROJEKT.md 11b Punkt 2, KONZEPT-AGENTEN.md). Das hat nichts mit den Netzregeln zu tun.
- **Ordner und Unterordner** (Leiste in halber Höhe unter den Reitern, die sich nach Zahl und Länge der Namen aufteilt, zuletzt scrollbar; Unterordner als Zeilen mit Zurück-Pfeil; Ordner hineinziehen; Anlegen per Knopf): genaue Beschreibung in PROJEKT.md 11b und DESIGN.md.
- Markieren wie überall; der Papierkorb-Kreis wechselt seine Aufgabe (rot = nicht nachfragen, grün = Markierte löschen), kein zusätzlicher Knopf.
- Betrachter und Leser füllen das ganze Fenster, mit Pfeilen zum Weiterblättern.
- Bewegungen sollen weich sein (Federn, Apple-Richtlinien), auch Hinweise und das Vergrößern der Kachel.
- Janis hat eine 600er-Leitung; der Engpass beim Upload liegt woanders (Untersuchung in PROJEKT.md 11b).
- Superadmin (4a), modulare Modellauswahl (4b), universelle Erinnerung (4c) stehen weiter in PROJEKT.md 11a.

## Einstieg in einen neuen Chat

1. `CLAUDE.md` (Regeln), dann `PROJEKT.md` „Auf einen Blick“ und **Abschnitt 11b**, dann diese Datei.
2. Für Agenten, Netz, Geräte, Mac und den Dateizugriff der KI: `KONZEPT-AGENTEN.md`. Für Oberflächen: `DESIGN.md` (Abschnitt 10b und die Absätze zur Kachel „Dateien“).
3. Code: Der iCloud-Ordner enthält nur die Doku; der aktuelle Code liegt im Klon auf dem Pi (`/opt/agent-hub/workspaces/agent-hub`, Branch `main`). Auf dem PC gibt es kein Git.
4. **Als Erstes fragen:** Hat Janis die große Datei hochgeladen? Dann `window.__uploadLog` und das Protokoll des Hubs lesen (PROJEKT.md 11b, „Upload“). Dann die Reihenfolge der offenen Wünsche klären (Ordner, KI-Zugriff, Verschieben der Markierten; sein abgebrochener Satz dazu ist offen).

## Wie Claude hier arbeitet (Kurzfassung)

- Deutsch antworten, kurz erklären, **keine Verständnisfragen am Ende**; erst Schnittstelle zeigen, dann Code; kleinste Lösung; ein Thema pro Commit, ein Branch pro Aufgabe.
- Commit, Merge, Push, Deploy und Tests ohne Rückfrage, danach berichten. Fragen nur bei Berechtigungen, Sicherheit, Design und Features. `sudo`, Netz, Löschen vorher bestätigen lassen.
- **ssh vom PC:** Skript schreiben, `scp` nach `/tmp`, `bash /tmp/skript.sh`; nie verschachtelte Anführungszeichen. Änderungen an Dateien als kleines Python-Skript mit geprüftem Ersetzen.
- **Tests:** mit leerem `-v "$(mktemp -d):/data"`; HTTP-Test `web/tests/integration_files.py` in einem Wegwerf-Container ohne Port; Upload-Motor mit `web/tests/upload_engine/`.
- **Vorschau** der Oberfläche: `web/tests/preview_files.py` im Container rendern, per `scp -r` auf den PC, `py -m http.server 8765 --bind 127.0.0.1`, im eingebauten Browser ansehen (keine Ports am Pi). Einzelheiten in PROJEKT.md 11b, „Werkzeuge“.
- Nach Doku-Änderungen `CLAUDE.md`, `PROJEKT.md`, `DESIGN.md`, `KONZEPT-AGENTEN.md` und diese Datei in den iCloud-Projektordner kopieren.

## Wo wir stehen

- **Live und getestet:** siehe „Auf einen Blick“; 351 Web-Tests grün; 8 Browser-Szenarien für den Upload-Motor; HTTP-Test der Dateiablage grün.
- **Nicht geprüft:** das Hochladen großer Dateien durch den echten Tunnel (der eigentliche Test), das Erzeugen der Vorschaubilder und das Hinausziehen auf den Desktop an Janis’ Rechner, Berührung am Handy, ein echter Lauf mit dem Dateizugriff der KI (noch nicht gebaut).
- **Offen, nicht gebaut:** Ordner und Unterordner, KI-Zugriff über den eingehängten Ordner, Verschieben Markierter, Geräteliste, Schleife der Agentenläufe, Statusmeldung und Kachel-Infos, Verbrauchsanzeige, Mac-Programm, Superadmin, modulare Modellauswahl.
