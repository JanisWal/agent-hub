# Agent-Hub – Projektsheet

Stand: 07.11.2026 (Ende des Tages, nach dem Merge `review-cleanup`) · Autor: Janis (mit Claude) · Zweck: Philosophie, Ziel, Entscheidungen und Reihenfolge, damit jeder Claude-Chat im Projekt denselben Stand hat.

## Auf einen Blick (zuerst lesen, für neue Chats)

- **Was läuft:** Der Hub ist live unter `https://hub.janis-home.de` (Raspberry Pi 4B, 1 GB, Docker Compose, Cloudflare Tunnel). Repo `JanisWal/agent-hub` (privat), `main` = Produktiv und entspricht dem, was auf dem Pi läuft. Verlauf der Änderungen: Abschnitt 12.
- **Fertig:** Login, Dashboard mit Kacheln (Ziehen, Seiten), Projektseite mit Kanban-Board und Papierkorb, Hell/Dunkel, Deutsch/Englisch, Benutzerverwaltung mit Rollen Owner/Admin/Nutzer, Einladung und „Passwort vergessen“ per E-Mail (Resend, schöne HTML-Mails in Hell und Dunkel), Owner-Übergabe, Sperre nach falschen Passwörtern und nach zu vielen Reset-Anfragen, Mandantentrennung mit Tests.
- **Noch nicht gebaut:** Claude-Anbindung und Agenten (Phase 2 und 3), Dateiablage, Tresor, Token-Anzeige, Backup mit restic, Umzug auf SSD, Härtung des Containers (Abschnitt 11, Checkliste).
- **Agenten (Branch `agent-core`, am 07.11.2026 nach `main` gemergt und ausgerollt):** Der Knopf „Verknüpfen“ für Claude in der Schublade läuft live, dazu der Dienst `runner` (Anmeldungen, Löschen getrennter Ordner). Gebaut und getestet, aber noch ohne Oberfläche und ohne Schleife für Agentenläufe: Kette der Agenten, Auftragswarteschlange, Launcher (ein Container je Lauf). Ungeprüft live: der Erfolgsweg der Anmeldung mit einem echten Code (Janis). Konzept: `KONZEPT-AGENTEN.md`. Konzept, Schnittstellen und offene Entscheidungen: `KONZEPT-AGENTEN.md`.
- **Chat-Fenster (fertige Fassung, live seit 07.11.2026):** Auf der Projektseite fragt das Fenster „Claude“ (rechter Rand, auf allen Reitern) das eigene Claude kurze Einzelfragen: mit drei Modi je Frage per Schalter (nur antworten, Web: suchen und Seiten lesen, Code: Programme ausführen ohne Internet; Internet nur über den Filter-Proxy egress), ohne Projektdateien, ohne Gedächtnis früherer Fragen, Haiku. Im Menü (Zahnrad) löscht ein eigener Knopf „Chatverlauf löschen“ (roter Bestätigungsdialog, Abbrechen mit Standardfokus, ohne Passwort) alle Fragen und Antworten des Nutzers; pro Nutzer bleiben höchstens 100 Nachrichten. Das Trennen von Claude löscht den Verlauf bewusst nicht. Beim Trennen und beim Löschen eines Kontos räumt der Runner den Claude-Ordner auf (`claude_wipes`). Mögliche Erweiterungen (Projektbezug, Gedächtnis, Modellwahl, Verbrauch) bespricht Janis später.
- **Pflichtregeln für alles Neue:** Standards in `CLAUDE.md`; Gestaltung in `DESIGN.md`; die Trennung der Nutzer (Abschnitt 6) und die Trennung der Claude-Konten (Abschnitt 3, „Trennung der Claude-Konten“) gelten ausnahmslos.
- **So wird gearbeitet:** Janis beauftragt, Claude zeigt erst die Schnittstelle, dann den Code. Auf dem Windows-PC gibt es kein Git: Claude bearbeitet Dateien lokal im Arbeitsordner (Scratchpad), kopiert sie per `scp` in den Klon auf dem Pi, testet dort im Container, committet auf einem Branch je Thema, merged nach `main`, pusht, sichert die Datenbank und baut neu (Abschnitt 9, „Arbeitsablauf vom PC aus“). Commit, Merge, Push, Deploy und Tests ohne Rückfrage, Fragen nur bei Berechtigungen, Sicherheit und Design- oder Feature-Entscheidungen.
- **Nächste Schritte (Vorschlag, Reihenfolge):** (1) Janis prüft die Mails und die Einladung in echten Postfächern (Gmail, Apple Mail, Hell und Dunkel) und die Owner-Übergabe mit einem Testkonto; (2) Rest von Phase 1: Dateiablage, Backup mit restic, SSD; (3) Checkliste vor dem Livegang: Container als eigener Benutzer mit Speicherlimit, Gesundheitsprüfung, Content-Security-Policy; (4) Phase 2: Claude-Anbindung pro Nutzer nach den Pflichtregeln, Runner an die Website, Verbrauchsanzeige, Tresor; (5) Aufräumen auf dem Pi (Abschnitt 11).
- **Übergabe:** `CHAT-ZUSAMMENFASSUNG.md` fasst den Stand und die Entscheidungen des letzten Arbeitstags zusammen.

## 1. Ziel und Philosophie

- Ein selbst gehostetes Verwaltungstool für Software-Projekte auf einem Raspberry Pi: Projekte als Kacheln, Kanban-Board, feste KI-Agenten-Rollen, Dateiablage.
- Hobbyprojekt, aber in Bausteinen und offen gedacht: Freunde können das Grundgerüst auf einem eigenen Pi installieren.
- Janis baut es per Vibe-Coding mit Claude. Die Basics (Website, Datenmodell, Sicherheit, Rollenablauf) will er selbst verstehen und lernen.
- Kein Verkauf geplant. Keine Mehrkosten über das Pro-Abo hinaus.
- Regel für Claude: kleinste Lösung, die die Anforderung erfüllt; erst die Schnittstelle zeigen, dann die Implementierung; ein Modul pro Auftrag; Entscheidungen kurz begründen.
- Allgemeines Ziel: effizient arbeiten. Das Pro-Kontingent ist begrenzt, also verbraucht jede Aufgabe nur so viel wie nötig: kleine, klar umrissene Aufträge, das passende Modell je Aufgabe, nur der nötige Kontext (kurze CLAUDE.md, nur die relevanten Dateien), Limits für Durchläufe und Zeit und ein sichtbarer Verbrauch pro Lauf, um Verschwendung zu erkennen.

## 2. Getroffene Entscheidungen

- Claude Pro-Abo, keine API-Kosten. Sind die Limits aufgebraucht, wird später weitergearbeitet.
- Zugriff von überall über eigene Domain, Login mit E-Mail und Passwort. Passwort zurücksetzen und Einladungen per E-Mail über Resend (gebaut, Abschnitt 5 und 9).
- Rollen: Owner (genau einer, übertragbar), Admin, Nutzer. Keine Selbstregistrierung. Jeder Nutzer sieht und ändert nur seine eigenen Daten, und jeder verbindet sein eigenes Claude-Konto (Pflichtregeln in Abschnitt 3 und 6).
- Eine Installation pro Pi, mit Benutzerkonten. Andere nutzen entweder Janis’ Pi als Server mit eigener Claude-Anbindung oder installieren das Paket auf einem eigenen Pi. Janis’ Abo wird nie geteilt.
- Zuerst nur Claude. Andere KIs (z. B. ChatGPT) später als separate Anmeldung hinter einer gemeinsamen Schnittstelle.
- Programmiersprache Python; ein Wechsel nur, wenn JavaScript große Vorteile bringt.
- Eigene Struktur konsequent umsetzen, vorhandene Open-Source-Bausteine nutzen, wo sie passen.
- Tägliches Backup auf eine externe SSD mit restic (verschlüsselt, nur Änderungen), zusätzlich Git-Spiegel auf GitHub. Struktur, Doku und offene Punkte haben höchste Priorität. Zurückrollen von Versionen gehört von Anfang an dazu.
- Zunächst ein bis zwei weitere Nutzer; bei Problemen wird reguliert.
- GitHub: privater Spiegel der Projekte, später auch zum Teilen mit Freunden.
- Modellwahl: Standard ist Sonnet 5.5 (gut genug für den Alltag, schont das Pro-Limit). Opus 5.5 nur gezielt für schwierige Aufgaben (Architektur, hartnäckige Fehlersuche, Prüfer), Haiku 5.5 für einfache, häufige Aufgaben (Zusammenfassungen, Commit-Texte). Umschalten in Claude Code mit /model.

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

### Trennung der Claude-Konten (Pflichtregeln, Janis, 07.11.2026)

Jeder Nutzer verbindet sein eigenes Claude-Konto. Die Konten dürfen sich nie berühren: Wer ein Konto verbindet, bindet es nur für sich, und niemand benutzt je das Claude eines anderen mit. **Stand heute:** Nichts davon ist gebaut, die Website kennt noch keine Claude-Anbindung (die Einträge „Claude“ und „ChatGPT“ in der Schublade sind feste Platzhalter). Die einzige Claude-Anmeldung auf dem Pi (Janis’ Konto) liegt im Docker-Volume `agent-hub_claude-home` des alten Runners (`/opt/agent-hub/compose.yml`, Profil `tools`, von Hand gestartet); das Volume hängt an keinem Dienst der Website, ein Zugriff aus dem Hub ist also nicht möglich. Beim Bau der Anbindung gilt, und der Isolationstest des Runners prüft es:

1. **Ein Konfigurationsordner pro Nutzer.** Jeder Nutzer bekommt seinen eigenen Ordner für die Claude-Anmeldung (z. B. `/data/claude/<user_id>/`, über `CLAUDE_CONFIG_DIR`/`HOME` des Prozesses). Es gibt nie ein gemeinsames Volume und kein gemeinsames `HOME` für mehrere Nutzer. Janis’ bestehende Anmeldung wird sein Nutzerordner, nicht der Standard für alle.
2. **Kein Rückfall.** Hat ein Nutzer kein Claude verbunden (oder ist die Verbindung abgelaufen), startet seine Aufgabe nicht und wartet mit dem Status „nicht verbunden“. Es gibt keinen Ersatz durch die Anmeldung eines anderen, auch nicht die des Owners.
3. **Ein Lauf sieht nur seinen Nutzer.** Jede Aufgabe läuft in einem eigenen Container oder Prozess, der nur zwei Ordner sieht: den Projektordner dieser Aufgabe und den Claude-Ordner dieses Nutzers. Weder die Ordner anderer Nutzer noch `hub.db`, `.env`, Backups oder der Tresor sind eingehängt. Zwischen zwei Läufen verschiedener Nutzer gibt es keinen geteilten Speicher, keine gemeinsame Arbeitskopie und keine Verbindung zwischen den Agenten.
4. **Der Nutzer kommt vom Server, nie vom Aufrufer.** Der Runner bekommt `user_id` und Projekt aus dem Aufgabendatensatz auf dem Server, nie aus einem Parameter, den ein Browser mitschicken kann. Schreibt ein Agent ins Board, dann mit `board.create_suggestion(user_id, project_id, kind, title)`; die Funktion prüft wie alle anderen, dass das Projekt diesem Nutzer gehört.
5. **Token nur verschlüsselt und nur für den Besitzer.** Verbindungsdaten liegen verschlüsselt pro Nutzer. Weder Admins noch der Owner können sie anzeigen oder exportieren. Die Anzeige „Verknüpft“ und die Nutzungszählung hängen am Nutzer, nicht am Pi.
6. **Test.** Vor dem ersten Livegang der Anbindung kommt ein Test, der mit zwei Nutzern prüft: Der Lauf von B hängt nur den Ordner von B ein, ohne Verbindung von B startet nichts, und die Zählung von A bleibt bei A.

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

