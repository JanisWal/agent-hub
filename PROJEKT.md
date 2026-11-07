# Agent-Hub – Projektsheet

Stand: 07.11.2026 · Autor: Janis (mit Claude) · Zweck: Philosophie, Ziel, Entscheidungen und Reihenfolge, damit jeder Claude-Chat im Projekt denselben Stand hat.

## 1. Ziel und Philosophie

- Ein selbst gehostetes Verwaltungstool für Software-Projekte auf einem Raspberry Pi: Projekte als Kacheln, Kanban-Board, feste KI-Agenten-Rollen, Dateiablage.
- Hobbyprojekt, aber in Bausteinen und offen gedacht: Freunde können das Grundgerüst auf einem eigenen Pi installieren.
- Janis baut es per Vibe-Coding mit Claude. Die Basics (Website, Datenmodell, Sicherheit, Rollenablauf) will er selbst verstehen und lernen.
- Kein Verkauf geplant. Keine Mehrkosten über das Pro-Abo hinaus.
- Regel für Claude: kleinste Lösung, die die Anforderung erfüllt; erst die Schnittstelle zeigen, dann die Implementierung; ein Modul pro Auftrag; Entscheidungen kurz begründen.
- Allgemeines Ziel: effizient arbeiten. Das Pro-Kontingent ist begrenzt, also verbraucht jede Aufgabe nur so viel wie nötig: kleine, klar umrissene Aufträge, das passende Modell je Aufgabe, nur der nötige Kontext (kurze CLAUDE.md, nur die relevanten Dateien), Limits für Durchläufe und Zeit und ein sichtbarer Verbrauch pro Lauf, um Verschwendung zu erkennen.

## 2. Getroffene Entscheidungen

- Claude Pro-Abo, keine API-Kosten. Sind die Limits aufgebraucht, wird später weitergearbeitet.
- Zugriff von überall über eigene Domain, Login mit E-Mail und Passwort. Passwort zurücksetzen per E-Mail über einen fertigen Baustein.
- Eine Installation pro Pi, mit Benutzerkonten. Andere nutzen entweder Janis’ Pi als Server mit eigener Claude-Anbindung oder installieren das Paket auf einem eigenen Pi. Janis’ Abo wird nie geteilt.
- Zuerst nur Claude. Andere KIs (z. B. ChatGPT) später als separate Anmeldung hinter einer gemeinsamen Schnittstelle.
- Programmiersprache Python; ein Wechsel nur, wenn JavaScript große Vorteile bringt.
- Eigene Struktur konsequent umsetzen, vorhandene Open-Source-Bausteine nutzen, wo sie passen.
- Tägliches Backup auf eine externe SSD mit restic (verschlüsselt, nur Änderungen), zusätzlich Git-Spiegel auf GitHub. Struktur, Doku und offene Punkte haben höchste Priorität. Zurückrollen von Versionen gehört von Anfang an dazu.
- Zunächst ein bis zwei weitere Nutzer; bei Problemen wird reguliert.
- GitHub: privater Spiegel der Projekte, später auch zum Teilen mit Freunden.
- Modellwahl: Standard ist Sonnet 5.5 (gut genug für den Alltag, schont das Pro-Limit). Opus 5.5 nur gezielt für schwierige Aufgaben (Architektur, hartnäckige Fehlersuche, Prüfer), Haiku 5.5 für einfache, häufige Aufgaben (Dokumentator, Zusammenfassungen, Commit-Texte). Umschalten in Claude Code mit /model.

## 3. Offener Kernpunkt: Anbindung des Abos

Soweit bekannt, lässt sich ein Abo nicht über Benutzername und Passwort an eine fremde Website anbinden, und die Restlimits sind nicht auslesbar. Der naheliegende Weg ohne API-Kosten:

- Auf dem Pi läuft Claude Code (Kommandozeile) eigenständig und unabhängig vom Mac, angemeldet mit dem eigenen Konto. Die Website startet es für die Agenten-Aufgaben und liest dessen Ausgabe.
- Jeder Nutzer meldet sein eigenes Claude Code an. Daten und Limits bleiben getrennt.
- Die Token-Anzeige auf der Startseite ist dann kein Abo-Restwert, sondern eine eigene Zählung: Der Verbrauch pro Lauf (Tokens, Dauer) wird aus der Ausgabe von Claude Code gelesen und pro Projekt summiert (Format in Phase 2 prüfen). Der Abo-Rest bleibt in den Claude-Einstellungen unter Nutzung; ob Claude Code ihn über einen Befehl wie /usage anzeigt, wird getestet.
- Vor dem Bau prüfen: Nutzungsbedingungen für den Einsatz in eigenen Tools, Verfügbarkeit im Pro-Plan, Betrieb auf dem Pi (Pi 4/5, 64-Bit-OS, Node.js-Anforderung).

