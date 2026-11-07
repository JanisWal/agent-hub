# Agent-Hub – Designrichtlinien

Stand: 07.11.2026 · Entscheidungen von Janis. Die Login-Seite ist der abgenommene Referenzentwurf; alle Werte unten stammen aus ihr (`web/app/static/theme.css`, `theme.js`, `page()` in `web/app/main.py`). Wird ein Wert geändert, wird zuerst diese Datei angepasst, dann der Code. Änderungen am Design sind Entscheidungen von Janis.

Legende: **Ist** = umgesetzt und geprüft. **Ziel** = gewollt, noch nicht gebaut. **Ungeprüft** = gebaut, aber nicht nachgemessen.

## 1. Leitidee

Zwei Welten gemischt, nicht Apple in Reinform:
- **Von Apple (100 %):** runde Glasoptik, Symmetrie, Schatten und Lichtspiele, flüssige federnde Bewegung. Grundlage: Skill `apple-design` (`.claude/skills/apple-design/SKILL.md`) und die Apple Human Interface Guidelines.
- **Von Claude:** warme, ruhige Farben in Richtung Aprikose, kein kaltes Weiß, viel Luft.
- Zwei Stile, Hell und Dunkel, immer per Schalter wechselbar.
- Janis' Gefühl für „das gewisse Etwas“: entstand durch Tiefe (Lichtkante, Farbflächen hinter dem Glas), nicht durch mehr Dekoration. Bei Zweifeln lieber weglassen als hinzufügen.

## 2. Farben

Nie reines Weiß (`#FFFFFF`) oder reines Schwarz. Alle Flächen sind warm getönt. Jeder Wert steht als CSS-Variable in `theme.css`, nirgends feste Farben im Code oder in Seiten.

| Variable | Rolle | Hell | Dunkel |
|---|---|---|---|
| `--bg` | Hintergrund | `#EFDCC6` | `#1F1713` |
| `--glass` | Glasfläche | `rgba(247, 221, 196, 0.5)` | `rgba(66, 46, 36, 0.45)` |
| `--glass-border` | Rand von Feldern und Knöpfen | `rgba(255, 255, 255, 0.4)` | `rgba(255, 210, 170, 0.14)` |
| `--field` | Eingabefeld | `rgba(222, 170, 125, 0.28)` | `rgba(20, 12, 8, 0.4)` |
| `--text` | Text | `#3A2A20` | `#F6E6D8` |
| `--muted` | Text gedämpft (Labels, Unterzeile, Links) | `#6F5848` | `#BDA591` |
| `--accent` | Hauptknopf, Fokus | `#E8845A` | `#F29A72` |
| `--on-accent` | Text auf dem Hauptknopf | `#2B1D14` | `#2B1D14` |
| `--error` | Fehler | `#A63A1F` | `#FF9B7E` |
| `--danger` | Löschen: Dialograhmen, Titel, Knopf | `#C03A20` | `#FF7457` |
| `--on-danger` | Text auf dem Löschknopf | `#FFF3EA` | `#2A0E07` |
| `--shadow` | Schatten (zweilagig) | `0 18px 50px rgba(110,65,28,0.22), 0 2px 8px rgba(110,65,28,0.12)` | `0 18px 50px rgba(0,0,0,0.55), 0 2px 8px rgba(0,0,0,0.35)` |
| `--highlight` | Lichtkante | `rgba(255, 255, 255, 0.45)` | `rgba(255, 220, 190, 0.28)` |
| `--orb-a` | Farbfläche oben links | `#F0A878` | `#8A4F2E` |
| `--orb-b` | Farbfläche unten rechts | `#E6BF8C` | `#6B3A22` |
| `--orb-c` | kleine Farbfläche hinter der Karte | `#E8845A` | `#C8683F` |
| `--orb-opacity` | Deckkraft der zwei großen Flächen | `0.36` | `0.30` |
| `--orb-c-opacity` | Deckkraft der kleinen Fläche | `0.45` | `0.40` |