### Zugriff der Agenten auf Geräte (SSH)

- Claude Code läuft als lokales Programm auf dem Pi (bzw. Mac-Runner), nicht als Cloud-Sitzung. Es kann daher alles, was eine Shell auf diesem Rechner kann, auch `ssh` zu anderen Geräten im Heimnetz.
- Die Einschränkung „kein SSH, nur lokal“ betrifft Claude Code im Web (Sitzungen in Anthropics Cloud). Die nutzt der Hub nicht.
- Agenten sprechen nicht direkt miteinander: Der Hub reicht Ergebnisse weiter (Branch, Berichte, Datenbank).
- Geräte per USB (z. B. ESP32, Arduino): Runner auf dem Rechner, an dem das Gerät hängt, oder USB an den Container durchreichen.
- Geräte außerhalb des Heimnetzes: per VPN, siehe unten.

### Geräteliste und Netzwege (entschieden 07.11.2026, Janis)

- **Das Heimnetz bleibt für Agenten gesperrt.** Läufe haben keine Route dorthin; ihr einziger Weg nach draußen ist der `egress`-Proxy (KONZEPT-AGENTEN.md 6a). Verworfen: das Heimnetz pauschal freigeben. Ein per Webseite gelenkter Agent (Prompt-Injection) säße dann im Netz und erreichte alles ohne Passwort: Router, Drucker, Smart Home, Dienste des Pi, Geräte am Fahrzeug, später auch Agenten fremder Nutzer in Janis’ Netz. Ein SSH-Schlüssel schützt davor nicht, denn der Agent sitzt schon drin.
- **Geräteliste im Manager:** Der Nutzer trägt den Hostnamen eines Geräts ein. Der Hub (der Vermittler, nie der Agent) löst ihn im Netz auf, liest die Gerätedaten (Adresse, SSH-Port, Hostschlüssel) und führt das Gerät nach Freigabe durch den Nutzer in der Liste der freigegebenen Geräte. Optional wird dem Gerät ein SSH-Schlüssel im Tresor zugeordnet. Der Agent erreicht Geräte nur über den Vermittler; Schlüssel gelangen nie in einen Lauf-Container.
- **Auflagen** (Vorschlag von Claude, von Janis noch nicht ausdrücklich bestätigt, aber Teil der Mandantentrennung): ein Gerät gehört genau einem Nutzer und einem Projekt (Fall in `test_isolation.py`); die aufgelöste Adresse wird gespeichert und bei jeder Verbindung geprüft (kein Umlenken per DNS); der Hostschlüssel wird beim Eintrag gemerkt und danach geprüft; pro Gerät eine Liste erlaubter Befehle (bei Testgeräten weiter gefasst); Hardware am Fahrzeug (Roadster, Heizung, Relais, Bordnetz) steht nie auf der Liste, das schaltet Janis vor Ort.
- **Geräte in fremden Netzen** (z. B. beim Kollegen zu Hause): per VPN, sternförmig mit dem Pi in der Mitte. Isolation, wie von Janis festgelegt: (1) Jeder Kollege hat seine **eigene** VPN-Verbindung zum Pi, und der Pi leitet **nicht** zwischen den Verbindungen weiter, damit Kollege A und Kollege B einander nie erreichen. (2) Der Pi darf zum Gerät nur per SSH (Port 22), das Gerät und die Verbindung dürfen weder ins Netz des Pi noch ins restliche Netz des Kollegen. Umgesetzt mit Firewall-Regeln am Pi (Weiterleiten verboten, einzige Ausnahme Pi zu Gerät Port 22) und am Gerät des Kollegen (nur Pi, nur Antworten).
- **VPN-Technik (Claude auf Janis’ Auftrag zu prüfen, Stand 07.11.2026 recherchiert): Tailscale.** Harte Vorgabe von Janis: **Auf der Fritzbox wird kein Port geöffnet.** Selbst gehostetes Headscale scheidet damit aus: Nach seiner Dokumentation läuft es hinter Cloudflare Tunnel nicht (Cloudflare reicht die nötigen WebSocket-POSTs nicht durch), und sein eingebauter Relay-Dienst braucht UDP 3478 öffentlich erreichbar. Es bräuchte also offene Ports oder einen zusätzlichen Server im Internet. Tailscale verbindet nur ausgehend (NAT-Durchdringung, bei Bedarf Relay über Tailscales Server), ohne offenen Port. Zugriffsregeln: Geräte der Kollegen bekommen ein Etikett (Tag) und werden mit einem Einmal-Schlüssel des Owners aufgenommen, die Kollegen brauchen kein eigenes Tailscale-Konto; Regel „Hub darf zu Gerät Port 22“, alles andere ist verboten (Standard von Tailscale), damit sind Kollegen untereinander und Geräte zum Netz hin getrennt. Kostenloser Tarif nach Tailscales Preisseite: bis 6 Nutzer, unbegrenzt Geräte, bis 50 Etikett-Geräte (frühere Quellen nennen 3 Nutzer; die Preisseite gilt). **Nachteile:** Tailscale (Drittanbieter) verwaltet die Zugangsdaten der VPN-Knoten und sieht Metadaten, nicht den Verkehr; der kostenlose Tarif ist nur für nicht gewerbliche Nutzung gedacht. **Vor dem Bau zu prüfen:** ob die Etiketten mit den drei „ACL-Gruppen“ des kostenlosen Tarifs auskommen, die Nutzungsbedingungen, und optional Tailnet Lock (Knoten nur mit Signatur des Owners). Verworfen: WireGuard mit offenem Port (Fritzbox), Headscale (siehe oben), umgekehrter SSH-Tunnel (mehr Eigenbau, keine Regeln pro Gerät).

### Mac-Integration: lokaler Runner

- Ein Browser darf keine Programme auf dem Mac starten, und ein offener Mac-Port wäre ein Risiko. Darum läuft auf dem Mac ein kleines Programm, der Runner. Er baut selbst eine Verbindung zum Pi-Server auf (nur ausgehend) und braucht **keine eigene Anmeldung oder Kopplung** (entschieden 07.11.2026, Janis): Die Anmeldung im Hub gilt als Verifikation. Der Nutzer drückt in der Website den Knopf; der Hub erzeugt ein kurzlebiges Einmal-Ticket für genau diesen Nutzer und diese Aufgabe, der Browser übergibt es über einen eigenen Link (`agenthub://`) an das Mac-Programm, das es beim Hub gegen die Aufgabe eintauscht. Das Ticket bedient der Nutzer nie. Das Mac-Programm (Plugin) muss einmal installiert sein und ist noch zu bauen. Verworfen: Kopplung per Code in den Einstellungen.
- Bei passenden Aufgaben (z. B. Swift) zeigt die Website den Knopf „Lokale Ressourcen verwenden“, sobald ein Mac-Runner online ist. Ist der Mac aus, steht dort „Mac nicht verbunden“ und die Aufgabe wartet.
- Ablauf: Runner holt das Repo, startet Claude Code auf dem Mac (Xcode, Simulator), schickt das Ergebnis zurück und meldet Status und Ergebnis an die Website.
- **Rückgabe ins Projekt (Janis, 07.11.2026: muss ins Projekt einfließen):** Der Mac erreicht den Pi nicht per Git oder SSH (kein offener Port), alles läuft über den Hub per HTTPS, ausgehend, mit dem Einmal-Ticket. (1) **Holen:** Der Hub gibt dem Mac das Repo als Git-Bundle (Stand der Aufgabe). (2) **Zurück:** Der Mac lädt am Ende **ein Git-Bundle mit genau dem Branch dieser Aufgabe** hoch. Der Hub prüft es (Größenlimit, nur dieser eine Branch, Basis ist der bekannte Stand, Branchname vom Hub vorgegeben, nie vom Mac), holt es per `git fetch` aus dem Bundle in das Projekt-Repo und läuft dann in der gewohnten Kette weiter (Prüfer, Freigabe durch den Nutzer, Merge nach `main`, Manager führt die Doku nach), genau wie nach einem Lauf auf dem Pi. (3) **Ergebnisse:** Der Mac meldet die letzte Zeile `RESULT: …` und den Bericht als Daten, wie die Läufe auf dem Pi. (4) **Abbruch:** Kommt kein Ergebnis (Mac aus oder Verbindung weg), läuft das Ticket ab, die Aufgabe steht wieder auf „wartet auf Mac“, Teilergebnisse gelten nicht. (5) **Hat sich `main` inzwischen geändert,** löst der Merge bei der Freigabe das auf (Modul „Worktrees und Merge“); bei Konflikt geht die Aufgabe an den Nutzer. Die Aufgabe wird nur angenommen, wenn Ticket, Nutzer und Aufgabe zusammenpassen (Mandantentrennung, Fall in `test_isolation.py`).
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

