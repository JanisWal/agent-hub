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
- Philosophie: Der Admin kennt die Passwörter der Nutzer nicht und muss sich keine ausdenken. Er vergibt beim Anlegen ein einfaches Startpasswort (z. B. „Start1234“). Der Nutzer erfährt davon und setzt über „Passwort vergessen?“ per E-Mail sein eigenes Passwort. Deshalb ist der Passwort-Reset per E-Mail Pflicht.
- Absicherung dazu: Ein Startpasswort gilt nur bis zur ersten Änderung. Beim ersten Login mit dem Startpasswort muss der Nutzer ein eigenes Passwort setzen.
- Offen: Statt Startpasswort könnte der Hub beim Anlegen direkt eine Einladungs-Mail mit Link zum Passwort-Setzen schicken (gleicher Baustein wie der Reset). Der Admin gäbe dann nur die E-Mail-Adresse ein.
- Nur der Owner kann Admin-Rechte per Schalter in der Benutzerliste vergeben oder entziehen. Das Owner-Konto kann niemand löschen oder herabstufen.
- Das Owner-Konto entsteht bei der Installation (bisher per `docker compose exec web python -m app.create_admin` im Ordner der `compose.yml`, wird zum Owner umgebaut).

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

### Phase 0 – Grundlagen (selbst lernen) – erledigt

- Pi einrichten, Linux-Basics, Git, SSH mit Schlüssel.
- Eine einfache Website lokal bauen und verstehen (Seiten, Formulare, Datenbank).

### Phase 1 – Grundgerüst – größtenteils erledigt (Rest: Dateiablage, Backup)

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

## 8. Stand der Umsetzung (07.11.2026)

Phase 0 und der Großteil von Phase 1 sind erledigt und laufen live unter `https://hub.janis-home.de`.

**Fertig:** Pi eingerichtet (Raspberry Pi OS Lite 64-Bit, Docker, Compose, SSH mit Schlüssel); Login mit Benutzerkonten; Dashboard mit Kacheln, Seiten, Drag and Drop, zweistufigem Löschen; Projektseite mit Kanban-Board und Papierkorb; Einstellungen (Nutzername, Sprache); Deutsch/Englisch; Hell/Dunkel; Cloudflare Tunnel mit HTTPS; Claude Code auf dem Pi angemeldet (Runner, noch nicht an die Website angebunden).

**Noch Platzhalter in der Oberfläche:** Claude/ChatGPT verknüpfen, Token-Anzeige, Stationen Agenten/Dateiablage/Dokumentation, Passwort vergessen.

### Aufbau des Codes

Repo `JanisWal/agent-hub` (privat), Branch `main` = Produktiv, ein Branch je Aufgabe. Nur drei Abhängigkeiten: `fastapi`, `uvicorn`, `python-multipart`. Code, Kommentare und Dateinamen sind englisch, Oberfläche und Doku deutsch. Die Oberfläche entsteht serverseitig aus Textvorlagen, ohne Framework.

```
compose.yml                  web-Dienst (127.0.0.1:8000, Daten in ./data, Netz „web“ für den Tunnel)
web/Dockerfile               python:3.13-slim, startet uvicorn app.main:app
web/app/
  main.py                    FastAPI-App, Sicherheits-Header, Fehlerumleitungen, /health
  deps.py                    Cookie-Einstellungen, Anmeldeprüfung (page_user, api_user), Antwort-Helfer
  routes/auth.py             /login, /logout, /settings
  routes/projects.py         /, /projects, /projects/move, /projects/{id}, /projects/{id}/delete
  routes/board.py            Punkte anlegen, umbenennen, ordnen, annehmen, verwerfen, Papierkorb
  db.py                      SQLite-Verbindung, Schema, kleine Migrationen (schließt Verbindungen sicher)
  users.py  projects.py  board.py   Daten und Regeln (ohne HTTP)
  layout.py                  Seitenhülle und Vorlagen-Ersetzung fill(): %NAME% = fertiger Wert, %t.schluessel% = übersetzter Text
  ui.py                      Login-Seite, Einstellungs-Schublade, angemeldeter Seitenrahmen
  dashboard.py  projectpage.py   HTML von Startseite und Projektseite
  icons.py                   alle SVG-Symbole an einer Stelle
  i18n.py                    alle Texte in Deutsch und Englisch (ein Test prüft Gleichstand)
  create_admin.py            python -m app.create_admin
  static/app.css  dashboard.css  project.css   Gestaltung (Werte siehe DESIGN.md)
  static/core.js             Theme, Formularprüfung, Schublade, Dialog-Schließen, window.AgentHub.reload
  static/motion.js           Federn und FLIP;  sortable.js: Ziehen zum Ordnen
  static/dashboard.js        Begrüßung, Dialoge;  pages.js: Seitenband, Seitenanzeige, Kachel-Ziehen;  board.js: Board
web/tests/                   Unit-Tests und integration_http.py (End-to-End über HTTP)
```