Regeln:
- Der helle Stil ist **bewusst gedämpft**. Der erste Entwurf (`#FFF1E3` Hintergrund, Glas `rgba(255,232,208,0.62)`) wirkte zu grell und wurde abgedunkelt. Heller als die Werte oben wird er nicht.
- Textkontrast mindestens 4,5 : 1 (WCAG AA), auch auf Glas. Besteht ein Wert die Prüfung nicht, wird der Wert angepasst, nicht der Kontrast gesenkt. **Ungeprüft:** Eine echte Messung aller Paare (besonders `--muted` auf Glas und `--on-accent` auf `--accent`) steht aus.
- Fehler, Warnung und Erfolg nie nur über Farbe, immer mit Text.
- Dunkel gilt entweder durch `data-theme="dark"` am `<html>` oder, wenn nichts gewählt ist, durch `prefers-color-scheme: dark`. Beide Blöcke enthalten dieselben Werte und müssen gemeinsam geändert werden.
- `color-scheme: light` bzw. `dark` wird mit dem Stil gesetzt, damit Browser-Elemente (Autofill-Vorschläge, Scrollbalken) passen.

## 3. Glas

- Gläserne Fläche (`.glass`): `backdrop-filter: blur(28px) saturate(1.6)` (mit `-webkit-`-Präfix), Füllung `--glass`, Schatten `--shadow`, Rundung 28 px, Innenabstand 40 px (5 × 8), Breite 100 % bis maximal 420 px.
- **Lichtkante:** Ein `::before` mit 1,5 px Rand, Verlauf `135deg` von `--highlight` über transparent (bei 38 % und 62 %) zurück zu `--highlight`. Per Maske nur als Rand sichtbar. So fängt die Karte oben links und unten rechts Licht, statt einen flachen Rand zu haben.
- **Farbflächen dahinter** (`.orbs`, drei Kreise, `position: fixed`, hinter allem, `aria-hidden`), Unschärfe 70 px:
  - Nr. 1: 42 vmax, links −10 vmax, oben −12 vmax, Farbe `--orb-a`, Drift 30 s.
  - Nr. 2: 46 vmax, rechts −14 vmax, unten −16 vmax, Farbe `--orb-b`, Drift 38 s.
  - Nr. 3: 16 vmax, links `50 % + 6 vmax`, oben 52 %, Farbe `--orb-c`, Drift 24 s.
  - Drift (`ease-in-out`, endlos, abwechselnd): Nr. 1 → 14 vmax rechts, 10 vmax runter, Skalierung 1,10; Nr. 2 → 12 vmax links, 8 vmax hoch, 1,08; Nr. 3 → 10 vmax links, 6 vmax hoch, 1,20.
  - Zweck: Das Glas hat etwas zum Brechen. Die zwei großen Kugeln in den Ecken dürfen **nie auffallen** (Janis fand sie anfangs zu präsent, deshalb Deckkraft 0,36 / 0,30 und Unschärfe 70 px).
- Glas sparsam einsetzen: Kopfleiste, Kacheln, Dialoge. Nicht jedes Element.
- Rückfall, Ist: Fehlt `backdrop-filter` oder ist `prefers-reduced-transparency: reduce` aktiv, wird die Fläche deckend in `--bg`.

## 4. Formen, Knöpfe, Links

- Rundungen: Knöpfe und Felder 16 px (`--radius-button`), Karten und Dialoge 28 px (`--radius-card`), Symbolknöpfe voll rund (50 %).
- Abstandseinheit `--space` = 8 px.
- **Wenige, große Schaltflächen** statt vieler kleiner. Mindestgröße 44 × 44 px.
- Ein Knopf zeigt **entweder Symbol oder Text**. Beides nur als Ausnahme, wenn es Missverständnisse verhindert (z. B. „Endgültig löschen“ mit Symbol).
- Pro Ansicht genau ein Hauptknopf. Alles andere ist zurückhaltend.
- Löschen und Verwerfen sind nie in der Hauptfarbe und brauchen eine Bestätigung.
- **Normaler Knopf:** Schrift 600, Füllung `--glass`, Rand 1 px `--glass-border`, Schatten `--shadow`, Hover hebt um 1 px an, Klick skaliert auf 0,97. Übergang 0,25 s `cubic-bezier(0.3, 1.5, 0.5, 1)` (federnd).
- **Hauptknopf (`.primary`):** volle Breite, Höhe mindestens 54 px, Schrift 1,05 rem, Text `--on-accent`, Füllung `--accent` mit hellem Glanz oben (Verlauf von `rgba(255,255,255,0.38)` zu transparent bei 55 %), Rand `rgba(255,255,255,0.4)`, Schatten `0 10px 24px` in 38 % Akzent plus innere Lichtlinie `inset 0 1px 0 rgba(255,255,255,0.55)`, Hover `brightness(1.05)`, Abstand oben 8 px.
- **Nebenaktion als Textlink (`.link`):** ohne Kasten, ohne Schatten, zentriert, Höhe mindestens 44 px, Schrift 0,92 rem Gewicht 500, Farbe `--muted`, Abstand oben 16 px. Beim Darüberfahren Farbe `--text` und Unterstreichung (Abstand 4 px, vorher transparent, Übergang 0,2 s). Noch nicht gebaute Funktionen: `disabled`, Cursor normal, `title="Kommt später"` (Beispiel: „Passwort vergessen?“).
- **Umschalter Hell/Dunkel (`.theme-fab`):** 52 px rund, nur Symbol (Linien 2 px, runde Enden, 24 px), **fest unten rechts** (24 px Abstand zu Rand und Boden, über allem), `aria-label` übersetzt. Zeigt das Symbol des Stils, **zu dem man wechseln würde**: im hellen Stil den Mond, im dunklen die Sonne.

