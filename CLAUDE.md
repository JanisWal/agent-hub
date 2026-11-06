# Agent-Hub – selbst gehostetes Verwaltungstool (Raspberry Pi)

Projekte als Kacheln, Kanban-Board, feste KI-Agenten-Rollen, Dateiablage, Tresor für Zugangsdaten.
Ziel, Entscheidungen und Reihenfolge der Umsetzung: PROJEKT.md (dort zuerst nachlesen).

## Zusammenarbeit
- Janis bestimmt die Struktur. Vor dem Code: erst die Schnittstelle zeigen (Signaturen, Datenformat), dann die Implementierung.
- Kleinste Lösung, die die Anforderung erfüllt. Keine Abstraktion auf Vorrat. Standardbibliothek zuerst; jede neue Abhängigkeit nennen und begründen.
- Ein Modul pro Auftrag. Jede Entscheidung kurz erklären, inklusive verworfener Alternative.
- Janis will den Code verstehen und lernen: nach größeren Änderungen zwei Verständnisfragen stellen.
- Zugangsdaten, Schlüssel und Tokens nie ausgeben, nie ins Git, nie raten. Sie liegen im Tresor oder in der `.env`.
- Destruktive oder systemweite Befehle (Löschen, Docker-Volumes entfernen, `sudo`, Änderungen am Netzwerk) vorher von Janis bestätigen lassen.
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
- Nur ein Thema pro Commit, kurze Commit-Nachrichten.
- Backups und Rückrollen sind Teil jeder Änderung, die Daten betrifft.

## Arbeitsablauf
1. Janis skizziert Modul und Schnittstelle, Claude prüft auf Schlankheit.
2. Kleine Schritte, ein Modul pro Auftrag, jeweils mit Erklärung.
3. Entwickeln und Testen auf dem Mac, Git von Anfang an, ein Branch pro Aufgabe.
4. Deploy auf den Pi per `git pull`, Integrationstests per SSH.