Sonderregel für Swift (Entwurf): Swift-Code braucht Xcode und den Simulator und lässt sich nur am Mac bauen und testen. Der Pi bleibt Zentrale für Board, Rollen und Git. Für Swift-Aufgaben arbeitet Claude Code auf dem Mac im selben Git-Repo, der Pi übernimmt das Ergebnis per Git. Tests mit echtem iPhone und Pi meldet der Tester als „nicht prüfbar“. Die genaue Aufteilung wird vor Phase 2 festgelegt.

### Installation und Ersteinrichtung (Ziel)

- Wer das Paket (z. B. von GitHub) auf einen frischen Pi holt, soll möglichst nichts von Hand einrichten: ein Befehl lädt das Repo, ein Installationsskript installiert Docker, legt `/opt/agent-hub/` an und startet alles.
- Danach läuft die Einrichtung im Browser als Assistent: 1. Admin-Konto anlegen, 2. Verbindung nach außen (Cloudflare-Tunnel-Token einfügen), 3. Claude verbinden, 4. E-Mail-Versand einrichten.
- Nicht automatisierbar bleiben die Konten und Zugänge: Domain, Cloudflare, Claude, GitHub.
- Kein Anmelden per SSH auf dem Pi nötig. Alles läuft über die Webmaske per HTTPS.

### Claude-Anmeldung über die Weboberfläche (Ziel)

- Benutzername und Passwort von Claude gehen nie an den Pi. Die Anmeldung läuft über OAuth: Der Pi zeigt einen Anmelde-Link, der Nutzer bestätigt im Browser bei Claude und gibt den angezeigten Code oder Token in die Webmaske ein.
- Ablauf: Knopf „Mit Claude verbinden“, der Pi-Runner startet den Anmeldevorgang, die Maske zeigt den Link, der Nutzer bestätigt, Code oder Token geht zurück in die Maske, der Pi speichert ihn verschlüsselt pro Nutzer.
- Fallback: Token am Mac mit `claude setup-token` erzeugen und in die Maske einfügen. Auch dann ist kein SSH auf den Pi nötig.
- Risiko: Nach Fehlerberichten ist die Anmeldung ohne Bildschirm auf ARM64-Geräten wie dem Pi teils fehlerhaft, und Token laufen eventuell ohne automatische Erneuerung ab. Darum früh testen und in der Oberfläche den Status „Verbindung abgelaufen“ mit Knopf zum Erneuern anzeigen.
- Sicherheit: nur über HTTPS, Token verschlüsselt, nie in Logs oder im Git.

### Tresor für Zugangsdaten (Ziel)

- Janis lädt Zugangsdaten (SSH-Schlüssel, Passwörter, Tokens) über die Weboberfläche in einen Tresor. Agenten können sie nie lesen, nur nutzen lassen.
- Prinzip Vermittler: Der Agent bittet den Vermittler um eine Aktion (z. B. „auf dem Gerät roadster `git pull` ausführen“). Der Vermittler holt das Geheimnis, führt die Aktion selbst aus und gibt nur das gefilterte Ergebnis zurück. Das Geheimnis verlässt den Vermittler nie.
- Der Vermittler läuft als eigener Container. Der Agenten-Container hat weder Zugriff auf den Tresor-Ordner noch auf die Schlüssel (getrennte Volumes und Netze).
- Pro Zugang: Name, Typ, erlaubte Aktionen (Allowlist) und ob eine Freigabe durch Janis nötig ist. Beispiel: Zugang „roadster“ erlaubt nur `git pull` und den Neustart des Dienstes.
- Auf der Gegenseite ein eigener Benutzer mit Schlüssel-Login und eingeschränkten Rechten, nie Root. Schlüssel sind besser als Passwörter.
- Ausgaben werden gefiltert (Geheimnisse geschwärzt), jede Nutzung steht im Aktivitätsprotokoll.
- Verschlüsselung mit einer bewährten Bibliothek, keine eigene Kryptografie. Hauptschlüssel nicht neben den Daten, Entsperren nach dem Start per Passwort in der Weboberfläche. Später optional Vaultwarden als fertige Lösung.
- Grenze: Läuft eine Aktion in einer freien Shell mit dem Geheimnis, könnte ein Agent es über Umwege auslesen. Darum nur freigegebene Aktionen, keine freie Shell.