- Drei Rollen: Owner (immer genau einer, zunächst Janis), Admin, Nutzer. Der Owner hat alle Admin-Rechte. Der Owner ist keine feste Person: Er kann die Owner-Rechte an ein anderes Konto übergeben (siehe unten).
- Keine Selbstregistrierung: Neue Konten legen nur Owner und Admins an.
- In den Einstellungen: „Benutzer hinzufügen“ nimmt nur die E-Mail-Adresse und schickt eine Einladungs-Mail (siehe unten).
- Liste der Benutzer: Passwörter zurücksetzen und Konten löschen (Owner und Admins).
- Philosophie: Der Admin kennt die Passwörter der Nutzer nicht und muss sich keine ausdenken. Beim Anlegen gibt er nur die E-Mail-Adresse ein; der Hub schickt eine Einladungs-Mail mit einem Link, über den der Nutzer sein eigenes Passwort festlegt (gleicher Baustein wie der Reset per E-Mail, der Link gilt 7 Tage). Das Konto bekommt bis dahin ein Zufallspasswort, das niemand kennt.
- Klappt der Mailversand nicht, wird das neue Konto wieder entfernt und der Admin sieht eine Meldung. Ohne Resend-Einstellungen (Abschnitt 9) lassen sich also keine Nutzer einladen.
- Ein vom Admin vergebenes Startpasswort gibt es nur noch beim Zurücksetzen eines bestehenden Kontos (Schlüssel-Knopf in der Liste). Es gilt bis zur ersten Änderung: Beim ersten Login muss der Nutzer ein eigenes Passwort setzen.
- Nur der Owner kann Admin-Rechte per Schalter in der Benutzerliste vergeben oder entziehen. Das Owner-Konto kann niemand löschen oder herabstufen; die Rolle wechselt nur durch die Übergabe.
- **Owner übergeben** (Janis, 07.11.2026, Branch `owner-transfer`): In der Benutzerliste hat der Owner pro Konto einen Kronen-Knopf „Zum Owner machen“. Der Dialog „Owner-Rechte übergeben?“ erklärt, dass die Person Owner wird und er selbst Admin, und verlangt sein Passwort (Sperre pro IP wie beim Löschen). Beide Änderungen geschehen in einer Transaktion (`users.transfer_owner`): erst wird der alte Owner Admin, dann der neue Owner; es gibt nie keinen und nie zwei. Nur der Owner darf das, nicht an sich selbst, und nur an Konten, die schon ein eigenes Passwort gewählt haben (sonst könnte die Rolle bei jemandem landen, der sich nicht anmelden kann; für solche Konten fehlt der Knopf). Der neue Owner hat sofort alle Owner-Rechte, der alte nur noch Admin-Rechte; Sitzungen bleiben bestehen. Zurück geht es nur, wenn der neue Owner wieder übergibt. Abgesichert an drei Stellen: `create_user` und `transfer_owner` im Code, dazu ein eindeutiger Teilindex `users_one_owner` in der Datenbank (`UNIQUE (role) WHERE role = 'owner'`). Der Index legt keine Person fest, er verbietet nur einen zweiten Owner.
- **Gebaut am 07.11.2026** (Branch `user-management`): Rollen `owner`/`admin`/`user` in `users.role`, Seite `/users` (Eintrag „Benutzer verwalten“ in der Einstellungs-Schublade, nur für Owner und Admins), Dialoge zum Hinzufügen, Zurücksetzen und Löschen. Zurücksetzen und Löschen verlangen das Passwort dessen, der es tut (mit der Sperre pro IP). Wer sich mit einem Startpasswort anmeldet, erreicht nur `/password`, bis er ein eigenes gesetzt hat; dabei enden seine anderen Sitzungen. Der Owner kann Admins ernennen und entziehen und alle anderen verwalten, Admins verwalten nur normale Nutzer, niemand rührt den Owner an. Beim Löschen eines Kontos verschwinden auch seine Projekte.
- **Gebaut am 07.11.2026** (Branch `password-reset`): „Passwort vergessen?“ auf der Login-Seite führt zu `/forgot`, die Mail kommt über Resend (`mail.py`) mit einem Link `HUB_BASE_URL/reset/{token}` (1 Stunde gültig, einmalig, Sprache des Nutzers). Mit dem Link legt man ein Passwort nach den üblichen Regeln fest; danach enden alle Sitzungen und ein Startpasswort-Zwang entfällt.
- **Gebaut am 07.11.2026** (Branch `invite-mail`): Die Mails (Reset und Einladung) sind HTML-Mails im Design des Hubs (`mailtext.py`): Begrüßung „Hallo Name,“ (Name oder Teil vor dem `@`), Text, großer Knopf in der Akzentfarbe, darunter der Link als Text und ein Hinweis zur Gültigkeit; dazu immer eine reine Textfassung. Es gibt zwei Farbstile (hell und dunkel, Werte aus DESIGN.md Abschnitt 2); verschickt wird der Stil, den der Nutzer zuletzt gesehen hat. Dafür merkt sich der Server die Wahl pro Konto (`users.theme`, `light` oder `dark`, Standard `light`): Der Schalter speichert weiter im Browser (`localStorage`) und meldet die Wahl zusätzlich per `POST /theme`; außerdem meldet jede angemeldete Seite beim Laden ihren Stil, wenn er vom gespeicherten abweicht (so zählt auch die Geräteeinstellung, und das zuletzt benutzte Gerät gewinnt). Bei einem noch nie angemeldeten Konto (frische Einladung) ist die Mail hell. Mailprogramme wie Gmail färben dunkle Mails im Dunkelmodus eventuell selbst um.
- **Passwortseite** (`/password`, 07.11.2026): Wer sich gerade mit einem Startpasswort angemeldet hat, sieht nur „Neues Passwort“ und „wiederholen“ (kein aktuelles Passwort, er hat es eben eingegeben und es ist ohnehin nicht seins; das neue darf nicht gleich dem Startpasswort sein). Wer sein eigenes Passwort ändert, gibt wie bisher das aktuelle an. Beide Seiten haben „Abbrechen“: normal zurück zum Dashboard, bei Startpasswort Abmelden (jede andere Seite schickt ihn sonst hierher zurück). Der Reset-Link aus der Mail (`/reset/{token}`) fragt nie nach dem alten Passwort und hat ebenfalls „Abbrechen“ (zur Anmeldung). In der Benutzerverwaltung heißt der Rückweg „Zurück“.
- **Passwortregeln** (Janis, 07.11.2026): für selbst gewählte Passwörter mindestens 6 Zeichen mit Groß- und Kleinbuchstaben, einem Sonderzeichen und zwei Zahlen (`users.password_problem`). Ein vom Admin vergebenes Startpasswort braucht nur 6 Zeichen, denn der Nutzer ersetzt es sofort. `users.set_password(user_id, neues_passwort)` prüft nur die Länge, beendet alle Sitzungen (außer der als `keep_token` übergebenen) und macht offene Reset-Links ungültig; wer ein Passwort wählen lässt, prüft vorher `password_problem` (so tun `/password` und `/reset/{token}`).
- Das Owner-Konto entsteht bei der Installation (`docker compose exec -it web python -m app.create_admin` im Ordner der `compose.yml`: das erste Konto wird Owner, weitere werden Admins). Ein normales Konto lässt sich nur über die Website einladen; per SSH gäbe es nur den Aufruf von `users.create_user` mit `python -c`, einen fertigen Befehl gibt es dafür nicht.
- Sicherheits-Eigenschaften der Konten (Stand 07.11.2026): Passwörter als scrypt-Hash mit eigenem Salz; Sitzungen und Reset-Links nur als SHA-256-Hash in der Datenbank; Cookie HttpOnly, SameSite=Lax, Secure; Rollen werden bei jeder Anfrage aus der Datenbank gelesen (eine Rollenänderung gilt sofort, auch für laufende Sitzungen); Rollenrechte prüft der Server (`users.can_manage`, `transfer_owner`, Routen), nicht nur das Menü.

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
- Tester: prüft das Ergebnis. Bei Hardware-Themen erzeugt er eine Checkliste, die zum Manager geht (nicht aufs Board, Janis 07.11.2026). Kann er etwas nicht prüfen (z. B. Hardware), meldet er „nicht prüfbar“.
- Prüfer: kontrolliert die Einhaltung der Code-Richtlinien.
- ~~Dokumentator~~ **entfällt** (Janis, 07.11.2026): Der Manager weiß ohnehin über alles Bescheid und hält nach jeder freigegebenen Änderung knapp fest, was geändert wurde, wie es funktioniert und wie das Projekt aufgebaut ist (siehe „Manager-Tab“).
- Konfiguration pro Rolle: Testtiefe und Testumfang (Tester), Richtlinien (Prüfer), Projektkontext für alle (wie eine CLAUDE.md).
- Modell pro Rolle einstellbar, Vorschlag: Programmierer und Tester auf Sonnet, Prüfer und Chef bei Bedarf auf Opus (Doku-Arbeit des Chefs bei Bedarf auf Haiku). Standard ist Sonnet, damit das Kontingent lange reicht.
- Pro Agent ein Fenster mit Live-Status und technischen Daten.

### Manager-Tab (Entwurf, Janis, 07.11.2026; noch nicht gebaut, Gestaltung in DESIGN.md vor dem Bau)

Der Tab „Manager“ der Projektseite ist die Schaltzentrale des Projekts. Von Janis festgelegt:
- **Manager-Chat:** ein eigenes Fenster im Tab, in dem man direkt mit dem Manager schreibt. Er berät im Projekt auch über das Programmieren hinaus (z. B. Hardware) und hilft beim einfachen Dokumentieren.
- **Dokumente und Dateien:** Im Tab verwaltet man die Projektdateien selbst, lädt eigene Dateien hoch (z. B. Bilder) und legt weiteres ab, was in einem Projekt anfällt (das ist das Modul „Dateiablage“ aus der Reihenfolge, Abschnitt 8).
- **Aufgaben verteilen:** Der Manager verteilt die Aufgaben sinnvoll und geht dabei aktiv auf die anderen Agenten zu. Technisch bleibt es bei der Regel, dass Agenten nicht direkt miteinander sprechen: Der Manager liefert Zuteilung und Aufträge als Daten, der Hub stößt die Läufe der Rollen an (Zustandsautomat `workflow.py`).
- **Internet für alle Agenten:** Alle Rollen dürfen ins Internet, **in den besprochenen Grenzen**: nur über den `egress`-Proxy, nie ins Heimnetz, Geräte nur über Geräteliste und Vermittler (siehe „Geräteliste und Netzwege“). Läuft Code im selben Lauf, geht Web nur zu einer Liste von Seiten (PyPI, npm, GitHub, Dokumentation), damit ein Programm das lesbare Claude-Login nicht an eine beliebige Adresse schicken kann. Der Chat mit Einzelfragen bleibt „Web oder Code“.
- **Einstellungen im Tab:** Projektname und Projektbeschreibung (und was sonst das Projekt betrifft).
- **Dashboard:** Der Manager wählt die wertvollen Infos aus, die auf der Titelseite (Dashboard, Kachel des Projekts) stehen: Status, nächste Schritte, offene Entscheidungen.
- **Geräte:** Hier werden die Geräte hinterlegt, an denen gearbeitet wird, samt Zugangsdaten (Geräteliste mit Hostname, Auflösung, Freigabe und SSH-Schlüssel im Tresor, siehe „Geräteliste und Netzwege“).