## 5. Hell und Dunkel

- Umschalter **fest unten rechts auf jeder Seite**, auch auf Login und in jedem Menü, ein Klick, immer sichtbar. (Früher in der Kopfleiste, am 07.11.2026 nach unten rechts verschoben.)
- Erster Besuch: Stil der Geräteeinstellung (`prefers-color-scheme`). Danach gilt die Wahl, gespeichert im Browser (`localStorage`, Schlüssel `theme`, Werte `light` / `dark`), für alle Seiten.
- Kein Aufblitzen: Ein kleines Inline-Skript im `<head>` setzt `data-theme` vor dem ersten Zeichnen. `theme.js` übernimmt nur den Klick.
- `localStorage` kann blockiert sein (private Fenster): jeder Zugriff steht in `try/catch`, die Seite funktioniert dann ohne Speichern.

## 6. Bewegung

- Kurz, federnd, ruhig. Details im Skill `apple-design`.
- Karte beim Laden (`rise`): 0,7 s, `cubic-bezier(0.3, 1.25, 0.5, 1)` (leichtes Überschwingen), von 14 px tiefer, Skalierung 0,97 und unsichtbar zu normal.
- Fehlermeldung unter dem Feld (`fade`): 0,2 s, von 3 px höher und unsichtbar zu normal.
- Felder: Rand und Ring blenden in 0,2 s um. Textlink: Farbe und Unterstreichung 0,2 s.
- Hintergrund-Farbflächen driften sehr langsam (siehe Abschnitt 3), nur als ruhiges Hintergrundleben.
- `prefers-reduced-motion: reduce` wird beachtet, **Ist:** dann entfallen **alle** Übergänge und Animationen, auch das Einblenden (nichts bewegt sich, alles steht sofort).

## 7. Typografie

- Systemschrift: `system-ui, -apple-system, "Segoe UI", sans-serif`. Keine Webfonts (Ladezeit, schlanker Pi).
- Überschrift `h1`: 2 rem, Laufweite −0,03 em, kein Außenabstand. Darunter die Unterzeile (`.subtitle`): Farbe `--muted`, Abstand 8 px oben und 24 px unten. Jede Seite hat eine kurze Überschrift und eine freundliche Unterzeile (Login: „Anmelden“ / „Willkommen zurück.“).
- Marke „Agent-Hub“ in der Kopfleiste: 1,1 rem, Gewicht 650, Laufweite −0,01 em.
- Feldbeschriftung (`label`): 0,9 rem, Farbe `--muted`. Eingabetext 1 rem. Fehlertext unter Feld 0,85 rem, Gewicht 600.
- Seitentitel im Browser-Tab: „Seitenname – Agent-Hub“.

## 8. Raster und Layout

