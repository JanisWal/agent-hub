# Agent-Hub – selbst gehostetes Verwaltungstool (Raspberry Pi)

Projekte als Kacheln, Kanban-Board, feste KI-Agenten-Rollen, Dateiablage, Tresor für Zugangsdaten.
Ziel, Entscheidungen, Reihenfolge, Codeaufbau, Betrieb, Tests und offene Punkte: PROJEKT.md (dort zuerst nachlesen, Abschnitt „Auf einen Blick“ und Abschnitt 12 „Änderungsprotokoll“). Gestaltung: DESIGN.md. Übergabe des letzten Arbeitstags: CHAT-ZUSAMMENFASSUNG.md.

## Zusammenarbeit
- Janis bestimmt die Struktur. Vor dem Code: erst die Schnittstelle zeigen (Signaturen, Datenformat), dann die Implementierung.
- Kleinste Lösung, die die Anforderung erfüllt. Keine Abstraktion auf Vorrat. Standardbibliothek zuerst; jede neue Abhängigkeit nennen und begründen.
- Ein Modul pro Auftrag. Jede Entscheidung kurz erklären, inklusive verworfener Alternative.
- Janis will den Code verstehen, aber keine Verständnisfragen am Ende einer Antwort (gestrichen am 07.11.2026). Entscheidungen weiter kurz erklären.
- Zugangsdaten, Schlüssel und Tokens nie ausgeben, nie ins Git, nie raten. Sie liegen im Tresor oder in der `.env`.
- Destruktive oder systemweite Befehle (Löschen, Docker-Volumes entfernen, `sudo`, Änderungen am Netzwerk) vorher von Janis bestätigen lassen. Keine Ports für Vorschauen freigeben.
- Routine (Commit, Merge, Push fertiger Änderungen) ohne Rückfrage, danach kurz berichten. Nachfragen nur bei Berechtigungen, Sicherheit sowie Design- und Feature-Entscheidungen.
- Hardware am Fahrzeug (Roadster, Heizung, Relais, Bordnetz) nie autonom schalten oder testen; das macht Janis vor Ort.
- Neue Pflichten, Entscheidungen und Änderungen gehören am Ende eines Auftrags in PROJEKT.md (Stand, Änderungsprotokoll) und bei Gestaltung in DESIGN.md.

## Architektur (Stand, Details in PROJEKT.md)
- Raspberry Pi 4B, Raspberry Pi OS Lite 64-Bit, alles per Docker Compose unter `/opt/agent-hub/`.
- Python mit FastAPI, SQLite, schlichtes Frontend (serverseitige Vorlagen, kein Framework). Läuft live unter `hub.janis-home.de`.
- Zugriff von außen nur über Cloudflare Tunnel, keine offenen Router-Ports. Login mit E-Mail und Passwort, Rollen Owner (genau einer, übertragbar), Admin, Nutzer; Einladung und Passwort-Reset per E-Mail über Resend.
- Claude Code läuft über den Runner auf dem Pi, ein Wegwerf-Container je Lauf. Live: Claude verknüpfen pro Nutzer und der Manager-Chat; Agentenläufe sind gebaut, aber noch nicht angeschlossen. Für Swift später ein Mac-Programm (nur ausgehend, Start per Knopf ohne zweite Anmeldung, Ergebnis als Git-Bundle über den Hub).
- Netz der Agenten: internes Docker-Netz, einziger Ausgang der Filter-Proxy `egress` (3129 nur Anthropic, 3128 öffentliche Seiten); nie ins Heimnetz. Geräte nur über Geräteliste und Vermittler, fremde Netze über Tailscale; auf der Fritzbox wird kein Port geöffnet.
- Jeder Nutzer verbindet sein eigenes Claude-Konto; die Konten sind strikt getrennt (Pflichtregeln in PROJEKT.md Abschnitt 3, „Trennung der Claude-Konten“).
- Pro Aufgabe ein Git-Branch (Worktree). Ablauf: Programmierer, Tester, Prüfer, Freigabe durch Janis, danach führt der Manager die Doku nach (Rolle Dokumentator entfallen am 07.11.2026).
- Agenten nutzen Zugangsdaten nur über den Vermittler, nie direkt.