Ergänzungen von Claude, nicht entschieden:
- **Zugangsdaten sieht auch der Manager nie:** Er kennt Gerätenamen und Zweck, nicht die Daten. Zugangsdaten werden in der Oberfläche eingegeben, im Tresor gespeichert und nie wieder angezeigt (nur ersetzen oder löschen). Sie gehen durch keinen Chat und kein Prompt.
- **Uploads absichern:** Größenlimit pro Datei und je Projekt, erlaubte Dateitypen (zunächst Bilder, PDF, Text), Ablage außerhalb des Web-Ordners, Auslieferung nur nach Besitzprüfung mit festem Inhaltstyp und `nosniff`, Fremdes ist 404, Fall in `test_isolation.py`. Der Speicherplatz auf dem Pi ist begrenzt; die Ablage ist ein Kandidat für die externe Platte.
- **Bilder für die Agenten:** Hochgeladene Bilder darf der Manager sehen (Claude kann Bilder lesen) und anderen Rollen als Eingabe (nur lesend) in den Arbeitsordner legen.
- **Projektbeschreibung als Kontext:** Name, Beschreibung und die Notizen des Managers werden jedem Agentenlauf als Projektkontext mitgegeben (Entsprechung der CLAUDE.md je Projekt); der Chat hat sonst kein Gedächtnis über Fragen hinweg.
- **Vorschläge statt eigener Änderungen:** Was der Manager im Chat vorschlägt (Board-Punkte, Dokumententwürfe, neue Beschreibung), nimmt der Nutzer an oder lehnt es ab, wie bei den Vorschlägen der Agenten.
- **Hardware nur beraten:** Der Manager schaltet oder testet nie Hardware am Fahrzeug (Pflicht aus CLAUDE.md).
- **Ein Laufplatz:** Der Chat teilt sich den einen Laufplatz des Pi (`MAX_RUNNING = 1`) mit den Agentenläufen und kann warten. Verlauf je Projekt mit Löschknopf wie im Einzelfragen-Fenster.
Nachtrag, von Janis festgelegt (07.11.2026, später am Abend):
- **Einzelfragen-Fenster entfällt.** Es wird entfernt, sobald der Manager-Chat gebaut ist (bis dahin bleibt es). Der Manager-Chat ist ausdrücklich ein **Beratungs-Chat** für das Projekt: Der Manager sieht nicht nur die Programmier-To-Dos, sondern auch, was mit Hardware passiert, und kann sagen, ob etwas sinnvoll ist und wie man es umsetzt. Im Tab ist das Fenster größer als der alte Chat, damit das Schreiben angenehm ist.
- **To-Dos, die keine Software sind, kommen nicht aufs Board** (Janis, 07.11.2026): Das Board bleibt der Software vorbehalten. Hardware, Besorgungen und andere physische Aufgaben, auch die Hardware-Checklisten des Testers, liegen beim Manager (im Manager-Tab), der sie mitführt und dazu berät. Das ist Teil der Koexistenz: Der Tab ist dafür da, das Projekt zu managen, und das tut Janis mit.
- **Der Manager pflegt den Stand und legt ihn in Git ab.** Er übernimmt nicht die Arbeit von Programmierer, Tester und Prüfer, sondern nimmt deren Rückmeldungen auf und führt damit die Dokumentation und den Projektstand nach. Er hält Aufgaben und Dokumente selbst fest und schiebt sie ins Git. Umsetzung als Vorschlag, weil es zwei bestehende Regeln berührt: (a) Der Agent bekommt weiterhin **keinen Push-Zugang**, der Hub committet und pusht in seinem Namen (wie beim Programmierer, KONZEPT-AGENTEN.md 6a). (b) Der Manager schreibt nur in einen Bereich für Projektdokumente und Aufgaben (z. B. `docs/` oder `.agent-hub/` im Projekt), nie in den Code; so umgeht er die Freigabe von Code-Änderungen nicht. Entschieden (Janis): Die Rolle Dokumentator entfällt, der Manager übernimmt auch die Doku nach einer Freigabe.
- **Janis und Manager nebeneinander (Koexistenz):** Der Tab ist zugleich Werkzeug für Janis (Geräte, SSH-Schlüssel, Einstellungen, Dateien) und Arbeitsplatz des Managers (Chat, Status, Aufgabenverteilung). **Geräte und SSH-Schlüssel verwaltet nur der Mensch; die KI bekommt sie nie.** Schlüssel liegen **verschlüsselt auf dem Pi** und werden nur vom Vermittler beim Verbinden entschlüsselt. Umsetzung als Vorschlag: der Hauptschlüssel steht in der `.env` (nicht im Backup und nicht im Git), die Verschlüsselung braucht eine Bibliothek (Python-Standardbibliothek hat keine; z. B. `cryptography`, wird beim Bau genannt und begründet). Ehrlich begrenzt: Wer die `.env` und die Datenbank gemeinsam hat (Pi-Zugriff), kann entschlüsseln; geschützt sind Backups und eine gestohlene SD-Karte nur, solange die `.env` nicht mit liegt.
- **Statusmeldung des Managers:** Der Manager schreibt in regelmäßigen Abständen und nach wichtigen Ereignissen einen kurzen Status: was zuletzt passiert ist, wie es aktuell läuft, ob es Probleme gibt, was wichtig ist oder zu besprechen wäre. Dazu eine **Ampel in drei Stufen**: läuft; Probleme, aber beherrschbar; Eingreifen nötig. Die Meldung erscheint auf der Kachel und im Tab.
- **Projektkachel im Dashboard (Janis):** Der **Projekttitel steht ganz oben**. Darunter die aktuellen News des Managers (Kurzfassung des Geschehens), der Stand der Aufträge (Anzahl Bugs, kleine Updates, Major Updates) und die Statusampel. Vorschläge von Claude: Verbrauch (siehe unten), Zahl der Punkte, die auf Janis warten (siehe „Wartet auf dich“), Zeitpunkt der letzten Aktivität.
- **Eingriffstiefe des Managers (Einstellung im Tab, drei Stufen):** (1) **Vollautomatisch:** der Manager wählt immer die bestmögliche Lösung. (2) **Rückfrage bei großen Entscheidungen.** (3) **Rückfrage auch bei kleinen Dingen.** Wichtig (Janis): Die Stufe ist kein starrer Schalter nach Art von Claude Code. Der Manager entscheidet **fallweise selbst**, ob er fragen muss: Lässt sich die Antwort aus Dateien, Notizen oder dem bisherigen Stand ableiten, trifft er sie selbst und vermerkt es; nur wenn sie nicht ableitbar ist und nach der Stufe zählt, fragt er. Nicht zu verwechseln mit der Strenge des Testers (locker, normal, streng) und der Strenge des Chefs bei Tests; die Namen werden im Design klar getrennt.
- **„Wartet auf dich“ (Fenster für Entscheidungen und Eingriffe):** Eine Liste der Punkte, bei denen etwas auf Janis wartet (Fragen des Managers, Freigaben, Eskalationen nach drei Durchläufen, Hardware-Checklisten). Die betroffene Aufgabe wartet, der Rest läuft weiter. Janis dachte an den Programmierer-Tab, war aber unsicher. **Vorschlag:** die Station „Für dich“ der Projektseite ist genau dafür gedacht (sie sammelt schon, was Janis tun muss); dazu ein Zähler an der Kachel und im Manager-Tab. Ort noch offen.
- **Die Tabs Programmierer, Tester und Prüfer bleiben wie geplant,** auch wenn ihr Inhalt noch nicht feststeht (Janis, 07.11.2026). Gefüllt werden sie später, zum Beispiel mit Live-Status, Läufen, Berichten und Verbrauch der jeweiligen Rolle.
- **Verbrauch (Claude darf frei entwerfen, für Janis nebensächlich):** Vorschlag: Der Hub zählt die Token aus den `usage`-Angaben jedes Laufs und Chat-Beitrags (je Projekt, Rolle und Tag; Rechnung nur für die Anzeige, nicht für Abrechnung). Auf der Kachel eine kleine Zahl oder ein schmaler Balken „heute / diese Woche“, im Manager-Tab die Aufteilung nach Rolle und Modell. Janis: Der Verbrauch lässt sich aus der Ausgabe der Kommandozeile lesen; für die **verbleibenden Token gibt es keine auslesbare Schnittstelle**, sie müssen **geschätzt beziehungsweise berechnet** werden (z. B. aus dem gezählten Verbrauch und einem vom Nutzer eingestellten Kontingent). Die Anzeige kennzeichnet den Rest darum als Schätzung. Neue Tabelle für die Zählung kommt beim Bau (Schema über `db.py`, Backup davor).
- **Regelmäßige Prüfungen (Janis, 07.11.2026):** Kleine wiederkehrende Aufgaben wie Code prüfen, auf Sicherheit prüfen, Standards einhalten, professionell geschriebener Code und das Entfernen veralteter oder unnötig komplizierter Stellen, die sich mit der Zeit erledigt haben, gehören dem Manager. Sie sind To-Dos, aber **keine Board-Punkte**, weil sie weder Bugs noch Updates sind.
- **Aufbau der Seite (Janis, 07.11.2026):** Ein Klick auf „Manager“ links blendet das Board aus, die Stationen links bleiben, im Hauptfenster erscheint der Manager-Tab. Aufteilung überlässt Janis Claude (sinngemäß, kompakt, schön). Reicht der Platz nicht, käme eine zweite Seite wie beim siebten Projekt; ein eigenes Menü nur für den Manager passt nicht zum Designziel, dass man von oben nach unten alles durchgehen kann. **Erster Stand gebaut** (Branch `manager-tab`, siehe Änderungsprotokoll und DESIGN.md 10b).
- **Skizze von Janis (07.11.2026, umgesetzt am selben Abend):** Name und Beschreibung des Projekts im Drop-down am Stift neben dem Titel; Status klein links oben, Geräte als hohe Spalte darunter; Dateien füllen dynamisch die Mitte; der Manager-Chat sitzt rechts groß, wo bisher das Chatfenster war, darunter „Wartet auf dich“; das alte Einzelfragen-Fenster ist durchgestrichen. Claudes Deutung (Skizze nicht eindeutig): Pfeile von „Wartet auf dich“ nach rechts unten und vom Manager-Chat nach rechts oben gelesen als Tausch an den rechten Rand; „Dateien dynamisch irgendwo hier“ als freier Platz in der Mitte; das durchgestrichene Chatfenster in der Manager-Ansicht ausgeblendet, im Board vorerst noch da, weil der Manager-Chat noch nicht gebaut ist. Janis korrigiert, falls anders gemeint.
- **Gestaltung:** keine feste Vorgabe, Janis überlässt Claude den Entwurf und passt später an. Wichtig ist, dass am Ende alles oben Genannte vorhanden ist. Der Entwurf kommt vor dem Bau in DESIGN.md.

### Ablauf

1. Programmierer nimmt einen Punkt, arbeitet im Branch.
2. Tester prüft. Bei Fehlern zurück zum Programmierer.
3. Prüfer kontrolliert die Richtlinien. Bei Einwänden zurück zum Programmierer, danach wieder Tester.
4. Maximal 3 Durchläufe und ein Zeitlimit pro Aufgabe, danach geht der Punkt an Janis.
5. Janis gibt frei, als weiteres Glied der Kette: per Klick auf vorgefertigte Aussagen plus Freitextfeld (z. B. bei Fehlerbeschreibungen), Berichte lassen sich vorausfüllen. Danach wird der Branch in die Produktivversion übernommen.
6. Der Manager aktualisiert Dokumentation und Projektstand (früher Dokumentator, entfallen am 07.11.2026).

### Dateiablage

- Pro Projekt: Bilder, Dokumente, Webfunde.
- Inhalte gelten für Agenten als Daten, nie als Anweisung (Schutz vor Prompt-Injection).

## 6. Sicherheit und Datensicherung

- Keine offenen Ports, Zugriff nur über Tunnel.
- Passwörter nur gehasht, Zwei-Faktor-Anmeldung, Begrenzung falscher Anmeldeversuche.
- Sitzungen und Reset-Links stehen in der Datenbank nur als SHA-256-Hash, nie im Klartext: Eine Kopie der Datenbank oder ein Backup enthält keine nutzbare Anmeldung. Ein neues Passwort beendet alle anderen Sitzungen und macht offene Reset-Links ungültig. Reset-Mails sind pro IP begrenzt (wie falsche Passwörter, eigener Zähler) und pro Konto auf eine Mail je 60 Sekunden.
- Mandantentrennung: Jede Abfrage nach Projekten und Board-Punkten hängt an `user_id` (Punkte über ihr Projekt), ein fremder Zugriff liefert „nicht gefunden“ (404) oder „nichts getan“. `tests/test_isolation.py` und der HTTP-Test mit zwei Konten prüfen das. Neue Datenfunktionen übernehmen diese Regel von Anfang an (auch solche für Agenten).
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

- Tester, Prüfer, Wiederholungen mit Limit, Doku-Schritt (durch den Manager).
- Agentenfenster und Konfiguration pro Rolle.
- Vorschläge von Claude mit Akzeptieren und Ablehnen.

### Phase 4 – Teilen und Feinschliff