- Abstände im 8-px-Raster; gleiche Abstände links/rechts und oben/unten innerhalb einer Fläche (Symmetrie).
- Kopfleiste: Marke links, auf angemeldeten Seiten rechts die Einstellungsleiste (Login: nur die Marke), Innenabstand 16 px oben/unten und 24 px seitlich.
- Inhalt: `main` füllt den Rest der Höhe, Inhalt zentriert, Außenabstand 24 px, unten 96 px Platz für den Umschalter. Meta-Tag `viewport` ist gesetzt.
- Breite Seiten (Dashboard): Inhaltsbereich `.dash` mit höchstens 1100 px Breite, Abstand zwischen Blöcken 32 px. Auf kleinen Bildschirmen weniger Spalten (siehe Abschnitt 10).
- **Ungeprüft:** Handy-Ansicht (Layout wurde nur am großen Bildschirm angesehen).

## 9. Formulare

- **Keine Browser-Blasen** („Bitte füllen Sie dieses Feld aus“): Formulare tragen `novalidate`. `theme.js` prüft beim Absenden jedes Pflichtfeld und zeigt die Meldung im Design direkt unter dem Feld.
- Meldungstexte: leeres Feld „Bitte ausfüllen.“, ungültige Adresse „Bitte eine gültige E-Mail-Adresse eingeben.“ Als leer gilt ein Feld, das nur Leerzeichen enthält, **außer Passwörter** (dort zählt jedes Zeichen).
- Verhalten: Das erste fehlerhafte Feld bekommt den Fokus, die Meldung hat `role="alert"`, das Feld `aria-invalid="true"`, Rand und Ring in `--error` (Ring 4 px, 22 % Fehlerfarbe). Die Meldung verschwindet, sobald im Feld getippt wird.
- Der Server prüft immer selbst; fehlende Felder gelten dort als leer (`Form("")`) und führen zur Fehlermeldung statt zu einer technischen Fehlerseite. Falsche Anmeldung liefert Status 401 und dieselbe Meldung für „E-Mail“ und „Passwort“.
- Meldung vom Server („E-Mail oder Passwort falsch.“): getönte Box (`.error`) oben im Formular, Schrift 600 in `--error`, Hintergrund 12 % und Rand 30 % Fehlerfarbe, Rundung 16 px, `role="alert"`. Nie als lose rote Schrift.
- **Eingabefeld:** volle Breite, Höhe mindestens 50 px, Innenabstand 16 px seitlich, Schrift 1 rem in `--text`, Füllung `--field`, Rand 1 px `--glass-border`, Rundung 16 px, leichter Innenschatten `inset 0 1px 3px rgba(80,40,10,0.14)`.
- **Fokus:** Rand `--accent` plus Ring 4 px in 28 % Akzent; Cursor (`caret-color`) in `--accent`. Für Tastaturnutzer auf anderen Elementen: `:focus-visible` mit 3 px `--accent` und 2 px Abstand.
- **Platzhalter:** `--muted` bei 60 % Deckkraft. Login: E-Mail `name@beispiel.de`, Passwort `••••••••`.
- **Autofill des Browsers** bekommt den Ton der Seite (70 % `--bg` mit 30 % `--accent`) und die Textfarbe `--text`, nicht Gelb oder Blau.
- Attribute: E-Mail `autofocus`, `autocomplete="username"`; Passwort `autocomplete="current-password"`.
- Abstände: Label 16 px unten, Feld 8 px unter dem Label, Meldung 6 px unter dem Feld.

## 10. Dashboard (Startseite nach dem Login)

Stand 07.11.2026, von Janis beauftragt, mit Testkonten im Browser geprüft (Dunkel und Hell, Deutsch und Englisch).

**Begrüßung**
- Große Überschrift `.greeting`: Größe `clamp(2.2rem, 5.5vw, 3.6rem)`, Laufweite −0,035 em. Text „Guten Morgen / Guten Mittag / Guten Abend, Name“, bestimmt im Browser nach der **lokalen Uhrzeit** des Besuchers: 5–11 Uhr Morgen, 11–17 Uhr Mittag, sonst Abend. Ohne JavaScript steht „Hallo, Name“.
- Name: der gewählte Nutzername, sonst der Teil der E-Mail vor dem `@`.