## Coding-Regeln
- Code, Klassen, Variablen, Dateinamen und Kommentare auf Englisch. Oberfläche und Doku auf Deutsch.
- Bewegung in der Oberfläche folgt dem Skill `apple-design`: Federn aus `web/app/static/motion.js` (Ziehen: `sortable.js`) statt fester Dauern, immer unterbrechbar, nur `transform` und `opacity`, `prefers-reduced-motion` beachten. Neue Zieh-Listen nutzen `Motion.sortable`. Details in DESIGN.md Abschnitt 6.
- Die Oberfläche ist zweisprachig (Deutsch und Englisch, pro Nutzer wählbar). Jeder neue Text, auch in Mails, kommt in `web/app/i18n.py` in beide Sprachen, nie fest im HTML oder JavaScript. Neue Seiten bauen auf `ui.logged_in_page()` / `layout.page()` auf, neue Routen kommen als Router in `web/app/routes/`.
- Für Oberfläche und Swift/iOS-Teile gelten die Apple Human Interface Guidelines (Bedienung, Layout, Typografie, Farben, Barrierefreiheit) und die Apple-Richtlinien für Swift und die App Review. Bei Zielkonflikten mit dem Projektsheet fragt Claude nach. Das konkrete Design (Farben, Glas, Knöpfe, Hell/Dunkel, Mails) steht in DESIGN.md und ist für jede Oberfläche verbindlich.
- **Mandantentrennung:** Jede Datenfunktion bekommt die `user_id` und prüft den Besitz (Projekt, Punkt, Konto); Fremdes ist „nicht gefunden“ (404) oder „nichts getan“. Das gilt auch für Code, den Agenten aufrufen. Neue Funktionen bekommen einen Fall in `web/tests/test_isolation.py`.
- **Rechte prüft der Server**, nicht das Menü (`users.can_manage`, Rollenprüfung in der Route). Ernste Aktionen (Löschen, Zurücksetzen, Owner übergeben) verlangen das Passwort des Handelnden (`deps.reauth`, mit Sperre pro IP). Offene Routen, die Mails auslösen oder Passwörter prüfen, bekommen eine Begrenzung (`throttle.py`).
- **Tokens** (Sitzung, Reset-Link) stehen in der Datenbank nur als Hash. Links in Mails kommen aus `HUB_BASE_URL`, nie aus der Anfrage. Mails nur über `mail.py` und `mailtext.py`.
- **Datenbank:** Schemaänderungen über `db.py`; Umwandlungen alter Daten laufen einmalig, nie bei jedem Start; eine Migration wird vor dem Deploy an einer Kopie der echten Datenbank geprobt; vor jedem Deploy ein Backup.
- **Text an Claude** (Projektkontext, Berichte, Fragen) geht nur über die Standardeingabe und ist als Information markiert, nie über die Befehlszeile; der Kontext kommt nur aus Daten des Besitzers. Der Launcher nimmt nur geprüfte Werte (Zahlen, Modell aus `MODELS`, Modus aus `CHAT_MODES`).
- **Oberfläche:** Auswahlfelder immer im eigenen Stil (`.has-select`, Liste aus `core.js`), nie die Liste des Browsers, und ohne `title` (der Hinweis deckt sonst die Liste zu). Klassen in einer Ansicht mit Präfix, wenn ein Name schon vergeben ist (Manager: `m-`).
- **Board und Manager:** Das Board ist nur für Software (Bugs, kleine und Major-Updates). Hardware-To-Dos, Checklisten und regelmäßige Prüfungen gehören dem Manager. Einstellungen gelten pro Nutzer und pro Agent: Modell und Schalter „Web + Code zusammen“ hat jede Rolle selbst (`agents.configure(user, rolle, ...)`, der Manager ist `chef`); die Selbstständigkeit gehört dem Manager.
- Nur ein Thema pro Commit, kurze englische Commit-Nachrichten, ein Branch pro Aufgabe.
- Backups und Rückrollen sind Teil jeder Änderung, die Daten betrifft.

## Arbeitsablauf
1. Janis skizziert Modul und Schnittstelle, Claude prüft auf Schlankheit.
2. Kleine Schritte, ein Modul pro Auftrag, jeweils mit Erklärung.
3. Entwickeln und Testen: Am Windows-PC ohne Git über den Klon auf dem Pi (Ablauf in PROJEKT.md Abschnitt 9, „Arbeitsablauf vom PC aus“), später auch am Mac. Git von Anfang an, ein Branch pro Aufgabe.
4. Tests im Container (Unit-Tests, HTTP-Test mit zwei Konten), dann Merge nach `main`, Push, Backup, Deploy per `docker compose up -d --build web`, Prüfung von `/health` und der Live-Seite.