- Docker-Compose-Paket und Installationsanleitung für Freunde.
- Benachrichtigungen aufs Handy bei Freigabe oder Problemen.
- Weitere KI-Anbieter als eigene Anmeldung.

## 8. Stand der Umsetzung (07.11.2026)

Phase 0 und der Großteil von Phase 1 sind erledigt und laufen live unter `https://hub.janis-home.de`. Dazu kamen am 07.11.2026 die Benutzerverwaltung und der E-Mail-Versand (Verlauf: Abschnitt 12).

**Fertig:** Pi eingerichtet (Raspberry Pi OS Lite 64-Bit, Docker, Compose, SSH mit Schlüssel); Login mit Benutzerkonten und Sperre nach falschen Passwörtern; Dashboard mit Kacheln, Seiten, Drag and Drop, zweistufigem Löschen; Projektseite mit Kanban-Board und Papierkorb; Einstellungen (Nutzername, Sprache, eigene Auswahlliste); Deutsch/Englisch; Hell/Dunkel (Wahl wird auch am Konto gemerkt); Cloudflare Tunnel mit HTTPS; Benutzerverwaltung (Owner, Admin, Nutzer, Einladung per Mail, Zurücksetzen, Löschen, Owner-Übergabe); Passwort ändern und „Passwort vergessen“ per Mail über Resend, mit HTML-Mails in Hell und Dunkel; Sitzungen und Links nur als Hash; Mandantentrennung durch Tests belegt; Claude Code auf dem Pi angemeldet (Runner im alten Compose-Ordner, noch nicht an die Website angebunden).

**Noch Platzhalter in der Oberfläche:** Claude/ChatGPT verknüpfen, Token-Anzeige, Stationen Agenten/Dateiablage/Dokumentation.

**Tests (Stand 07.11.2026):** 141 Unit-Tests (`web/tests/`, alle grün) und der HTTP-Test mit zwei Konten (alle Prüfungen grün). Nicht geprüft: Aussehen der Mails in echten Mailprogrammen, Berührung am echten Handy, gefühlte Flüssigkeit der Bewegung (Abschnitt 9, „Tests“).

### Aufbau des Codes

Repo `JanisWal/agent-hub` (privat), Branch `main` = Produktiv, ein Branch je Aufgabe. Nur drei Abhängigkeiten: `fastapi`, `uvicorn`, `python-multipart`. Code, Kommentare und Dateinamen sind englisch, Oberfläche und Doku deutsch. Die Oberfläche entsteht serverseitig aus Textvorlagen, ohne Framework.

```
compose.yml                  web-Dienst (127.0.0.1:8000, Daten in ./data, Netz „web“ für den Tunnel)
web/Dockerfile               python:3.13-slim, startet uvicorn app.main:app
web/requirements.txt         festgenagelt: fastapi 0.162.0, uvicorn 0.54.0, python-multipart 0.0.33
web/app/
  main.py                    FastAPI-App, Sicherheits-Header, Fehlerumleitungen, /health
  deps.py                    Cookie-Einstellungen, Anmeldeprüfung (page_user, api_user), Antwort-Helfer
  routes/auth.py             /login, /logout, /settings
  routes/projects.py         /, /projects, /projects/move, /projects/{id}, /projects/{id}/delete
  routes/board.py            Punkte anlegen, umbenennen, ordnen, annehmen, verwerfen, Papierkorb
  routes/accounts.py         /users (Benutzerverwaltung), /password
  routes/resets.py           /forgot, /reset/{token} (Passwort vergessen)
  db.py                      SQLite-Verbindung, Schema, Migrationen (einmalig, nur für alte Datenbanken; schließt Verbindungen sicher)
  users.py  projects.py  board.py   Daten und Regeln (ohne HTTP)
  throttle.py                Sperre nach zu vielen falschen Passwörtern (pro IP, SQLite)
  mail.py                    Mailversand über die Resend-API (`send_mail`), nur Standardbibliothek
  mailtext.py                Mails mit Knopf (Reset, Einladung): Text und HTML, Farbstile hell/dunkel
  resets.py                  Reset-Token (Hash in SQLite, 1 Stunde, einmalig)
  claude_link.py             Claude-Verbindung pro Nutzer (Zustand, Ordner `config_dir`, Anmelde-Link), keine Token in der Datenbank
  workflow.py                Kette der Agenten als reine Zustandsmaschine (Stufen, Rückläufe, Limits)
  agents.py                  Aufgaben, Läufe, Einstellungen pro Nutzer, `claim_next`/`finish_run` für den Runner
  routes/runner.py           Schnittstelle des Runners (`/runner/...`), nur mit Token und nie durch den Tunnel
  routes/claude.py           `/claude/{status,connect,code,disconnect}`: Verknüpfen in der Schublade (nur der eigene Nutzer)
  static/claude.js           Dialog „Claude verknüpfen“ (zeigt Schritte, fragt den Zustand ab, keine Texte im Skript)
runner/                      launcher.py (Container je Lauf und je Anmeldung, Befehle aus fester Vorlage, Ergebnis lesen), login.py (Anmeldung über Pseudo-Terminal),
                             runner.py (Schleife: Anmeldungen und Löschen der Claude-Ordner), Dockerfile (Image `agent-hub-agent`), Dockerfile.runner (Image `agent-hub-hub-runner`), Tests
  userspage.py               HTML von /users und /password
  resetpages.py              HTML von /forgot und /reset/{token}
  layout.py                  Seitenhülle und Vorlagen-Ersetzung fill(): %NAME% = fertiger Wert, %t.schluessel% = übersetzter Text
  ui.py                      Login-Seite, Einstellungs-Schublade, angemeldeter Seitenrahmen
  dashboard.py  projectpage.py   HTML von Startseite und Projektseite
  icons.py                   alle SVG-Symbole an einer Stelle
  i18n.py                    alle Texte in Deutsch und Englisch (ein Test prüft Gleichstand)
  create_admin.py            python -m app.create_admin
  static/app.css  dashboard.css  project.css  users.css   Gestaltung (Werte siehe DESIGN.md)
  static/core.js             Theme, Formularprüfung, Schublade, Dialog-Schließen, window.AgentHub.reload
  static/motion.js           Federn und FLIP;  sortable.js: Ziehen zum Ordnen
  static/dashboard.js        Begrüßung, Dialoge;  pages.js: Seitenband, Seitenanzeige, Kachel-Ziehen;  board.js: Board;  users.js: Benutzerverwaltung
web/tests/                   Unit-Tests (test_users, test_accounts, test_resets, test_isolation, test_db_upgrade, test_throttle, test_projects, test_board, test_pages, test_static),
                             integration_http.py (End-to-End über HTTP, mit zweitem Konto) und preview_mail.py (schreibt die Mails als HTML-Dateien, kein Test)
```

**Schnittstellen für später:** Jede Route hängt an einem eigenen Router (`routes/`), neue Bereiche (Agenten, Dateiablage, Tresor) kommen als weiteres Modul plus Router dazu, ohne `main.py` umzubauen. Die Anmeldeprüfung ist eine Abhängigkeit (`page_user` für Seiten, `api_user` für fetch-Aufrufe), eine Rollenprüfung lässt sich dort ergänzen. Neue Seiten bauen auf `ui.logged_in_page()` auf, neue Texte kommen in `i18n.py` in beide Sprachen, neue Symbole in `icons.py`. Claude-Vorschläge legt der spätere Agenten-Code mit `board.create_suggestion(user_id, project_id, kind, title)` an.

### Datenmodell (SQLite, `/data/hub.db`)

- `users`: id, email (eindeutig), password_hash (scrypt), role (`owner`/`admin`/`user`, höchstens ein `owner` durch den Teilindex `users_one_owner`), must_change_password, theme (`light`/`dark`, zuletzt gesehener Stil, für Mails), display_name, language (`de`/`en`), had_project, created_at.
- `sessions`: token_hash (SHA-256 des Cookie-Werts, nie der Wert selbst), user_id, expires_at (14 Tage). Cookie `session`: HttpOnly, SameSite=Lax, Secure über `HUB_SECURE_COOKIE=1`.
- `projects`: id, user_id, name (höchstens 60), page, position. Sechs Kacheln pro Seite; eine volle Seite schiebt ihr letztes Projekt auf die nächste (`projects.move`). Seiten ohne Projekte gibt es nicht. Löschen ist endgültig und verlangt das Passwort.
- `board_items`: id, project_id, kind (`bug`/`minor`/`major`), title (höchstens 200), source (`user`/`claude`), status (`open`/`proposed`/`trash`), position. Von Hand angelegte Punkte sind `open` und stehen oben, Vorschläge von Claude sind `proposed` und stehen unten. Jeder Zugriff prüft, dass das Projekt dem Nutzer gehört.
- `login_attempts`: ip (Schlüssel), failures, window_start, locked_until. Zählt falsche Passwörter pro IP (hinter dem Tunnel aus `CF-Connecting-IP`). Zehn Fehlversuche innerhalb von 30 Minuten sperren die IP für eine Stunde, dann antworten Anmeldung und Projekt-Löschen mit 429 (auch bei richtigem Passwort). Ein richtiges Passwort setzt den Zähler nicht zurück, er läuft mit dem Zeitfenster ab. Gezählt wird nie pro E-Mail, damit niemand den Owner aussperren kann.
- `password_resets`: token_hash (Schlüssel, SHA-256 des Tokens, der Token selbst steht nur in der Mail), user_id, created_at, expires_at. Gültig 1 Stunde, wird beim Benutzen gelöscht. Eine neue Anfrage ersetzt die alte; für dasselbe Konto geht frühestens nach 60 Sekunden eine neue Mail raus. Löscht man den Nutzer, verschwinden seine Tokens (Cascade).
- `claude_connections`, `agent_settings`, `agent_tasks`, `agent_runs`: Claude-Verbindung, Einstellungen, Aufgaben und Läufe der Agenten (Felder in `KONZEPT-AGENTEN.md`, Abschnitt 4). Alle hängen über Cascade am Nutzer bzw. Projekt.
- Schemaänderungen laufen über `NEW_COLUMNS` in `db.py` (Spalten werden beim ersten Datenbankzugriff nach dem Start ergänzt). Umwandlungen alter Daten (Rollen aus dem früheren `is_admin`, Seiten der Projekte, Sitzungs-Hashes) laufen **einmalig** und nur für alte Datenbanken, nie bei jedem Start; vor dem Deploy einer Migration wird sie an einer Kopie der echten Datenbank geprobt. Vor jeder Änderung an Daten ein Backup.

### Routen