**Einstellungsleiste (oben rechts, auf jeder angemeldeten Seite)**
- Dezente Pille (`.settings-toggle`): Nutzername (höchstens 14 Zeichen sichtbar) und ein Pfeil, Schrift 0,92 rem in `--muted`, Fläche nur 60 % Glas, kein Schatten. Der Pfeil dreht sich beim Aufklappen um 180°.
- Aufgeklapptes Panel (`.settings-panel`, Glas, 300 px, Rundung 24 px, 16 px unter der Pille): Feld **Nutzername** (höchstens 40 Zeichen), Auswahl **Sprache** (zwei große Schalter „Deutsch“ / „English“, der gewählte mit Akzentrand), **Speichern**, dann „Claude verknüpfen“ und „ChatGPT verknüpfen“ (ausgegraut, „Kommt später“), darunter **Abmelden**.
- Schließt bei Klick daneben und mit Escape.

**Projektkacheln (Mitte)**
- Raster 3 Spalten × 2 Reihen, Abstand 24 px, Reihenhöhe mindestens 190 px, **6 Kacheln pro Seite**. Unter 900 px Breite 2 Spalten, unter 560 px eine Spalte.
- Projektkachel: Glas, Innenabstand 24 px, Projektname groß unten links (1,5 rem, Gewicht 650, höchstens 3 Zeilen), weitere Infos folgen später. Die ganze Kachel ist ein Link zum Projekt (**ohne** Anmeldeabfrage). Beim Darüberfahren hebt sie sich um 3 px. Beim Laden blenden die Kacheln gestaffelt ein (70 ms Versatz).
- **Löschknopf:** kleiner runder Knopf oben rechts in der Kachel (sichtbar 36 px, Klickfläche 44 px), Mülleimer-Symbol, Farbe `--muted`, beim Darüberfahren `--danger`.
- **Plus-Kachel:** Der nächste freie Platz zeigt ein großes Plus (56 px, Akzentfarbe, 70 % Deckkraft, gestrichelter Rand, helle Fläche). Beim Darüberfahren wird sie kräftiger und das Plus dreht sich um 90°. Klick öffnet „Neues Projekt“ (Name, Anlegen, Abbrechen).
- **Einstiegstext:** Auf der Plus-Kachel oben links steht „Beginne mit deinem ersten Projekt“, solange der Nutzer noch nie ein Projekt hatte (`users.had_project`). Er kommt nach dem Löschen des letzten Projekts **nicht** zurück.
- **Leere Plätze** sind nur zarte gestrichelte Umrisse (55 % Deckkraft), damit das Raster bestehen bleibt. Sie sind nicht klickbar.
- **Drag and Drop:** Nur belegte Kacheln lassen sich umordnen. Plus und leere Plätze bleiben stehen. Die gezogene Kachel wird halbtransparent (45 %) und etwas kleiner. Die neue Reihenfolge wird sofort gespeichert; die Reihenfolge anderer Seiten bleibt erhalten.
- **Mehrere Seiten:** Ab dem siebten Projekt entsteht Seite 2 usw. Ist die letzte Seite voll, kommt das Plus auf eine neue Seite. Unter dem Raster: kleine Punkte (10 px, aktiver Punkt als 26-px-Pille in Akzentfarbe, Klick springt zur Seite) und links/rechts je ein dezentes Dreieck (44 px Klickfläche, am Rand ausgegraut).

**Löschen (zweistufig, bewusst deutlich)**
- Mülleimer → Dialog 1: „Sind Sie sicher, dass Sie dieses Projekt löschen möchten?“, darunter der Projektname, Knöpfe **Abbrechen** (Standardfokus) und **Ja**.
- „Ja“ → Dialog 2 im selben Fenster: „Bitte bestätigen Sie mit Ihren Zugangsdaten.“, die E-Mail steht schreibgeschützt da, darunter das Passwortfeld. Knöpfe **Abbrechen** und **Endgültig löschen**. Ein falsches Passwort zeigt „Passwort falsch.“ im Dialog, das Projekt bleibt.
- „Abbrechen“ geht auf beiden Stufen; beim erneuten Öffnen beginnt der Dialog wieder bei Stufe 1, Passwort und Meldung sind geleert.
- Rot, aber warm: Fläche 22 % `--danger` in `--bg` gemischt, Rahmen 2 px `--danger` (70 %) mit Leuchten (48 px, 35 %), Titel in `--danger` (1,55 rem), Löschknopf in `--danger` mit Glanz und farbigem Schatten. Hintergrund hinter dem Dialog abgedunkelt und unscharf.
- Gelöscht wird endgültig (kein Papierkorb für Projekte). Der Server verlangt immer das Passwort und prüft, dass das Projekt dem Nutzer gehört.

