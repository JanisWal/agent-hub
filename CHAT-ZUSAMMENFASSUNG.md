# Agent-Hub – Übergabe an einen neuen Chat

Stand: 08.11.2026, Zwischenstand · Zweck: Einstieg in einen neuen Chat oder auf einem anderen Rechner. Quelle der Wahrheit bleiben `PROJEKT.md` (Entscheidungen, Aufbau, Betrieb, „Auf einen Blick“, Änderungsprotokoll in Abschnitt 12), `KONZEPT-AGENTEN.md` (Agenten, Netz, Geräte, Mac), `DESIGN.md` (Gestaltung, Abschnitt 10b Projektseite und Manager) und `CLAUDE.md` (Regeln). Frühere Übergaben liegen im Ordner `archiv/`.

## In einem Satz

Ein selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B (1 GB), live unter `https://hub.janis-home.de`: Projekte als Kacheln, Board für Software, ein Manager pro Projekt (Chat mit dem eigenen Claude), später feste KI-Agenten pro Nutzer. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was seit der letzten Übergabe (07.11.2026, Mittag) dazugekommen ist

1. **Claude verknüpfen** pro Nutzer (Schublade, Link und Code), Trennen räumt den Ordner auf; Runner-Dienst, ein Container je Lauf, Image `agent-hub-agent`.
2. **Netz:** Agenten-Netz intern, einziger Ausgang der Filter-Proxy `egress` (3129 nur Anthropic, 3128 öffentliche Seiten, derzeit ungenutzt). Heimnetz gesperrt.
3. **Projektseite neu** nach Janis’ Skizze: Titel am goldenen Schnitt mit **Stift** (Drop-down für Name und Beschreibung), runde Knöpfe für Archiv und Papierkorb am Zahnrad, Board als Linien mit grünen/roten Knöpfen, Stationen links als zwei Ansichten **Board** und **Manager** (`#board`, `#manager`), eigene Tooltips und Scrollleisten, geprüft von 360 bis 1920 px.
4. **Manager-Ansicht** in drei Spalten: Status, Geräte | Regelmäßige Prüfungen, Dateien | **Manager-Chat**, „Wartet auf dich“. Geräte, Prüfungen und Dateien sind angekündigt, Status und „Wartet auf dich“ noch leer.
5. **Manager-Chat:** ersetzt das alte Einzelfragen-Fenster. Kennt Name, Beschreibung, offene Board-Punkte und die letzten 6 Fragen des Projekts; Web (Suche bei Anthropic) und Code (ohne Internet) immer an, nutzt sie nur bei Bedarf. **Modell** und **Selbstständigkeit** als Drop-downs im eigenen Glas-Stil, Einstellungen des Managers pro Nutzer. Echter Lauf auf dem Pi bestanden.
6. **Säuberung** (`cleanup-manager`): Rolle Dokumentator aus dem Code, alte Chat-Modi entfernt, ungenutzter Text entfernt.

## Entscheidungen von Janis (neu, alle in PROJEKT.md oder KONZEPT-AGENTEN.md)

- Heimnetz bleibt gesperrt; Geräte über eine **Geräteliste im Manager** (Hostname, Auflösung durch den Hub, Freigabe, SSH-Schlüssel verschlüsselt auf dem Pi, nie für die KI). Fremde Netze per VPN sternförmig mit Isolation; Technik **Tailscale**, weil auf der Fritzbox **kein Port** geöffnet wird.
- **Mac:** Knopf in der Website startet die lokale Entwicklung ohne zweite Anmeldung (unsichtbares Einmal-Ticket); Ergebnis kommt als Git-Bundle über den Hub zurück ins Projekt.
- **Alle Agenten dürfen ins Internet** in den besprochenen Grenzen (nur über `egress`, nie Heimnetz).
- **Manager:** berät auch zu Hardware, pflegt Doku und Projektstand (legt sie über den Hub in Git ab), verteilt Aufgaben über den Hub, schreibt Statusmeldungen mit Ampel, liefert die Infos für die Kachel; Rolle **Dokumentator entfällt**. Hardware-To-Dos, Checklisten und regelmäßige Prüfungen gehören zum Manager, **das Board bleibt Software**. Der Manager-Tab ist Koexistenz: Janis managt Geräte, Schlüssel und Einstellungen, der Manager seine Aufgaben.
- **Kachel im Dashboard (geplant):** Titel oben, News des Managers, Zahl der Bugs/kleinen/Major-Updates, Ampel; Vorschläge: Verbrauch, „wartet auf dich“, letzte Aktivität.
- **Verbrauch:** aus der Ausgabe von Claude Code; der Rest des Kontingents nur geschätzt.
- Tabs Programmierer, Tester, Prüfer bleiben, auch wenn ihr Inhalt noch offen ist.

## Wie Claude hier arbeitet (Kurzfassung, Details in PROJEKT.md Abschnitt 9)

- Deutsch antworten, kurz erklären, **keine Verständnisfragen am Ende**; erst Schnittstelle zeigen, dann Code; kleinste Lösung; ein Thema pro Commit.
- Commit, Merge, Push, Deploy und Tests ohne Rückfrage, danach berichten. Fragen nur bei Berechtigungen, Sicherheit, Design und Features.
- Am Windows-PC gibt es kein Git: Dateien im Arbeitsordner bearbeiten, per `scp` in den Klon auf dem Pi (`/opt/agent-hub/workspaces/agent-hub`), dort Branch, Tests im Container (Ergebnis über den Exit-Code prüfen), Backup `data/hub.db` nach `/opt/agent-hub/backups/`, Merge `--no-ff`, Push, `docker compose up -d --build web` (bei Änderungen am Runner auch `runner`), Prüfung von `/health` und `/login`.
- Vorschau ohne offenen Port: Seite im Container als Datei rendern (Skript mit Testdaten), lokal über `127.0.0.1` im eingebauten Browser ansehen.
- Zugang zum Pi: `ssh -i ~/.ssh/id_agenthub admin@home.local`. Passwörter und Schlüssel nie ausgeben.
- Nach Doku-Änderungen `CLAUDE.md`, `PROJEKT.md`, `DESIGN.md`, `KONZEPT-AGENTEN.md` und diese Datei in den iCloud-Projektordner kopieren.

## Wo wir stehen

- **Live und getestet:** siehe „Auf einen Blick“ in PROJEKT.md; Web-Tests und Runner-Tests grün (Zahlen im Änderungsprotokoll).
- **Nicht geprüft:** Manager-Chat mit Sonnet und vollem Projektkontext (Janis testet), Verbrauch pro Frage mit Kontext, Bedienung am Handy mit Finger, Mails in echten Mailprogrammen.
- **Offen besprochen, nicht gebaut:** USB-Stick als externe Platte (Janis will das besprechen, nichts vorher anschließen), Dateiablage, Geräteliste mit Tresor, Schleife der Agentenläufe, Statusmeldung und Kachel-Infos, Verbrauchsanzeige, Mac-Programm.

## Nächste Aufgaben (Vorschlag)

Siehe „Nächste Schritte“ in PROJEKT.md, „Auf einen Blick“. Aufräumen auf dem Pi (altes Runner-Image und -Volume, alte Codekopie, gemergte Branches) nur nach Janis’ Ja.
