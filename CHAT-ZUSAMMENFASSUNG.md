# Agent-Hub – Übergabe an einen neuen Chat

Stand: 07.11.2026, Ende des Arbeitstags · Zweck: Einstieg in einen neuen Chat oder auf einem anderen Rechner. Quelle der Wahrheit bleiben `PROJEKT.md` (Entscheidungen, Aufbau, Betrieb, Änderungsprotokoll in Abschnitt 12), `DESIGN.md` (Gestaltung) und `CLAUDE.md` (Regeln). Die frühere Übergabe vom 06.11.2026 liegt im Ordner `archiv/`.

## In einem Satz

Ein selbst gehostetes Verwaltungstool auf einem Raspberry Pi 4B (1 GB), live unter `https://hub.janis-home.de`: Projekte als Kacheln, Kanban-Board, später feste KI-Agenten pro Nutzer mit eigenem Claude-Konto. Repo `JanisWal/agent-hub` (privat), `main` = Produktiv.

## Was heute (07.11.2026) dazugekommen ist

1. **Benutzerverwaltung:** Rollen Owner, Admin, Nutzer; Seite `/users` (Hinzufügen, Zurücksetzen, Löschen, Admin-Schalter); eigenes Passwort ändern; Passwortregeln (6 Zeichen, Groß/Klein, Sonderzeichen, zwei Zahlen).
2. **E-Mail über Resend** (Absender `Agent-Hub <noreply@janis-home.de>`): „Passwort vergessen“ und Einladung. „Benutzer hinzufügen“ fragt nur noch die E-Mail-Adresse; die Person legt über einen Link (7 Tage) ihr Passwort selbst fest. Janis hat den Reset selbst getestet, es funktioniert.
3. **Schöne HTML-Mails** im Design des Hubs, in Hell und Dunkel. Welcher Stil verschickt wird, hängt am Konto (`users.theme`): Der Schalter meldet die Wahl zusätzlich an den Server, jede Seite meldet ihren Stil beim Laden. Janis fand die helle Mail „extrem gelungen“.
4. **Passwortseiten:** Wer ein Startpasswort hat, sieht kein „Aktuelles Passwort“; „Abbrechen“ auf `/password` und im Reset; „Zurück“ statt „Alle Projekte“ in der Benutzerverwaltung.
5. **Owner übergeben:** Der Owner kann die Rechte per Kronen-Knopf mit Passwort an ein anderes Konto übergeben und wird selbst Admin. Immer genau ein Owner (Code und Datenbank-Index), keine feste Person.
6. **Prüfung des Codes seit der letzten Säuberung** (`review-cleanup`): Sitzungen nur noch als Hash; Migrationen einmalig; `is_admin` entfernt; „Passwort vergessen“ pro IP begrenzt; offene Reset-Links sterben mit dem neuen Passwort; `create_suggestion` prüft den Besitz; `.env` nur für `admin` lesbar; Versionen festgenagelt; Mandantentrennung mit eigenen Tests belegt (Unit-Tests und HTTP-Test mit zwei Konten). **Janis wurde dabei einmal abgemeldet.**

## Entscheidungen und Wünsche von Janis (neu)

- Resend als Mail-Dienst, `noreply@janis-home.de`.
- Einladung per Mail statt Startpasswort; Startpasswort nur noch beim Zurücksetzen eines bestehenden Kontos.
- Mail im zuletzt benutzten Stil (hell oder dunkel) des Empfängers; der Schalter bleibt lokal im Browser und meldet zusätzlich an das Profil.
- Owner nicht fest: übertragbar, mit Passwort abgesichert, der alte Owner wird Admin, nie zwei Owner.
- Jeder Nutzer nur in seiner eigenen Umgebung; jeder verbindet sein eigenes Claude-Konto; die Konten dürfen sich nie berühren und nie ein fremdes mitbenutzen (Pflichtregeln in PROJEKT.md Abschnitt 3).
- Dokumentation und Änderungsstand sollen immer nachgeführt sein, damit ein neuer Chat alles findet.

## Wie Claude hier arbeitet (Kurzfassung, Details in PROJEKT.md Abschnitt 9)

- Deutsch antworten, kurz erklären, **keine Verständnisfragen am Ende**; erst Schnittstelle zeigen, dann Code; kleinste Lösung; ein Thema pro Commit.
- Commit, Merge, Push, Deploy und Tests ohne Rückfrage, danach berichten. Fragen nur bei Berechtigungen, Sicherheit, Design und Features.
- Am Windows-PC gibt es kein Git: Dateien lokal bearbeiten, per `scp` in den Klon auf dem Pi (`/opt/agent-hub/workspaces/agent-hub`), dort Branch, Tests im Container, Merge, Push, Backup der Datenbank, `docker compose up -d --build web`.
- Zugang zum Pi: `ssh -i ~/.ssh/id_agenthub admin@home.local`. Passwörter und Schlüssel nie ausgeben.
- Keine Ports freigeben (die Sicherheitsprüfung lehnt es ab); Mail-Vorschauen als Datei erzeugen (`web/tests/preview_mail.py`).

## Wo wir stehen

- **Fertig und live:** alles unter „Auf einen Blick“ in PROJEKT.md. 141 Unit-Tests und der HTTP-Test mit zwei Konten sind grün.
- **Nicht geprüft:** Aussehen der Mails in echten Mailprogrammen; Benutzerverwaltung und Dialoge nicht von Janis angesehen; Berührung am Handy; Flüssigkeit der Bewegung.
- **Nicht gebaut:** Claude-Anbindung und Agenten, Dateiablage, Tresor, Token-Anzeige, restic-Backup, SSD-Umzug, Härtung des Containers, Content-Security-Policy, Zwei-Faktor-Anmeldung.

## Nächste Aufgaben (Vorschlag, Reihenfolge)

1. Janis prüft die Mails in echten Postfächern (hell und dunkel), lädt eine zweite Adresse ein und probiert die Owner-Übergabe mit einem Testkonto.
2. Rest von Phase 1: Dateiablage, Backup mit restic, SSD.
3. Checkliste vor dem Livegang: Container als eigener Benutzer mit Speicherlimit (zuerst die Rechte des Datenordners anpassen), Gesundheitsprüfung, Content-Security-Policy.
4. Phase 2: Claude-Anbindung pro Nutzer nach den Pflichtregeln, Runner an die Website, Verbrauchsanzeige, Tresor mit Vermittler. Der alte Runner (ein gemeinsames Volume `agent-hub_claude-home`, Janis’ Anmeldung) wird dabei durch Ordner pro Nutzer ersetzt.
5. Aufräumen auf dem Pi, nur nach Janis’ Ja: alte Codekopie `/opt/agent-hub/web`, alter Compose-Ordner mit dem Runner, doppelte Dateien unter `/home/admin/cloudflared`, 21 gemergte lokale Branches.

## Sicherheits-Stand in Stichworten

Passwörter scrypt; Sitzungen und Reset-Links nur als Hash; Cookie HttpOnly, SameSite=Lax, Secure; Sperre pro IP bei falschen Passwörtern und bei zu vielen Reset-Anfragen; Rechte und Rollen prüft der Server bei jeder Anfrage; ernste Aktionen verlangen das Passwort; Mandantentrennung durch Tests belegt; Links in Mails aus `HUB_BASE_URL`; `.env` nur für `admin` lesbar, nie im Git. Offen: Container läuft noch als root, keine Content-Security-Policy, Reset-Links stehen eine Stunde lang im Zugriffslog des Containers (nur für wen den Pi erreicht).