**Token-Anzeige (unten)**
- Balken (10 px hoch, voll rund, Akzentverlauf), darüber links „Geschätztes Token-Kontingent“, rechts „Noch keine Messdaten“. Breite höchstens 560 px, mittig.
- **Ist:** Der Balken ist leer, es gibt noch keine Messung. Angebunden wird er mit dem Runner (Phase 2).

**Dialoge allgemein (`.dialog`):** höchstens 440 px, Rundung 28 px, Fläche 82 % `--bg` mit Weichzeichner, gleiche Lichtkante wie Glas, federnde Einblendung (0,45 s). Knöpfe in Dialogen sind gleich breit nebeneinander (Höhe 48 px). Pro Dialog genau ein Hauptknopf.

**Sprache**
- Deutsch und Englisch, pro Nutzer gespeichert (`users.language`). Alle Texte stehen in `web/app/i18n.py`. **Jeder neue Text kommt in beide Sprachen.** Ein Test prüft, dass beide Wörterbücher dieselben Schlüssel haben. Die Login-Seite ist noch nur Deutsch.

**Projektseite:** Platzhalter mit Projektname und „Hier entsteht das Kanban-Board.“, darunter „← Zurück“.

## 11. Umsetzung

- `web/app/static/theme.css`: alle Werte als Variablen, alle Komponenten.
- `web/app/static/theme.js`: Umschalter und Formularmeldungen (Texte kommen vom Server über `data-msg-*`). Keine Abhängigkeit, kein Framework.
- `web/app/static/dashboard.js`: Begrüßung, Einstellungsleiste, Dialoge, Löschablauf, Drag and Drop.
- `web/app/layout.py`: `page(title, body, lang, top_right, scripts)` ist die gemeinsame Hülle mit Meta-Tags, Inline-Skript für das Theme, Farbflächen, Kopfleiste und Umschalter. **Neue Seiten nutzen `page()`**, damit der Umschalter überall da ist. `fill()` setzt `%NAME%`-Platzhalter in einem Durchgang ein (Nutzertext kann so nichts einschleusen).
- `web/app/dashboard.py`: HTML von Dashboard, Einstellungsleiste und Projektseite. `web/app/i18n.py`: Texte. `web/app/projects.py`: Projekte in SQLite.
- Reines CSS und JavaScript ohne Bibliotheken (Standardbibliothek zuerst, siehe CLAUDE.md), neue Abhängigkeiten nur nach Begründung.
- Einbindung: `/static` wird von FastAPI (`StaticFiles`) ausgeliefert; nach Änderungen an Dateien im Ordner `static` muss der Web-Container neu gebaut werden (`docker compose up -d --build web`).

## 12. Noch offen (Janis entscheidet bei Bedarf)

- Handy-Layout prüfen (Abschnitt 8). Drag and Drop nutzt die Browser-Funktion und geht auf Touchgeräten noch nicht; per Tastatur lässt sich auch noch nicht umordnen.
- **Gewünscht (Janis, 07.11.2026), nach dem Kanban-Board:** Kacheln auf eine andere Seite ziehen, wie Apps auf dem Handy. Zieht man eine Kachel an den rechten Rand, blättert die Ansicht zur nächsten Seite, ist keine da, geht eine neue auf; am linken Rand zurück. Beispiel: Drei Projekte gehören zu einer Kategorie, das vierte soll auf die nächste Seite. Leere Plätze bleiben immer am Ende, sie müssen nicht umgeordnet werden. Bis dahin lassen sich Kacheln nur innerhalb einer Seite ordnen (mit der Maus geprüft, Touch ungeprüft).
- Begrenzung falscher Passworteingaben (Anmeldung und Löschen), steht auch in der Checkliste vor dem Livegang.
- Login-Seite auf Englisch (erst nach der Anmeldung ist die Sprache bekannt).
- Inhalt der Kacheln („weitere Infos“) wird später festgelegt.
- Kontrastmessung aller Farbpaare (Abschnitt 2).
- Schriftcharakter: reine Systemschrift oder eine warme Serifenschrift für Überschriften.
- Hauptgerät (Mac/PC oder Handy) bestimmt, wie viel Aufwand das Handy-Layout bekommt.
- Passwort zurücksetzen: Link ist nur Platzhalter, das Modul folgt später.