## 4. Architektur (Entwurf)

- Hardware: Raspberry Pi 4 mit micro SD (später externe USB SSD). Betriebssystem: Raspberry Pi OS Lite 64-Bit (Debian für den Pi, mit passenden Treibern).
- Zugriff: Cloudflare Tunnel statt offener Router-Ports, HTTPS inklusive. Tailscale bleibt nur Alternative für privaten Zugriff, weil es auf jedem Gerät eine App braucht.
- Web: kleines Backend mit SQLite als Datenbank, schlichtes Frontend. Konkreten Stack vor dem Bau festlegen.
- Agenten laufen in einem Container, jede Aufgabe in einem eigenen Git-Branch.
- Paketierung: Docker Compose, damit Freunde es mit wenigen Befehlen installieren.

### Speicher: SD jetzt, SSD später

- Ziel: das ganze Betriebssystem plus Daten auf einer USB-SSD, nicht nur die Daten. Datenbank, Docker und Git schreiben viel, SD-Karten verschleißen dabei schneller und fallen oft ohne Vorwarnung aus.
- Zum Start reicht die SD-Karte (mindestens 32 GB, Markenkarte), solange keine wichtigen Daten darauf liegen. Das tägliche Backup auf die externe SSD gilt ab Tag eins.
- Der Umzug ist unkompliziert, wenn alles unter `/opt/agent-hub/` liegt: Raspberry Pi OS per Raspberry Pi Imager frisch auf die SSD schreiben, Docker installieren, den Ordner zurückkopieren, `docker compose up -d`. Die SD-Karte bleibt unverändert als Rückfallebene.
- Der Pi 4B muss dafür von USB booten können. Die Bootreihenfolge wird in `raspi-config` gesetzt, bei älterer Firmware zuerst aktualisieren.
- Größe: 120 GB reichen, 240 GB geben Luft für Dateiablage und Repos. Die Backup-SSD mindestens gleich groß, Markenmodell mit USB-3-Gehäuse.

### Domain und Kosten

- Eine Domain kostet jährlich, nicht monatlich. Eine .com liegt 2026 laut Vergleichsseiten bei etwa 10–11 USD pro Jahr (Cloudflare, Porkbun, Spaceship). Entscheidend ist der Verlängerungspreis, nicht das Lockangebot im ersten Jahr.
- Geplante Domain: janis-home.de. Cloudflare Registrar bietet .de soweit bekannt (noch) nicht an, vor dem Kauf auf der TLD-Liste prüfen. Dann: Domain bei einem Registrar kaufen, der .de anbietet, und nur die Nameserver auf Cloudflare stellen (DNS und Tunnel). Das Dashboard läuft unter einer Subdomain wie hub.janis-home.de, damit die Hauptdomain für andere Dienste frei bleibt.
- Cloudflare Tunnel und Tailscale sind für den privaten Gebrauch soweit bekannt kostenlos. Konditionen vor dem Start prüfen.
- Laufende Kosten: nur die Domain. Dazu einmalig eine SSD.

### Container-Aufbau auf dem Pi

- Direkt auf dem Pi (Host): Raspberry Pi OS Lite, Docker Engine mit Docker Compose (aus der offiziellen Docker-Paketquelle), Git, SSH. Sonst nichts.
- In Containern, gestartet über eine Datei `compose.yml`: `web` (Backend und Oberfläche, SQLite-Datei im Datenordner), `tunnel` (cloudflared), `runner-pi` (Claude Code und Git, arbeitet nur im Projektordner), optional `backup` (restic).
- Ordner auf dem Pi: `/opt/agent-hub/` mit `compose.yml`, `.env` (Geheimnisse, nie im Git), `data/` (SQLite, Dateiablage), `workspaces/` (ein Git-Repo je Projekt), `backups/`.
- Der Claude-Login des Runners liegt in einem eigenen Container-Volume und nie im Git.

### Mac-Integration: lokaler Runner