**Schnittstellen für später:** Jede Route hängt an einem eigenen Router (`routes/`), neue Bereiche (Agenten, Dateiablage, Tresor) kommen als weiteres Modul plus Router dazu, ohne `main.py` umzubauen. Die Anmeldeprüfung ist eine Abhängigkeit (`page_user` für Seiten, `api_user` für fetch-Aufrufe), eine Rollenprüfung lässt sich dort ergänzen. Neue Seiten bauen auf `ui.logged_in_page()` auf, neue Texte kommen in `i18n.py` in beide Sprachen, neue Symbole in `icons.py`. Claude-Vorschläge legt der spätere Agenten-Code mit `board.create_suggestion(project_id, kind, title)` an.

### Datenmodell (SQLite, `/data/hub.db`)

- `users`: id, email (eindeutig), password_hash (scrypt), is_admin, display_name, language (`de`/`en`), had_project, created_at.
- `sessions`: token, user_id, expires_at (14 Tage). Cookie `session`: HttpOnly, SameSite=Lax, Secure über `HUB_SECURE_COOKIE=1`.
- `projects`: id, user_id, name (höchstens 60), page, position. Sechs Kacheln pro Seite; eine volle Seite schiebt ihr letztes Projekt auf die nächste (`projects.move`). Seiten ohne Projekte gibt es nicht. Löschen ist endgültig und verlangt das Passwort.
- `board_items`: id, project_id, kind (`bug`/`minor`/`major`), title (höchstens 200), source (`user`/`claude`), status (`open`/`proposed`/`trash`), position. Von Hand angelegte Punkte sind `open` und stehen oben, Vorschläge von Claude sind `proposed` und stehen unten. Jeder Zugriff prüft, dass das Projekt dem Nutzer gehört.
- Schemaänderungen laufen über `NEW_COLUMNS` in `db.py` (Spalten werden beim Start ergänzt). Vor jeder Änderung an Daten ein Backup.

### Routen

| Methode, Pfad | Zweck | Ohne Login |
|---|---|---|
| GET/POST `/login`, POST `/logout` | Anmelden (401 bei falschen Daten), Abmelden | offen |
| GET `/`, GET `/projects/{id}` | Dashboard, Projektseite | Umleitung auf `/login` |
| POST `/settings`, `/projects`, `/projects/{id}/items`, `/items/{id}` | Formulare, antworten mit Umleitung | Umleitung auf `/login` |
| POST `/projects/move`, `/projects/{id}/delete`, `/projects/{id}/trash/empty`, `/items/reorder`, `/items/{id}/{accept,reject,discard,restore,delete}` | fetch-Aufrufe, antworten mit `{"ok": …}` | 401 |
| GET `/health` | Lebenszeichen | offen |

`/docs`, `/redoc` und `/openapi.json` sind abgeschaltet. Alle Antworten tragen `X-Content-Type-Options`, `X-Frame-Options: SAMEORIGIN` und `Referrer-Policy`; Seiten (nicht `/static`) zusätzlich `Cache-Control: no-store`, bei HTTPS `Strict-Transport-Security`.

## 9. Betrieb

### Pi, Zugriff und Ordner

- Gerät im Heimnetz: `admin@home.local`, Anmeldung per SSH-Schlüssel (`~/.ssh/id_agenthub`, ohne Passphrase, auf dem Pi in `authorized_keys` mit Kommentar `agent-hub-claude`). `admin` ist in der Gruppe `docker`. Passwörter tippt Janis selbst, Claude kennt und speichert keine.
- Produktiv läuft der Klon `/opt/agent-hub/workspaces/agent-hub` (`main`, entspricht GitHub). Daten liegen in dessen Ordner `data/`. Der Tunnel liegt getrennt unter `/home/admin/cloudflared` (Token in dessen `.env`, nie im Git).
- Die Seite erreicht der Tunnel über das Docker-Netz `web` (Alias `agent-hub`, Port 8000). Cloudflare leitet `hub.janis-home.de` an `http://agent-hub:8000`. Port 8000 ist nur auf `127.0.0.1` des Pi offen, von außen und im LAN geschlossen.
- GitHub: Deploy-Key auf dem Pi, Push von dort.