| Methode, Pfad | Zweck | Ohne Login |
|---|---|---|
| GET/POST `/login`, POST `/logout` | Anmelden (401 bei falschen Daten), Abmelden | offen |
| GET `/`, GET `/projects/{id}` | Dashboard, Projektseite | Umleitung auf `/login` |
| POST `/settings`, `/projects`, `/projects/{id}/items`, `/items/{id}` | Formulare, antworten mit Umleitung | Umleitung auf `/login` |
| POST `/theme` (Wert `light`/`dark`, sonst 400), `/projects/move`, `/projects/{id}/delete`, `/projects/{id}/trash/empty`, `/items/reorder`, `/items/{id}/{accept,reject,discard,restore,delete}` | fetch-Aufrufe, antworten mit `{"ok": …}` | 401 |
| GET `/users`, POST `/users/add`, `/users/{id}/reset`, `/users/{id}/delete`, `/users/{id}/owner`, `/users/{id}/admin` | Benutzerverwaltung für Owner und Admins (`/users/add` nimmt nur die E-Mail-Adresse und lädt per Mail ein, bei Versandfehler 502 und das Konto wird wieder entfernt; `/users` sonst 404, die POST-Aufrufe 403; Zurücksetzen, Löschen und Owner-Übergabe verlangen das eigene Passwort; `admin` und `owner` nur für den Owner) | Umleitung auf `/login` bzw. 401 |
| GET/POST `/password` | eigenes Passwort ändern (nach einem Startpasswort Pflicht, bis dahin ist nur diese Seite erreichbar) | Umleitung auf `/login` |
| GET/POST `/forgot` | E-Mail-Adresse eingeben, Link per Mail anfordern. Antwort immer gleich, ob es das Konto gibt oder nicht (die Mail geht nach der Antwort raus, auch die Dauer verrät nichts); ohne `@` 400; pro IP begrenzt (10 Anfragen in 30 Minuten sperren die IP für eine Stunde, dann 429) | offen |
| GET/POST `/reset/{token}` | Neues Passwort mit dem Link aus der Mail festlegen (Regeln wie bei `/password`); unbekannter, abgelaufener oder benutzter Link: 400. Danach enden alle Sitzungen, ein Startpasswort-Zwang entfällt, Umleitung auf `/login` | offen |
| POST `/runner/claim`, `/runner/runs/{id}/finish`, GET `/runner/logins`, POST `/runner/logins/{user_id}/{url,code,done,expired}` | Schnittstelle des Runners (Branch `agent-core`, Einzelheiten in `KONZEPT-AGENTEN.md` Abschnitt 5). Token im Header `Authorization: Bearer`, Hub kennt nur `HUB_RUNNER_TOKEN_HASH`; Anfragen durch den Tunnel und ohne gesetzten Hash: 404, falsches Token: 401, gesperrte IP: 429 | nur Runner |
| GET `/claude/status`, POST `/claude/connect`, `/claude/code`, `/claude/disconnect` | Claude-Verknüpfung des angemeldeten Nutzers (Branch `agent-core`); `code` gibt den Code einmalig an den Runner weiter und speichert ihn nie | 401 |
| GET `/runner/wipes`, POST `/runner/wipes/{user_id}/done` | Runner löscht den Claude-Ordner eines getrennten Nutzers (wie die anderen `/runner/...`-Routen) | nur Runner |
| GET `/health` | Lebenszeichen | offen |

`/docs`, `/redoc` und `/openapi.json` sind abgeschaltet. Alle Antworten tragen `X-Content-Type-Options`, `X-Frame-Options: SAMEORIGIN` und `Referrer-Policy`; Seiten (nicht `/static`) zusätzlich `Cache-Control: no-store`, bei HTTPS `Strict-Transport-Security`.

## 9. Betrieb

### Pi, Zugriff und Ordner

- Gerät im Heimnetz: `admin@home.local`, Anmeldung per SSH-Schlüssel (`~/.ssh/id_agenthub`, ohne Passphrase, auf dem Pi in `authorized_keys` mit Kommentar `agent-hub-claude`). `admin` ist in der Gruppe `docker`. Passwörter tippt Janis selbst, Claude kennt und speichert keine.
- Produktiv läuft der Klon `/opt/agent-hub/workspaces/agent-hub` (`main`, entspricht GitHub). Daten liegen in dessen Ordner `data/`. Der Tunnel liegt getrennt unter `/home/admin/cloudflared` (Token in dessen `.env`, nie im Git).
- Die Seite erreicht der Tunnel über das Docker-Netz `web` (Alias `agent-hub`, Port 8000). Cloudflare leitet `hub.janis-home.de` an `http://agent-hub:8000`. Port 8000 ist nur auf `127.0.0.1` des Pi offen, von außen und im LAN geschlossen.
- GitHub: Deploy-Key auf dem Pi, Push von dort.
- **E-Mail-Versand (Resend, Absender `Agent-Hub <noreply@janis-home.de>`):** Domain `janis-home.de` wird bei Resend verifiziert (DNS-Einträge in Cloudflare, „Nur DNS“, nicht über den Proxy). Die Einstellungen stehen in der `.env` im Klon-Ordner (nie im Git, nur für `admin` lesbar halten): `RESEND_API_KEY` (Schlüssel mit „Sending access“ nur für diese Domain), `MAIL_FROM` und `HUB_BASE_URL=https://hub.janis-home.de`. `compose.yml` reicht sie an `web` weiter; fehlen sie, passiert beim Versand nichts außer einer Logzeile (`docker compose logs web`). Der Link in der Mail kommt aus `HUB_BASE_URL`, nie aus der Anfrage (Schutz vor gefälschtem Host-Header). Nach Änderung der `.env`: `docker compose up -d web`.

### Arbeitsablauf vom PC aus (so wurde bisher gearbeitet)

Auf dem Windows-PC ist kein Git installiert und das Repo liegt nur auf dem Pi und bei GitHub. Claude arbeitet deshalb so (Janis muss dafür nichts tun):

1. **Bearbeiten lokal:** Dateien aus dem Klon per `scp` in einen Arbeitsordner (Scratchpad der Sitzung) holen, dort mit den Editier-Werkzeugen ändern (UTF-8 ohne BOM, Zeilenenden `\n`).
2. **Auf den Pi:** geänderte Dateien per `scp` in den Klon `/opt/agent-hub/workspaces/agent-hub` legen, vorher `git switch -c <thema>` dort (ein Branch je Thema).
3. **Testen im Container**, ohne den laufenden Dienst anzufassen (Abschnitt „Tests“), neuer Code über zusätzliches `-v "$PWD/web/app:/app/app"`.
4. **Committen** (ein Thema pro Commit, kurze englische Nachricht), `git switch main`, `git merge --no-ff <thema>`, `git push origin main`.
5. **Sichern und ausrollen:** Datenbank nach `/opt/agent-hub/backups/hub-<datum>-before-<thema>.db` kopieren, `docker compose up -d --build web`, dann `/health` und `https://hub.janis-home.de/login` prüfen und bei Datenbankänderungen die Tabellen ansehen.
6. **Schritte als Skriptdatei:** längere Abläufe als `.sh`-Datei per `scp` hochladen und mit `bash` ausführen (keine verschachtelten Anführungszeichen für `ssh` aus PowerShell). Skripte und Vorschau-Dateien liegen im Scratchpad, nicht im Projekt.
7. **Keine Ports für Vorschauen öffnen** (z. B. `http.server` auf dem Pi): Die Sicherheitsprüfung der Sitzung lehnt das ab. Mail-Vorschauen stattdessen als Datei erzeugen und im eingebauten Browser der Claude-App öffnen (dort nur ansehen, kein Bedienen).
8. **Zugangsdaten** (`.env`, Schlüssel) werden nie ausgegeben; Prüfungen zeigen nur Namen und Längen, nie Werte.

### Update-Ablauf

1. Backup der Datenbank: `cp data/hub.db /opt/agent-hub/backups/hub-$(date +%F).db` (im Klon-Ordner, Dienst darf laufen).
2. Änderungen auf einem Branch entwickeln und testen, dann nach `main` mergen und pushen.
3. Auf dem Pi im Klon-Ordner: `git pull`, dann `docker compose up -d --build web`.
4. Prüfen: `curl -s http://127.0.0.1:8000/health` und `https://hub.janis-home.de/login`.
5. Zurück: `git revert <Commit>`, erneut bauen; Daten notfalls aus dem Backup.

### Tests

- **Unit-Tests** (laufen im Container, ohne den Dienst anzufassen), im Klon-Ordner (für Code, der noch nicht im Image steckt, zusätzlich `-v "$PWD/web/app:/app/app"` angeben): `docker compose run --rm --no-deps -v "$PWD/web/tests:/app/tests" web python -W ignore -m unittest discover -s tests -t .`
- **Launcher-Tests** (Ordner `runner/`, brauchen zusätzlich dessen Einhängung): `docker compose run --rm --no-deps -v "$PWD/web/tests:/app/tests" -v "$PWD/web/app:/app/app" -v "$PWD/runner:/app/runner" web python -W ignore -m unittest runner.test_launcher`. Ein echter Lauf mit Anmeldung ist damit nicht geprüft.
- **HTTP-Test** gegen eine Wegwerf-Instanz mit eigener Datenbank und Testkonto, z. B. `docker run -d --name hub-test -p 8001:8000 -e HUB_DB=/tmp/test.db -e HUB_SECURE_COOKIE=0 agent-hub-web`, Testnutzer mit `users.create_user` anlegen, dann `python3 web/tests/integration_http.py http://127.0.0.1:8001 EMAIL PASSWORT [EMAIL2 PASSWORT2]` (mit einem zweiten normalen Konto prüft der Test zusätzlich, dass es nichts vom ersten sieht oder ändert). Bei HTTP muss `HUB_SECURE_COOKIE=0` stehen, sonst sendet der Client den Cookie nicht zurück. Nie mit dem echten Konto testen.
- **Mail-Vorschau:** `docker compose run --rm --no-deps -v "$PWD/web/tests:/app/tests" -v /tmp/mailprev:/out web python -W ignore tests/preview_mail.py /out` schreibt die Mails (Reset und Einladung, hell und dunkel) als HTML-Dateien; ansehen im Browser der Claude-App (Datei öffnen), ohne einen Port freizugeben. Das Aussehen in echten Mailprogrammen prüft nur Janis.
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