- Ein Browser darf keine Programme auf dem Mac starten, und ein offener Mac-Port wäre ein Risiko. Darum läuft auf dem Mac ein kleines Programm, der Runner. Er baut selbst eine Verbindung zum Pi-Server auf (nur ausgehend) und wird einmalig per Code in den Einstellungen gekoppelt.
- Bei passenden Aufgaben (z. B. Swift) zeigt die Website den Knopf „Lokale Ressourcen verwenden“, sobald ein Mac-Runner online ist. Ist der Mac aus, steht dort „Mac nicht verbunden“ und die Aufgabe wartet.
- Ablauf: Runner holt das Repo per Git, startet Claude Code auf dem Mac (Xcode, Simulator), schickt den Branch zurück und meldet Status und Ergebnis an die Website.
- Der Pi-Runner und der Mac-Runner haben dieselbe Schnittstelle. Jede Aufgabe trägt „braucht: Mac“ oder „egal“. Weitere Rechner lassen sich später ergänzen.
- Verworfen: Fernsteuerung der Claude-Desktop-App (kein verlässlicher, dokumentierter Weg bekannt) und offene Ports am Mac.

### Git in Kurzform

- Git ist die Versionsverwaltung. Es läuft lokal, speichert jede Änderung als Commit und erlaubt Branches und Zurückrollen. Kein Internet und kein Konto nötig.
- GitHub ist eine optionale Website, die Git-Repositories hostet. Pro Repository wählst du privat (nur du) oder öffentlich (alle sehen es). Es ist eine Zusatzkopie, kein Muss.
- Dein Aufbau: Das Haupt-Repo je Projekt liegt auf dem Pi. Pi-Runner und Mac-Runner holen und liefern per Git. Optional ein Spiegel in einem privaten GitHub-Repo als externes Backup.
- Board, Rollen und Freigabe macht dein Tool, Git speichert nur den Code. GitHub hat eigene Boards, die wir nicht brauchen.
- Begriffe: Commit = gespeicherter Stand mit Beschreibung. Branch = Arbeitslinie für eine Aufgabe. `main` = Produktivversion. Merge = Branch übernehmen. Tag = benannte Version (z. B. v0.3) zum Zurückrollen.
- Beispiel einer Aufgabe: `git switch -c fix-login`, Änderungen, `git commit -m "Fix login"`, nach Freigabe `git switch main` und `git merge fix-login`. Zurückrollen: `git revert <Commit>`.

### Bausteine aus Open Source (Recherche)

- Vibe Kanban (Apache-2.0): Kanban-Board, das Coding-Agenten wie Claude Code startet. Jede Aufgabe läuft in einem eigenen Git-Worktree, der Workflow-Status liegt in SQLite, der Code in Git. Es ist ein gutes Vorbild für unsere Architektur. Es startet Agenten standardmäßig ohne Rückfragen, ein Rollenkreislauf mit Tester, Prüfer und deiner Freigabe ist nach der Beschreibung nicht erkennbar.
- Vikunja (AGPL-3, Go): Aufgabenverwaltung mit Kanban, SQLite-Option und sehr kleinem Ressourcenbedarf, mit REST-API. Passt als fertiges Board, aber die Logik Akzeptieren/Ablehnen, Papierkorb und Agentenfluss müssten wir ohnehin selbst bauen.
- Planka: reines Kanban, braucht PostgreSQL. Seit August 2026 liegt SSO nur noch in der Bezahlversion, daher nicht empfohlen.
- Vorschlag: Board und Rollenablauf selbst bauen, weil sie klein und sehr speziell sind. Muster von Vibe Kanban übernehmen (Worktree je Aufgabe, eine einheitliche Schnittstelle je Agent, Workflow in SQLite). Für Login, Passwort-Reset und Mailversand fertige Python-Bibliotheken nutzen.

## 5. Funktionen

### Startseite

- Projekte als große Kacheln mit klarem Design.
- News pro Projekt: aktueller Stand, Probleme.
- Einstellungen: Konto, Claude-Anbindung, Nutzungsanzeige.

### Benutzerverwaltung (nur Admin)

- Drei Rollen: Owner (genau einer, Janis), Admin, Nutzer. Der Owner hat alle Admin-Rechte.
- Keine Selbstregistrierung: Neue Konten legen nur Owner und Admins an.
- In den Einstellungen: „Neuen Benutzer hinzufügen“ mit E-Mail-Adresse und vergebenem Passwort.
- Liste der Benutzer: Passwörter zurücksetzen und Konten löschen (Owner und Admins).
- Nur der Owner kann Admin-Rechte per Schalter in der Benutzerliste vergeben oder entziehen. Das Owner-Konto kann niemand löschen oder herabstufen.
- Das Owner-Konto entsteht bei der Installation (bisher per `python -m app.create_admin` auf dem Pi, wird zum Owner umgebaut).