### Update-Ablauf

1. Backup der Datenbank: `cp data/hub.db /opt/agent-hub/backups/hub-$(date +%F).db` (im Klon-Ordner, Dienst darf laufen).
2. Änderungen auf einem Branch entwickeln und testen, dann nach `main` mergen und pushen.
3. Auf dem Pi im Klon-Ordner: `git pull`, dann `docker compose up -d --build web`.
4. Prüfen: `curl -s http://127.0.0.1:8000/health` und `https://hub.janis-home.de/login`.
5. Zurück: `git revert <Commit>`, erneut bauen; Daten notfalls aus dem Backup.

### Tests

- **Unit-Tests** (laufen im Container, ohne den Dienst anzufassen), im Klon-Ordner: `docker compose run --rm --no-deps -v "$PWD/web/tests:/app/tests" web python -W ignore -m unittest discover -s tests -t .`
- **HTTP-Test** gegen eine Wegwerf-Instanz mit eigener Datenbank und Testkonto, z. B. `docker run -d --name hub-test -p 8001:8000 -e HUB_DB=/tmp/test.db -e HUB_SECURE_COOKIE=0 agent-hub-web`, Testnutzer mit `users.create_user` anlegen, dann `python3 web/tests/integration_http.py http://127.0.0.1:8001 EMAIL PASSWORT`. Bei HTTP muss `HUB_SECURE_COOKIE=0` stehen, sonst sendet der Client den Cookie nicht zurück. Nie mit dem echten Konto testen.
- **Browser-Prüfung** der Oberfläche in Claude in Chrome gegen die Testinstanz auf Port 8001 (Seite `http://home.local:8001`). Fenstergrößen werden über Rahmen (iframe) in der gewünschten Größe geprüft, weil `resize_window` das Fenster nicht ändert. In einem minimierten Test-Fenster pausiert Chrome `requestAnimationFrame` und CSS-Animationen: dann den Takt durch einen 16-ms-Zeitgeber ersetzen und endliche Animationen mit `getAnimations().finish()` beenden. Das Feld mit `autofocus` bekommt keinen Fokus, daher per `input.focus()` setzen und 2 bis 3 s nach dem Laden warten. Klicks per Koordinate: Bildschirmfoto ist skaliert (1568 px breit), also `getBoundingClientRect` über `javascript_tool` lesen und umrechnen.
- Die Federn und die gefühlte Flüssigkeit kann nur Janis in einem sichtbaren Fenster beurteilen. Berührung am echten Handy ist ungeprüft.
- Aus PowerShell keine verschachtelten Anführungszeichen für `ssh`: längere Schritte als Skriptdatei per `scp` hochladen und mit `bash` ausführen.

### Zusammenarbeit mit Claude (Regeln von Janis)

- Commit, Merge, Push, Deploy und Testläufe ohne Rückfrage, danach kurz berichten. Fragen nur bei Berechtigungen, Sicherheit sowie Design- und Feature-Entscheidungen. Keine „Verständnisfragen“ am Ende einer Antwort. Bei Änderungen an der Infrastruktur klar sagen, was entfernt und was neu ist.
- Destruktive oder systemweite Befehle (Löschen, Docker-Volumes, `sudo`, Netzwerk) vorher bestätigen lassen. Hardware am Fahrzeug nie autonom schalten.
- Ein Thema pro Commit, kurze Commit-Nachrichten. Neue Abhängigkeiten nennen und begründen.
- Oberfläche folgt den Apple Human Interface Guidelines und dem Skill `apple-design`, Werte in DESIGN.md.

## 10. Arbeitsplatz wechseln (Windows-PC → MacBook)

Eine laufende Claude-Code-Sitzung zieht nicht um; der PC muss an bleiben, bis ein Auftrag fertig ist. Danach lässt sich am Mac weiterarbeiten:

1. Projektordner `Claude Projekte/Claude Board` ist per iCloud schon auf dem Mac (CLAUDE.md, PROJEKT.md, DESIGN.md und Skill `.claude/skills/apple-design`). Claude liest beim Start diese Dateien, damit hat jeder Chat den gleichen Stand.
2. SSH-Schlüssel für den Pi: auf dem Mac `ssh-keygen -t ed25519 -f ~/.ssh/id_agenthub -N ""`, den öffentlichen Teil (`~/.ssh/id_agenthub.pub`) auf dem Pi in `~/.ssh/authorized_keys` ergänzen (einmalig mit Janis’ Passwort, das er selbst tippt). Danach `ssh -i ~/.ssh/id_agenthub admin@home.local`.
3. Claude in Chrome: Erweiterung im Chrome des Macs installieren und anmelden, dann gilt dieselbe Prüfweise wie in Abschnitt 9.
4. Die Erinnerungen von Claude (Auto-Memory) liegen nur auf dem PC (`C:\Users\janis\.claude\projects\…\memory`). Ihr Inhalt steht hier in Abschnitt 9, am Mac wird nichts davon benötigt.
5. Repo am Mac klonen: `git clone git@github.com:JanisWal/agent-hub.git` (mit einem eigenen GitHub-Zugang des Macs).

## 11. Offene Punkte

- Anbindung des Abos: Claude Code lässt sich auf dem Pi (Debian trixie, arm64) installieren und per Link und Code ohne Bildschirm anmelden (getestet 06.11.2026). Offen: Nutzungsbedingungen prüfen und ob die Anmeldung dauerhaft hält.
- Vorlagen für Janis’ Freigaben und die Tester-Checklisten: welche Klick-Aussagen, welche Felder.
- Domain `janis-home.de` ist im Einsatz (Subdomain `hub`); Registrar und Cloudflare-Konditionen bei Gelegenheit prüfen. Optional Cloudflare Access (Code per E-Mail) als zusätzliche Hürde vor der Seite, bis eine Begrenzung der Anmeldeversuche gebaut ist.
- SSD kaufen (120–240 GB) und Umzug von der SD-Karte planen.
- E-Mail-Versand für Passwort-Reset: Dienst festlegen. Eigener Mailserver zu Hause scheidet aus (Privat-IPs landen im Spam oder auf Sperrlisten, Port 25 oft gesperrt). Gmail funktioniert, ist aber nicht sauber. Kandidaten: Versanddienst mit eigener Absender-Domain (z. B. noreply@janis-home.de) wie Brevo oder Resend im kostenlosen Tarif. Der Reset per E-Mail ist gesetzt (siehe Benutzerverwaltung), Favorit: Resend.
- Wie viele Nutzer langfristig (bestimmt Leistung des Pi und Rechtekonzept).
- Arbeitsspeicher: Der Pi 4B hat nur 1 GB (905 MiB nutzbar), Claude Code verlangt laut Anleitung 4 GB. Belastungstest mit einem echten Projekt und Docker steht aus. Fällt er schlecht aus: Runner auf Mac oder PC (Variante B) oder Pi mit 4–8 GB (Variante C).
- Aufräumen auf dem Pi: Codekopie `/opt/agent-hub/web` und alte Branches, doppelte `docker-compose.yml` unter `/home/admin/cloudflared`.
- Oberfläche: siehe DESIGN.md, Abschnitt „Noch offen“.

### Checkliste vor dem Livegang

- [x] Cloudflare Tunnel mit HTTPS eingerichtet, Port nur auf 127.0.0.1 gebunden
- [x] Cookie mit Secure-Merkmal, per Einstellung umschaltbar (`HUB_SECURE_COOKIE`)
- [x] Geheimnisse nur in .env, nicht im Git
- [x] Update-Ablauf festgelegt (Abschnitt 9)
- [x] Erster Admin angelegt, Login getestet
- [x] Sicherheits-Header gesetzt, API-Dokumentation abgeschaltet
- [ ] Begrenzung falscher Anmeldeversuche (Anmeldung und Löschen) – von Janis noch nicht freigegeben
- [ ] Versionen von fastapi, uvicorn und python-multipart festgenagelt
- [ ] Web-Container läuft als eigener Benutzer ohne Sonderrechte (Datenordner-Rechte anpassen), mit Speicherlimit
- [ ] Gesundheitsprüfung über `/health` in compose eingetragen
- [ ] Content-Security-Policy (benötigt, dass das Theme-Skript im `<head>` ohne Inline-Code auskommt)
- [ ] Tägliches Backup (restic) läuft, Wiederherstellung einmal getestet
- [ ] System von SD-Karte auf SSD umgezogen
- [ ] Nur noch eine Codekopie (Doppelung /opt/agent-hub/web und Klon in workspaces aufgelöst)