- Idee (07.11.2026): Projekte mit anderen Nutzern teilen. Noch nicht ausgearbeitet. Zu klären: Rechte (nur lesen oder mitarbeiten), wessen Claude-Konto die Agenten eines geteilten Projekts nutzen, und wie das zur Mandantentrennung passt (Besitzprüfung wird zu „Besitz oder freigegeben“, neue Fälle in `test_isolation.py`).
- Idee (07.11.2026, Janis): **Manager-Chat** im Tab „Manager“, ein Chat direkt mit dem Manager. Er berät im Projekt auch über das Programmieren hinaus (zum Beispiel Hardware) und hilft beim einfachen Dokumentieren. Ausgearbeitet im Abschnitt „Manager-Tab (Entwurf)“ bei den Agenten.
- Anbindung des Abos: Claude Code lässt sich auf dem Pi (Debian trixie, arm64) installieren und per Link und Code ohne Bildschirm anmelden (getestet 06.11.2026). Offen: Nutzungsbedingungen prüfen und ob die Anmeldung dauerhaft hält.
- Vorlagen für Janis’ Freigaben und die Tester-Checklisten: welche Klick-Aussagen, welche Felder.
- Domain `janis-home.de` ist im Einsatz (Subdomain `hub`); Registrar und Cloudflare-Konditionen bei Gelegenheit prüfen. Optional Cloudflare Access (Code per E-Mail) als zusätzliche Hürde vor der Seite (die Begrenzung der Anmeldeversuche ist inzwischen gebaut, Access wäre eine zweite Schicht).
- SSD kaufen (120–240 GB) und Umzug von der SD-Karte planen.
- E-Mail-Versand für Passwort-Reset: **entschieden, Resend** mit Absender `noreply@janis-home.de` (Betrieb siehe Abschnitt 9). Eigener Mailserver zu Hause schied aus (Privat-IPs landen im Spam oder auf Sperrlisten, Port 25 oft gesperrt). Offen: Tarifgrenzen von Resend im Blick behalten (die Mails sind pro IP und pro Konto begrenzt, eine Obergrenze für alle zusammen gibt es nicht); das Aussehen der Mails in echten Mailprogrammen ist ungeprüft.
- Wie viele Nutzer langfristig (bestimmt Leistung des Pi und Rechtekonzept).
- Arbeitsspeicher: Der Pi 4B hat nur 1 GB (905 MiB nutzbar), Claude Code verlangt laut Anleitung 4 GB. Erster Test am 07.11.2026: Claude Code (`claude -p`, Haiku) lief im Runner-Container mit hartem Limit von 480 MB ohne Swap zweimal fehlerfrei durch (je 11 s, Spitze mindestens 225 MiB, im Sekundentakt gemessen), danach waren weiter etwa 580 MiB frei und die Seite blieb erreichbar. Offen: lange Läufe, Sonnet, parallel laufende Tests und Git-Worktrees. Fällt er schlecht aus: Runner auf Mac oder PC (Variante B) oder Pi mit 4–8 GB (Variante C).
- Aufräumen auf dem Pi (löschen nur nach Janis’ Ja): alte Codekopie `/opt/agent-hub/web`, die alte `/opt/agent-hub/compose.yml` mit dem Runner (er teilt ein einziges Volume `agent-hub_claude-home` für die Claude-Anmeldung und wird durch die Lösung pro Nutzer ersetzt, Abschnitt 3) samt Ordner `runner/`, doppelte `docker-compose.yml` unter `/home/admin/cloudflared`, der leere Ordner `web/tests/tests` im Klon, und 21 lokale Branches im Klon, die alle schon in `main` gemergt sind (`git branch --merged main`).
- Offen für die Mails: Obergrenze für alle Reset- und Einladungsmails zusammen (Schutz des Resend-Kontingents), falls Missbrauch auftritt.
- Offen für die Anmeldung: Login-Seite auf Englisch (die Sprache ist vor der Anmeldung unbekannt), Zwei-Faktor-Anmeldung (steht in Abschnitt 6 als Ziel).
- Oberfläche: siehe DESIGN.md, Abschnitt „Noch offen“.

### Checkliste vor dem Livegang

- [x] Cloudflare Tunnel mit HTTPS eingerichtet, Port nur auf 127.0.0.1 gebunden
- [x] Cookie mit Secure-Merkmal, per Einstellung umschaltbar (`HUB_SECURE_COOKIE`)
- [x] Geheimnisse nur in .env, nicht im Git
- [x] Update-Ablauf festgelegt (Abschnitt 9)
- [x] Erster Admin angelegt, Login getestet
- [x] Sicherheits-Header gesetzt, API-Dokumentation abgeschaltet
- [x] Begrenzung falscher Anmeldeversuche: nur pro IP, 10 Fehlversuche in 30 Minuten sperren die IP für 1 Stunde (Anmeldung und Löschen gemeinsam, `throttle.py`)
- [x] Versionen von fastapi, uvicorn und python-multipart festgenagelt (`web/requirements.txt`; die übrigen Pakete, z. B. starlette, ergeben sich daraus)
- [x] Sitzungen und Reset-Links nur als Hash in der Datenbank, `.env` nur für `admin` lesbar (07.11.2026)
- [x] „Passwort vergessen“ pro IP begrenzt, pro Konto eine Mail je 60 Sekunden (07.11.2026)
- [x] Mandantentrennung geprüft und durch Tests belegt (`tests/test_isolation.py`, HTTP-Test mit zwei Konten, 07.11.2026)
- [ ] Web-Container läuft als eigener Benutzer ohne Sonderrechte (Datenordner-Rechte anpassen: Der Dienst läuft jetzt als root und schreibt in `data/`, die Rechte müssen zuerst passen, sonst kann er nicht mehr schreiben), mit Speicherlimit
- [ ] Gesundheitsprüfung über `/health` in compose eingetragen
- [ ] Content-Security-Policy (benötigt, dass das Theme-Skript im `<head>` ohne Inline-Code auskommt)
- [ ] Tägliches Backup (restic) läuft, Wiederherstellung einmal getestet
- [ ] System von SD-Karte auf SSD umgezogen
- [ ] Nur noch eine Codekopie (Doppelung /opt/agent-hub/web und Klon in workspaces aufgelöst)
- [ ] Mails in echten Mailprogrammen angesehen (Gmail, Apple Mail; hell und dunkel), Einladung an eine zweite Adresse und Owner-Übergabe mit einem Testkonto von Janis probiert
- [ ] Trennung der Claude-Konten gebaut und mit dem Isolationstest geprüft (Pflichtregeln in Abschnitt 3), bevor der erste Nutzer außer Janis Claude verbindet. **Stand 07.11.2026:** gebaut (Ordner, Launcher, Zustandsprüfung, Tests mit zwei Nutzern in `test_isolation.py`); der Isolationstest mit zwei echten Läufen steht mit der Runner-Schleife aus, bis dahin verbindet nur Janis.

## 12. Änderungsprotokoll

Neueste zuerst. Alle Einträge vom 07.11.2026; jeder Eintrag ist ein Branch, der in `main` gemergt wurde (`git log --no-merges 132f9cb..main` zeigt die Commits). Basis war die große Säuberung „Frontend: split CSS and JS per page, remove dead rules“ (`132f9cb`, davor `11b1b01` für das Backend).