### Projektansicht

- Links die Stationen; die erste ist das Kanban-Board.
- Weitere Stationen: Agenten, Dateiablage, Dokumentation.

### Kanban-Board

- Auf dem Board nur drei Spalten: Bugs, Kleine Updates, Major Updates.
- Händisch angelegte Punkte gelten als zugestimmt und stehen oben.
- Claude-Vorschläge (Kleine/Major Updates) stehen unten mit Akzeptieren und Ablehnen. Abgelehnte wandern in den Papierkorb.
- Der Papierkorb ist standardmäßig ausgeblendet und wird per Knopf geöffnet. Dort liegen die verworfenen Punkte; man kann sie wiederherstellen, den Papierkorb leeren oder per X pro Stichpunkt endgültig löschen.
- Agenten dürfen Bugs eintragen. Ein Punkt gilt erst nach Freigabe durch Janis als Teil der Produktivversion.

### Agenten (feste Rollen, pro Nutzer ein- und ausblendbar)

- Chef (Manager): sortiert und priorisiert das Board, fasst den Projektstatus für die Kachel zusammen, stößt die anderen an. Schreibt selbst keinen Code. Ist der Mac nicht erreichbar, schätzt er, wie nötig ein Test ist: Unwichtiges wird übersprungen, sonst wartet die Aufgabe. Die Strenge ist in seinem Menü in drei Stufen einstellbar: locker, normal, streng.
- Programmierer: arbeitet Punkte ab in der Reihenfolge Bugs, Kleine Updates, Major Updates.
- Tester: prüft das Ergebnis. Bei Hardware-Themen erzeugt er eine Checkliste als Aufgabe für Janis. Kann er etwas nicht prüfen (z. B. Hardware), meldet er „nicht prüfbar“.
- Prüfer: kontrolliert die Einhaltung der Code-Richtlinien.
- Dokumentator: hält nach jeder freigegebenen Änderung knapp fest, was geändert wurde, wie es funktioniert und wie das Projekt aufgebaut ist.
- Konfiguration pro Rolle: Testtiefe und Testumfang (Tester), Richtlinien (Prüfer), Projektkontext für alle (wie eine CLAUDE.md).
- Modell pro Rolle einstellbar, Vorschlag: Programmierer und Tester auf Sonnet, Prüfer und Chef bei Bedarf auf Opus, Dokumentator auf Haiku. Standard ist Sonnet, damit das Kontingent lange reicht.
- Pro Agent ein Fenster mit Live-Status und technischen Daten.

### Ablauf

1. Programmierer nimmt einen Punkt, arbeitet im Branch.
2. Tester prüft. Bei Fehlern zurück zum Programmierer.
3. Prüfer kontrolliert die Richtlinien. Bei Einwänden zurück zum Programmierer, danach wieder Tester.
4. Maximal 3 Durchläufe und ein Zeitlimit pro Aufgabe, danach geht der Punkt an Janis.
5. Janis gibt frei, als weiteres Glied der Kette: per Klick auf vorgefertigte Aussagen plus Freitextfeld (z. B. bei Fehlerbeschreibungen), Berichte lassen sich vorausfüllen. Danach wird der Branch in die Produktivversion übernommen.
6. Dokumentator aktualisiert die Doku.

### Dateiablage

- Pro Projekt: Bilder, Dokumente, Webfunde.
- Inhalte gelten für Agenten als Daten, nie als Anweisung (Schutz vor Prompt-Injection).

## 6. Sicherheit und Datensicherung

- Keine offenen Ports, Zugriff nur über Tunnel.
- Passwörter nur gehasht, Zwei-Faktor-Anmeldung, Begrenzung falscher Anmeldeversuche.
- Zugangsdaten und Schlüssel nie im Code, nie im Git.
- Agenten laufen isoliert im Container und nur im Projektordner.
- Automatische Backups von Datenbank und Dateiablage auf ein zweites Medium, mit regelmäßigem Test der Wiederherstellung.
- Jede Version ist ein Git-Stand und lässt sich zurückrollen. Vor jedem Update ein Backup.
- Aktivitätsprotokoll: wer, welcher Agent, was geändert.

