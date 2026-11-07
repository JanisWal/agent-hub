# Agent-Hub – selbst gehostetes Verwaltungstool (Raspberry Pi)

Projekte als Kacheln, Kanban-Board, feste KI-Agenten-Rollen, Dateiablage, Tresor für Zugangsdaten.
Ziel, Entscheidungen und Reihenfolge der Umsetzung: PROJEKT.md (dort zuerst nachlesen).

## Zusammenarbeit
- Janis bestimmt die Struktur. Vor dem Code: erst die Schnittstelle zeigen (Signaturen, Datenformat), dann die Implementierung.
- Kleinste Lösung, die die Anforderung erfüllt. Keine Abstraktion auf Vorrat. Standardbibliothek zuerst; jede neue Abhängigkeit nennen und begründen.
- Ein Modul pro Auftrag. Jede Entscheidung kurz erklären, inklusive verworfener Alternative.
- Janis will den Code verstehen, aber keine Verständnisfragen am Ende einer Antwort (gestrichen am 07.11.2026). Entscheidungen weiter kurz erklären.
- Zugangsdaten, Schlüssel und Tokens nie ausgeben, nie ins Git, nie raten. Sie liegen im Tresor oder in der `.env`.
- Destruktive oder systemweite Befehle (Löschen, Docker-Volumes entfernen, `sudo`, Änderungen am Netzwerk) vorher von Janis bestätigen lassen.
- Routine (Commit, Merge, Push fertiger Änderungen) ohne Rückfrage, danach kurz berichten. Nachfragen nur bei Berechtigungen, Sicherheit sowie Design- und Feature-Entscheidungen.
- Hardware am Fahrzeug (Roadster, Heizung, Relais, Bordnetz) nie autonom schalten oder testen; das macht Janis vor Ort.

## Architektur (Stand, Details in PROJEKT.md)
- Raspberry Pi 4B, Raspberry Pi OS Lite 64-Bit, alles per Docker Compose unter `/opt/agent-hub/`.
- Python (Framework noch offen, Vorschlag FastAPI), SQLite, schlichtes Frontend.
- Zugriff von außen nur über Cloudflare Tunnel, keine offenen Router-Ports. Login mit E-Mail und Passwort, Passwort-Reset per E-Mail.
- Claude Code läuft als Runner auf dem Pi; für Swift-Aufgaben ein Runner auf dem Mac mit derselben Schnittstelle (nur ausgehende Verbindung).
- Pro Aufgabe ein Git-Branch (Worktree). Ablauf: Programmierer, Tester, Prüfer, Freigabe durch Janis, Dokumentator.
- Agenten nutzen Zugangsdaten nur über den Vermittler, nie direkt.

## Coding-Regeln
- Code, Klassen, Variablen, Dateinamen und Kommentare auf Englisch. Oberfläche und Doku auf Deutsch.
- Bewegung in der Oberfläche folgt dem Skill `apple-design`: Federn aus `web/app/static/motion.js` statt fester Dauern, immer unterbrechbar, nur `transform` und `opacity`, `prefers-reduced-motion` beachten. Neue Zieh-Listen nutzen `Motion.sortable`. Details in DESIGN.md Abschnitt 6.
- Die Oberfläche ist zweisprachig (Deutsch und Englisch, pro Nutzer wählbar). Jeder neue Text kommt in `web/app/i18n.py` in beide Sprachen, nie fest im HTML oder JavaScript. Neue Seiten bauen auf `layout.page()` auf.
- Für Oberfläche und Swift/iOS-Teile gelten die Apple Human Interface Guidelines (Bedienung, Layout, Typografie, Farben, Barrierefreiheit) und die Apple-Richtlinien für Swift und die App Review. Bei Zielkonflikten mit dem Projektsheet fragt Claude nach. Das konkrete Design (Farben, Glas, Knöpfe, Hell/Dunkel) steht in DESIGN.md und ist für jede Oberfläche verbindlich.
- Nur ein Thema pro Commit, kurze Commit-Nachrichten.
- Backups und Rückrollen sind Teil jeder Änderung, die Daten betrifft.

## Arbeitsablauf
1. Janis skizziert Modul und Schnittstelle, Claude prüft auf Schlankheit.
2. Kleine Schritte, ein Modul pro Auftrag, jeweils mit Erklärung.
3. Entwickeln und Testen auf dem Mac, Git von Anfang an, ein Branch pro Aufgabe.
4. Deploy auf den Pi per `git pull`, Integrationstests per SSH.