| Branch | Was sich geändert hat |
|---|---|
| `manager-layout` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-manager-layout.db`) | Manager-Ansicht nach Janis’ Skizze umgebaut: drei Spalten (links Status und Geräte, Mitte Prüfungen und Dateien, rechts Manager-Chat über „Wartet auf dich“). Projektname und -beschreibung wandern aus der Kachel in ein **Drop-down am neuen Stift neben dem Titel** (`titlemenu.js`, `projectpage.title_html`), auf beiden Ansichten erreichbar. Das alte Einzelfragen-Fenster ist in der Manager-Ansicht ausgeblendet (bleibt im Board, bis der Manager-Chat steht). Keine Datenbankänderung. Auf Desktop und Handy im Browser geprüft; neue Tests für Spalten, Stift und Drop-down. Unsicher in der Skizze gedeutet: siehe Abschnitt Manager-Tab. |
| `manager-tab` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-manager-tab.db`) | Projektseite mit zwei Ansichten: Klick auf „Manager“ links blendet das Board aus (`stations.js`, Adresse `#board`/`#manager`), die Stationen bleiben. Manager-Ansicht (`managerpage.py`): Status und „Wartet auf dich“ (leer), angekündigte Kacheln Manager-Chat, Dateien, Geräte, Regelmäßige Prüfungen („Kommt später“), Einstellungen mit **Projektname und Projektbeschreibung** (neue Spalte `projects.description`, additiv über `db.py`, bestehende Projekte bekommen eine leere Beschreibung; `projects.update_details`, Route `POST /projects/{id}/settings`, fremde Projekte 404, Fall in `test_isolation.py`). Regelmäßige Prüfungen des Managers stehen nicht auf dem Board. Noch ohne KI. Auf Desktop- und Handybreite im Browser geprüft (Umschalten, Papierkorb aus dem Manager, Speichern-Knopf, keine Sprung-Bewegung beim Laden mit `#manager`). 238 Tests grün (vorher 232), Migration an einer Kopie der echten Datenbank geprobt. |
| `docs-no-documenter` (nur Doku, 07.11.2026) | Rolle Dokumentator entfällt, der Manager führt Doku und Projektstand nach (Doku-Schritt der Kette bleibt, nur der Ausführende wechselt). Hardware- und andere physische To-Dos und die Hardware-Checklisten des Testers kommen nicht aufs Board, sondern zum Manager; das Board bleibt der Software vorbehalten. Verbrauch: aus der Kommandozeile lesbar, Rest nur geschätzt. **Im Code noch offen:** `workflow.py` (Schritt `documenting`, Rolle `documenter`), `agents.py` und die Rolleneinstellungen; die Umstellung gehört in das Modul „Schleife des Runners“, weil noch kein Lauf den Schritt nutzt. |
| `docs-manager-details` (nur Doku, 07.11.2026) | Manager-Tab weiter festgelegt: Einzelfragen-Fenster entfällt mit dem Manager-Chat (Beratungs-Chat, größeres Fenster); Board kennt Punkte ohne Software; Manager führt Dokumentation und Projektstand nach und legt sie über den Hub in Git ab; Geräte und SSH-Schlüssel nur für den Menschen, verschlüsselt auf dem Pi; Statusmeldung mit Ampel; Projektkachel (Titel oben, News, Zahl der Bugs/kleinen/Major-Updates, Ampel); Eingriffstiefe in drei Stufen mit fallweiser Entscheidung des Managers; Fenster „Wartet auf dich“ (Ort offen, Vorschlag Station „Für dich“); Tabs Programmierer/Tester/Prüfer bleiben; Verbrauchsanzeige als Vorschlag. Nichts gebaut. |
| `docs-manager-tab` (nur Doku, 07.11.2026) | Manager-Tab als Entwurf festgehalten (Chat, Dokumente und Uploads, Aufgabenverteilung über den Hub, Einstellungen, Dashboard-Infos, Geräte mit Zugangsdaten). Entschieden mit Janis: **alle Agenten dürfen ins Internet** in den besprochenen Grenzen (nur über `egress`, nie Heimnetz; bei Code im selben Lauf nur Seitenliste). Ergänzungen von Claude als Vorschläge gekennzeichnet (Zugangsdaten nie für den Manager sichtbar, Upload-Absicherung, Projektbeschreibung als Kontext). Nichts gebaut. |
| `docs-mac-return-vpn` (nur Doku, 07.11.2026) | VPN-Technik entschieden (Claude geprüft, Vorgabe von Janis: kein offener Fritzbox-Port): Tailscale mit Zugriffsregeln, Headscale verworfen (läuft nicht hinter Cloudflare Tunnel, braucht UDP 3478), WireGuard mit offenem Port verworfen. Rückgabe der Mac-Ergebnisse ins Projekt festgelegt: Git-Bundle über den Hub (holen und zurückladen, nur der Branch der Aufgabe, Prüfung durch den Hub, danach normale Kette). Nichts gebaut. |
| `docs-devices-mac` (nur Doku, 07.11.2026) | Entschieden mit Janis: Mac-Knopf ohne zweite Anmeldung (Einmal-Ticket im Hintergrund); Heimnetz bleibt gesperrt, Geräte kommen über eine Geräteliste im Manager (Hostname, Auflösung durch den Hub, Freigabe, optional SSH-Schlüssel im Tresor, Zugriff nur über den Vermittler); Geräte in fremden Netzen per VPN, sternförmig mit Firewall-Regeln (Kollegen untereinander getrennt, Pi nur Port 22 zum Gerät, Gerät nicht ins Netz). Offen: Wahl der VPN-Technik wegen „keine offenen Ports“. Nichts gebaut. |
| `responsive-check` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-responsive-check.db`) | Projektseite auf allen Fenstergrößen geprüft (DESIGN.md 10b, „Bildschirmgrößen“): Auf dem Handy hat die Kopfleiste zwei Zeilen, damit der Projektname volle Breite behält (vorher 30 px bei 390 px Breite); Spalten und Stationen stapeln jetzt bis 1100 px statt 1000 px (bei 1024 px waren drei Spalten zu eng). Alle anderen Größen ohne Überlappung. 222 Tests grün. |
| `code-sandbox` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-code-sandbox.db`) | Chat mit drei Modi (nur antworten, Web, Code) und zwei Schaltern „Web“ und „Code“ über dem Eingabefeld; Code-Modus mit dem Werkzeug Bash und Python 3 im Image, ohne Internet. **Neues Netzwerk:** `agent-hub-agents` ist jetzt ein internes Docker-Netz ohne Route nach draußen; einziger Ausgang ist der neue Dienst `egress` (`runner/egress.py`, Filter-Proxy: Port 3128 nur öffentliche Hosts auf 443, Port 3129 nur Anthropic). Das schließt auch die Lücke, dass die Websuche das Heimnetz hätte erreichen können. Im Code-Modus ist das Login des Nutzers nur lesbar eingehängt. Agentenläufe und Anmeldungen laufen über den Proxy (Port 3129). Spalte `chat_messages.mode`. Codeblöcke und `Code` in Antworten. Echte Läufe auf dem Pi: Python rechnet, Zugriff ins Internet scheitert, Heimnetz und interne Adressen werden vom Proxy abgelehnt. 232 und 51 Tests grün. Neue Dateien: `runner/egress.py`, `runner/test_egress.py`. |
| `chat-web` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-chat-web.db`) | Der Chat bekommt Websuche und Seiten lesen als einzige Werkzeuge (höchstens 8 Schritte, Zeitlimit 200 s); Antworten zeigen fett und Links echt (nur aus DOM-Knoten, nur http/https); klare Meldung beim Erreichen des Schrittlimits; neuer Hinweistext im Chat. Mit dem Konto des Owners in einem echten Lauf mit dem Befehl des Launchers geprüft. Code-Sandbox bewusst noch nicht. 228 Tests und 37 Launcher-Tests grün. |
| `common-line` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-common-line.db`) | „Agent-Hub“ und der Zurück-Pfeil liegen auf derselben Linie wie die runden Knöpfe rechts (gemeinsamer Mittelpunkt `--line`, 34 px, Handy 30 px, niedrige Fenster 24 px), auf jeder Seite; der Projektname bleibt mittig in der höheren Leiste. 227 Tests grün. |
| `chat-final` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-chat-final.db`) | Chat-Fenster als fertige Fassung statt Testfenster: Titel „Claude“, ohne Plakette „Vorübergehend“ und ohne Testsatz, neuer Satz für Einzelfragen, Menütext „aus dem Chat“; Verlauf auf 100 Nachrichten je Nutzer begrenzt. Oberkante des Chats auf der Linie der Spalten (94 px, vorher 104 px), Unterkante schon gleich. Zahnrad mit Pfeil als Oval mit dem Rand der runden Knöpfe (38 px hoch, auf einer Linie mit ihnen). Texte und Kommentare mit „Test“ und „TEMPORARY“ entfernt. 226 Tests grün. |
| `project-layout-3` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-project-layout-3.db`) | Dritte Runde (DESIGN.md 10b): „Alle Projekte“ als runder Pfeil-Knopf neben der Marke (wie Archiv und Papierkorb); Spalten reichen bis ganz nach unten und enden auf derselben Linie wie das Chatfenster (96 px über dem Fensterrand), der Chat ragt nicht mehr in den Hell/Dunkel-Knopf; eigene Tooltips (kleines Glasschild statt Browser-Box, `core.js`). 221 Tests grün. |
| `project-layout-2` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-project-layout-2.db`) | Zweite Runde nach Janis’ Rückmeldung (DESIGN.md 10b): „Alle Projekte“ als Link neben der Marke in der Kopfleiste, größerer Projektname mit mehr Luft; Testchat als feste Leiste am rechten Rand (auf schmalen Bildschirmen per Knopf) statt unter dem Board; Stationen neu eckig, am linken Fensterrand und ohne Pfeile, aktiver Reiter als Rechteck, das herausstößt; eigene schlanke Bildlaufleiste. Tooltips bleiben Standard des Browsers (Janis: Kleinigkeit). 218 Tests grün. |
| `project-redesign` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-project-redesign.db`) | Projektseite nach Janis’ Skizze neu gestaltet (Einzelheiten DESIGN.md Abschnitt 10b): Projektname in der Kopfleiste bei 38,2 %, Archiv- und Papierkorb-Knopf links neben dem Zahnrad (fahren mit der Schublade, kein Zähler, Board wird überblendet), Board aus drei großen Spalten mit Zeilen und Glowlinie statt Blöcken, Übernehmen grün (`--go`) und Ablehnen rot, mehreckige Stationen im Zyklus Board, Manager, Programmierer, Tester, Prüfer, Für dich. Logik: neuer Status `archived` (erledigte Aufgabe der Agenten landet im Archiv statt gelöscht zu werden, `board.archive`, `restore` holt zurück); **Agenten-Bugs** (`create_suggestion` mit Spalte Bug) kommen ohne Freigabe direkt in die Bug-Spalte, nur Kleine und Major Updates warten auf Übernehmen oder Ablehnen. 214 Tests grün. |
| `claude-chat-test` (ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-chat-test.db`) | **Vorübergehendes** Testfenster „Claude testen“ unter dem Board der Projektseite: eine Frage an das eigene Claude, beantwortet vom Runner in einem Container (Haiku, ohne Werkzeuge, ohne Projektdateien, nur der Claude-Ordner des Nutzers). Neu: `chat.py`, `routes/chat.py`, `/runner/chat/...`, `chat.js`, Tabelle `chat_messages`; Link-Knopf „Bei Claude anmelden“ jetzt gestaltet wie ein Knopf. Ein verlorener Login lässt die Verbindung „Abgelaufen“ anzeigen. Zum Entfernen nach dem Test: diese Dateien, das Fenster in `projectpage.py`, die Runner-Funktionen `handle_chat`/`build_chat_command`/`parse_chat_output` und die Tabelle. |
| `agent-core` (gemergt und ausgerollt am 07.11.2026, Backup `hub-2026-11-07-before-agent-core.db`) | Grundstein der Agenten: `claude_link.py`, `workflow.py`, `agents.py`, vier neue Tabellen, Runner-Schnittstelle `routes/runner.py` (Token, nie durch den Tunnel), Launcher für einen Container je Lauf (`runner/`, Image `agent-hub-agent`, auf dem Pi mit dem echten Befehl geprüft), Konzept in `KONZEPT-AGENTEN.md`; 173 Hub-Tests und 11 Launcher-Tests grün. Dazu der Knopf „Verknüpfen“ in der Schublade (Dialog, grüner Zustand `--success`, `routes/claude.py`, `claude.js`), der Runner für Anmeldungen und das Löschen getrennter Ordner (`runner/runner.py`, `login.py`) und der Compose-Dienst `runner` (läuft; Ordner `/opt/agent-hub/claude` außerhalb von `data/`, Modus 0700, nur der Runner hängt ihn und den Docker-Socket ein; Token `RUNNER_TOKEN` und `HUB_RUNNER_TOKEN_HASH` in der `.env`). Live geprüft: `/runner/...` antwortet durch den Tunnel mit 404, im Netz mit falschem Token 401, der Runner erreicht den Hub mit seinem Token. Mit einem Wegwerf-Hub, Testkonto und echtem Anmelde-Container auf dem Pi geprüft (Link kommt an, falscher Code scheitert sauber); der Erfolgsweg mit echtem Code steht aus. Noch keine Runner-Schleife für Agentenläufe und kein Arbeitsordner je Aufgabe. Auf dem Pi neu: Images `agent-hub-agent` und `agent-hub-hub-runner`. Nebenwirkung: Der erste `docker compose build runner` hat dem alten Image `agent-hub-runner` kurz den Namen weggenommen; es wurde aus `/opt/agent-hub/runner/Dockerfile` neu gebaut (gleicher Inhalt, neuere Claude-Version), das Volume mit Janis’ Anmeldung blieb unberührt. |
| `review-cleanup` | Prüfung des Codes seit der Säuberung. Sitzungen nur noch als SHA-256-Hash (alle wurden einmal abgemeldet); Migrationen laufen einmalig statt bei jedem Start (vorher hätte ein Neustart einen herabgestuften Admin wieder befördert); Spalte `is_admin` entfernt (`role` genügt); Passwortwechsel in einer Transaktion und er macht offene Reset-Links ungültig; „Passwort vergessen“ pro IP begrenzt; `board.create_suggestion` prüft jetzt den Besitz (neue Signatur mit `user_id`); E-Mail höchstens 254 Zeichen; `.env` auf Modus 600; Versionen festgenagelt; tote Teile entfernt (`projects.list_projects`, BOM in `__init__.py`); neue Tests `test_isolation.py`, `test_db_upgrade.py` und HTTP-Test mit zweitem Konto. Die Umstellung wurde vorher an einer Kopie der echten Datenbank geprobt. |
| `owner-transfer` | Der Owner kann seine Rechte mit Passwort-Bestätigung an ein anderes Konto übergeben und wird selbst Admin. Genau ein Owner: Prüfung im Code (`create_user`, `transfer_owner`) und Teilindex `users_one_owner` in der Datenbank. Kronen-Knopf und Dialog in `/users`. |
| `theme-mail` | `users.theme` merkt den zuletzt gesehenen Stil (Schalter und Seitenaufruf melden ihn per `POST /theme`), die Mails kommen in diesem Stil. `/password` ohne „Aktuelles Passwort“ bei Startpasswort, „Abbrechen“ auf `/password` und `/reset/{token}`, „Zurück“ statt „Alle Projekte“ in der Benutzerverwaltung. |
| `invite-mail` | HTML-Mails im Design des Hubs (`mailtext.py`, Knopf, Hell und Dunkel). „Benutzer hinzufügen“ nimmt nur noch die E-Mail-Adresse und schickt eine Einladung mit Link (7 Tage); klappt der Versand nicht, wird das Konto wieder entfernt. |
| `password-reset` | „Passwort vergessen?“ per E-Mail über Resend: `mail.py`, `resets.py`, Seiten `/forgot` und `/reset/{token}`, Tabelle `password_resets`, `compose.yml` reicht die Mail-Einstellungen aus `.env` weiter. |
| `user-management` | Rollen Owner/Admin/Nutzer, Seite `/users` (Hinzufügen, Zurücksetzen, Löschen, Admin-Schalter), `/password`, Passwortregeln, Startpasswort-Zwang. |
| `login-throttle` | Sperre einer IP für eine Stunde nach 10 falschen Passwörtern in 30 Minuten (Anmeldung und Projekt-Löschen), `throttle.py`. |
| `custom-select` | Eigene Glas-Auswahlliste für die Sprache statt des Browser-Popups. |
| `fix-static-cache` | Inhalts-Hash in den Adressen der statischen Dateien, damit ein veralteter Cache nie alte und neue Skripte mischt. |

Dazu Doku-Commits (Rollenmodell, Mail-Entscheidung, Zugriff der Agenten auf Geräte, erster Speichertest von Claude Code auf dem Pi, Skill `apple-design` im Repo) und diese Fassung der Dokumente. Die Backups vor jedem Deploy liegen unter `/opt/agent-hub/backups/` (`hub-2026-11-07-before-*.db`).