## 7. Reihenfolge der Umsetzung

### Phase 0 – Grundlagen (selbst lernen)

- Pi einrichten, Linux-Basics, Git, SSH mit Schlüssel.
- Eine einfache Website lokal bauen und verstehen (Seiten, Formulare, Datenbank).

### Phase 1 – Grundgerüst

- Domain sichern, Tunnel einrichten, HTTPS.
- Login mit Benutzerkonten und Passwort-Hash.
- Projektkacheln, Kanban-Board mit Papierkorb, Dateiablage.
- Erstes Backup und Rückrollen testen.

### Phase 2 – Ein Agent

- Claude Code auf dem Pi anmelden und aus der Website starten.
- Programmierer-Agent im Container und Git-Branch, Ergebnis mit Freigabe durch Janis.
- Eigene Verbrauchsanzeige.
- Tresor mit Vermittler für Zugangsdaten, bevor ein Agent irgendeinen Zugang nutzen darf.

### Phase 3 – Kreislauf

- Tester, Prüfer, Wiederholungen mit Limit, Dokumentator.
- Agentenfenster und Konfiguration pro Rolle.
- Vorschläge von Claude mit Akzeptieren und Ablehnen.

### Phase 4 – Teilen und Feinschliff

- Docker-Compose-Paket und Installationsanleitung für Freunde.
- Benachrichtigungen aufs Handy bei Freigabe oder Problemen.
- Weitere KI-Anbieter als eigene Anmeldung.

## 8. Offene Punkte

- Anbindung des Abos: Getestet am 06.11.2026: Claude Code lässt sich auf dem Pi (Debian trixie, arm64) installieren, starten und per Link und Code ohne Bildschirm mit dem Claude-Konto anmelden. Offen: Nutzungsbedingungen prüfen und ob die Anmeldung dauerhaft hält (Erneuerung).
- Vorlagen für Janis’ Freigaben und die Tester-Checklisten: welche Klick-Aussagen, welche Felder.
- Domain janis-home.de kaufen: Registrar mit .de-Unterstützung wählen, Nameserver auf Cloudflare.
- GitHub-Konto anlegen (privat).
- SSD kaufen (120–240 GB) und Umzug von der SD-Karte planen.
- E-Mail-Versand für Passwort-Reset: Dienst festlegen. Eigener Mailserver zu Hause scheidet aus (Privat-IPs landen im Spam oder auf Sperrlisten, Port 25 oft gesperrt). Gmail funktioniert, ist aber nicht sauber. Kandidaten: Versanddienst mit eigener Absender-Domain (z. B. noreply@janis-home.de) wie Brevo oder Resend im kostenlosen Tarif. Alternative für wenige Nutzer: kein Mailversand, der Admin setzt Passwörter zurück.
- Wie viele Nutzer langfristig (bestimmt Leistung des Pi und Rechtekonzept).
- Arbeitsspeicher: Der Pi 4B hat nur 1 GB (905 MiB nutzbar), Claude Code verlangt laut Anleitung 4 GB. Belastungstest mit einem echten Projekt und Docker steht aus. Fällt er schlecht aus: Runner auf Mac oder PC (Variante B) oder Pi mit 4–8 GB (Variante C).

### Checkliste vor dem Livegang

- [ ] Cloudflare Tunnel mit HTTPS eingerichtet, Port nur auf 127.0.0.1 gebunden
- [ ] Cookie mit Secure-Merkmal, per Einstellung umschaltbar (Test per HTTP, Betrieb per HTTPS)
- [ ] Versionen von fastapi, uvicorn und python-multipart festgenagelt
- [ ] Web-Container läuft als eigener Benutzer ohne Sonderrechte, mit Speicherlimit
- [ ] Geheimnisse nur in .env, nicht im Git
- [ ] Tägliches Backup (restic) läuft, Wiederherstellung einmal getestet
- [ ] Update-Ablauf festgelegt: Backup, git pull, docker compose up -d --build, Rückweg per Git
- [ ] Gesundheitsprüfung über /health in compose eingetragen
- [ ] System von SD-Karte auf SSD umgezogen
- [ ] Nur noch eine Codekopie (Doppelung /opt/agent-hub/web und Klon in workspaces aufgelöst)
- [ ] Erster Admin angelegt, Login getestet, Begrenzung falscher Anmeldeversuche aktiv
