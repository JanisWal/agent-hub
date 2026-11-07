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

- Kurz, federnd, ruhig. Grundlage ist der Skill `apple-design` (Apple, „Designing Fluid Interfaces“).
- **Alles, was man anfassen kann, bewegt sich mit Federn** (`web/app/static/motion.js`, ohne Bibliothek), nicht mit festen Dauern. Eine Feder hat zwei Werte, Dämpfung und Reaktionszeit, und hat keine feste Dauer:
  - **Verschieben und Seitenwechsel** (`MOVE`): Dämpfung 1,0, Reaktionszeit 0,4 s, kein Überschwingen. Gemessen: Seitenwechsel per Punkt kommt nach etwa 0,7 s an, ohne Überschwingen.
  - **Anheben** (`LIFT`): Dämpfung 1,0, Reaktionszeit 0,25 s.
  - **Nach einem Wisch** (`SNAP`): Dämpfung 0,85, Reaktionszeit 0,35 s, etwas Nachschwingen (gemessen 3 px), **nur weil die Geste Schwung hatte**.
  - **Neigung der getragenen Kachel** (`LEAN`): Dämpfung 0,7, Reaktionszeit 0,35 s, schwingt hin und zurück, weil die Neigung ein Bewegungsimpuls ist (Hinweis in Richtung der Geste).
- **Jede Bewegung startet vom Wert, der gerade zu sehen ist** und lässt sich jederzeit unterbrechen oder umkehren (greift man die Bahn mitten in der Bewegung, folgt sie dem Finger). Die Geschwindigkeit der Geste wird an die Feder übergeben, damit zwischen Ziehen und Gleiten kein Ruck entsteht. X und Y laufen als getrennte Federn.
- Es werden nur `transform` und `opacity` animiert. Das Schweben beim Darüberfahren nutzt die CSS-Eigenschaft `translate`, damit es sich nicht mit den Federn (`transform`) beißt. Der Einblend-Zustand der Karten ist `backwards`, damit er nach dem Ende nicht mehr über die Feder bestimmt.
- Karte beim Laden (`rise`): 0,7 s, `cubic-bezier(0.3, 1.25, 0.5, 1)` (leichtes Überschwingen), von 14 px tiefer, Skalierung 0,97 und unsichtbar zu normal.
- Fehlermeldung unter dem Feld (`fade`): 0,2 s, von 3 px höher und unsichtbar zu normal.
- Felder: Rand und Ring blenden in 0,2 s um. Textlink: Farbe und Unterstreichung 0,2 s.
- Hintergrund-Farbflächen driften sehr langsam (siehe Abschnitt 3), nur als ruhiges Hintergrundleben.
- `prefers-reduced-motion: reduce` wird beachtet, **Ist:** dann entfallen **alle** Übergänge und Animationen, auch das Einblenden, und die Federn springen sofort auf ihr Ziel (nichts bewegt sich, alles steht sofort).
- **Seiten und Ziehen** haben eigene Regeln, siehe Abschnitt 10 („Seitenband“, „Ziehen“).

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
- **Handy-Ansicht (≤ 560 px, geprüft bei 390 px Breite in Chrome, 07.11.2026):** Außenabstand 16 px, Kopfleiste 12 × 16 px. Das Dashboard zeigt **2 Spalten × 3 Reihen** kompakter Kacheln (Reihenhöhe mindestens 132 px, Abstand 14 px, Innenabstand 16 px, Rundung 22 px, Name 1,1 rem, höchstens 3 Zeilen). Eine Seite passt damit ohne Scrollen auf den Bildschirm. Plus-Zeichen 44 px, Einstiegstext 0,85 rem. Das Zahnrad (Schublade) bekommt auf dem Handy eine Glasfläche mit Rand, weil es beim Scrollen über dem Inhalt schwebt; 8 px Abstand zum Rand. Die Beschriftung der Token-Anzeige darf umbrechen. Bis 1000 px bilden die Stationen eine wischbare Zeile (kein Umbruch, ohne Scrollbalken). Die Schublade ist so breit wie das Fenster abzüglich 96 px, höchstens 320 px.
- **Nicht geprüft am echten Gerät:** Berührung. Geprüft wurde in Chrome mit einem 390 px breiten Rahmen (Layout) und mit **selbst gesendeten Zeigerereignissen** (Berührung, Wisch, langes Drücken), nicht an einem Handy.

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

**Einstellungs-Schublade (oben rechts, auf jeder angemeldeten Seite)** (neu gestaltet am 07.11.2026, ersetzt die frühere Pille)
- **Geschlossen:** nur ein dezentes Zahnrad (22 px) mit einem Pfeil nach links daneben (18 px), beide in `--muted`, ohne Kasten, 12 px von Rand und Oberkante. Beim Darüberfahren `--text`.
- **Öffnen:** Ein Klick zieht den Kasten weich aus der rechten oberen Ecke heraus (0,55 s, federnd). Zahnrad und Pfeil hängen links am Kasten und fahren mit, der Pfeil dreht sich dabei um 180° (zeigt dann nach rechts = zurückschieben). Der Kasten blendet dabei ein (0,3 s) und ist im geschlossenen Zustand unsichtbar und nicht anwählbar.
- **Kasten:** Glas, Breite `min(320 px, 100 vw − 96 px)`, Rundung 24 px, Innenabstand 20 px, 12 px von Rand und Oberkante, höchstens so hoch wie das Fenster (dann scrollbar). Schließt bei Klick daneben und mit Escape.
- **Einheitliche Einträge:** Jeder Eintrag ist derselbe Block (`.setting`): Feldfarbe, Rand 1 px, Rundung 16 px, Innenabstand 10 × 14 px, oben kleine Beschriftung (0,78 rem, `--muted`), darunter der Wert (1 rem, Gewicht 600), 8 px Abstand zwischen Blöcken. Fokus: Rand `--accent` und Ring 4 px am ganzen Block.
  1. **Nutzername** (Textfeld, höchstens 40 Zeichen; als Platzhalter steht der aktuell gezeigte Name).
  2. **Sprache** als Dropdown („Deutsch“ / „English“) mit eigenem Pfeil rechts.
  3. **Claude** und 4. **ChatGPT**: Name als Beschriftung, darunter ein Statuspunkt mit „Nicht verknüpft“ bzw. „Verknüpft“ (Punkt in Akzentfarbe, Text in `--text`). Nicht verknüpft: rechts daneben der Textlink „Verknüpfen“ (ausgegraut, „Kommt später“). Ist ein Dienst verknüpft, steht nur „Verknüpft“ da. **Ist:** Der Zustand ist fest „nicht verknüpft“, echt wird er mit dem Runner (Phase 2).
- **Besonders bleiben:** **Speichern** (Hauptknopf, volle Breite) und **Abmelden** (dezenter Textlink darunter, mittig).

**Projektkacheln (Mitte)**
- Raster 3 Spalten × 2 Reihen, Abstand 24 px, Reihenhöhe mindestens 190 px, **6 Kacheln pro Seite**. Unter 900 px Breite 2 Spalten; auf dem Handy (unter 560 px) ebenfalls 2 Spalten, aber kompakter (siehe Abschnitt 8).
- Projektkachel: Glas, Innenabstand 24 px, Projektname groß unten links (1,5 rem, Gewicht 650, höchstens 3 Zeilen), weitere Infos folgen später. Die ganze Kachel ist ein Link zum Projekt (**ohne** Anmeldeabfrage). Beim Darüberfahren hebt sie sich um 3 px. Beim Laden blenden die Kacheln gestaffelt ein (70 ms Versatz).
- **Löschknopf:** kleiner runder Knopf oben rechts in der Kachel (sichtbar 36 px, Klickfläche 44 px), Mülleimer-Symbol, Farbe `--muted`, beim Darüberfahren `--danger`.
- **Plus-Kachel:** Auf der ersten Seite mit freiem Platz zeigt der nächste freie Platz ein großes Plus (56 px, Akzentfarbe, 70 % Deckkraft, gestrichelter Rand, helle Fläche). Beim Darüberfahren wird sie kräftiger und das Plus dreht sich um 90°. Klick öffnet „Neues Projekt“ (Name, Anlegen, Abbrechen).
- **Einstiegstext:** Auf der Plus-Kachel oben links steht „Beginne mit deinem ersten Projekt“, solange der Nutzer noch nie ein Projekt hatte (`users.had_project`). Er kommt nach dem Löschen des letzten Projekts **nicht** zurück.
- **Leere Plätze** sind nur zarte gestrichelte Umrisse (55 % Deckkraft), damit das Raster bestehen bleibt. Sie sind nicht klickbar.
- **Drag and Drop wie auf der Handy-Startseite** (Janis, 07.11.2026): Nur belegte Kacheln lassen sich ziehen, Plus und leere Plätze bleiben stehen (leere Plätze sind immer das Ende einer Seite, man muss sie nicht ordnen). Plus und leere Plätze werden währenddessen ausgeblendet (Deckkraft 0, bleiben aber als Ablageziel).
  - **Ziehen (Maus, Stift, Finger):** Eigenes Ziehen mit Zeigerereignissen, nicht die Browser-Funktion, damit es auch per Finger geht. Eine Maus beginnt nach 5 px Bewegung, ein Finger nach **380 ms Drücken** (Bewegt er sich vorher mehr als 10 px, ist es ein Wisch oder Scrollen, kein Tragen; dazu kurzes Vibrieren auf Geräten, die es können). Die Kachel wird als **Klon über allem** getragen: Sie wächst auf 1,05 (Feder `LIFT`) mit tieferem Schatten (`0 34px 70px`) und dichterer Glasfläche, hängt **1:1 am Zeiger und behält den Abstand zum Griffpunkt**. Sie **neigt sich bis zu 6° in die Bewegungsrichtung** (Feder `LEAN`: Dämpfung 0,7, Reaktionszeit 0,35 s, schwingt in Ruhe zurück). Ihr Platz bleibt reserviert und ist als **Lücke sichtbar**: gestrichelter Rahmen in Akzentfarbe (1,5 px, 55 %) mit leichter Akzentfläche (9 %), ohne Schatten und ohne Inhalt. So sieht man, wo die Kachel landet.
  - **Gezielt tauschen:** Ausschlaggebend ist die **Mitte der getragenen Kachel**, nicht der Zeiger. Getauscht wird nur, wenn diese Mitte im **inneren Bereich** einer anderen Kachel liegt (20 % Rand links/rechts und 22 % oben/unten zählen nicht), ein Streifen am Rand tauscht nichts. Außerdem nur, wenn die Bewegung **langsamer als 700 px/s** ist: Wer schnell über andere Kacheln fliegt, tauscht nichts, sobald die Bewegung ruhiger wird (nach 130 ms), geschieht der Tausch von selbst.
  - **Die anderen machen Platz:** Beim Tausch gleiten alle betroffenen Kacheln und die Lücke mit Federn (`MOVE`) an ihren neuen Ort (FLIP). Sie setzen **als Welle** ab: Je weiter eine Kachel von der Lücke entfernt ist, desto später startet sie (Entfernung/10 ms, höchstens 110 ms). Ändert sich das Ziel mitten im Gleiten, geht es von der aktuellen Position und Geschwindigkeit weiter.
  - **Loslassen:** Der Klon fliegt mit der **Geschwindigkeit der Geste** in seinen Platz und wird kleiner (Federn), danach wird er durch die echte Kachel ersetzt. Ein Klick nach dem Ziehen löst den Link nicht aus.
  - **Seitenband:** Alle Seiten liegen nebeneinander auf einer Bahn (**128 px Abstand**), die per Feder gleitet (`MOVE`), statt dass Seiten ein- und ausgeblendet werden. Der Seitenwechsel per Punkt, Pfeil, Pfeiltaste (links/rechts) oder Wisch ist also immer **dieselbe Bewegung in dieselbe Richtung** (räumliche Konsistenz). Seiten, die nicht zu sehen sind, sind nicht anwählbar (`inert`).
  - **Wischen mit dem Finger:** Die Bahn folgt dem Finger 1:1, an den Enden mit Gummiband (Formel aus dem Skill; 400 px Zug ergeben 185 px Weg). Beim Loslassen zählt die **Geschwindigkeit**: Der Ruhepunkt wird hochgerechnet (`v/1000 · 0,998/(1−0,998)`), höchstens eine Seite pro Wisch, dann gleitet die Bahn mit der Loslass-Geschwindigkeit und etwas Nachschwingen (`SNAP`) dorthin. Greift man die Bahn mitten in der Bewegung, hält sie an und folgt dem Finger.
  - **Seitenwechsel beim Ziehen:** Hält man die Kachel etwa 0,65 s am linken oder rechten Rand (Zone: 8 % der Fensterbreite, höchstens 96 px), blättert die Ansicht um. Am Rand erscheint dabei ein Farbverlauf mit Pfeil (Deckkraft 50 %, am Rand, der gerade zählt, 100 %). Hält man weiter, blättert sie weiter.
  - **Neue Seite:** Rechts hinter der letzten Seite öffnet sich eine neue leere Seite, **wenn die letzte Seite mindestens ein anderes Projekt enthält**. Wird dort nichts abgelegt, verschwindet sie wieder.
  - **Ablegen:** Auf einer Kachel setzt man vor diese, auf einem freien Platz hinter das letzte Projekt der Seite. Ist die Zielseite voll (6), schiebt sie ihr letztes Projekt an den Anfang der nächsten Seite (das kann sich über mehrere Seiten fortsetzen). Seiten ohne Projekte gibt es nicht.
  - **Speichern:** Jedes Projekt merkt sich Seite und Position (`projects.page`, `projects.position`), Seiten dürfen also nur teilweise gefüllt sein (z. B. 3 Projekte auf Seite 1, das vierte allein auf Seite 2). Wechselt die Kachel die Seite oder schiebt eine volle Seite ein Projekt weiter, lädt die Seite danach einmal neu (ohne Einblend-Animation), damit die Aufteilung vom Server kommt.
- **Mehrere Seiten:** Neue Projekte kommen auf die erste Seite mit freiem Platz, sonst auf eine neue letzte Seite. Sind alle Seiten voll, hat die letzte Seite nur das Plus. Alle Seiten stehen im Browser, Blättern lädt nichts nach. Die Adresse zeigt die Seite (`?page=2`). Bei nur einer Seite ist die Seitenanzeige ausgeblendet.
  - **Seitenanzeige mit Physik:** Unter dem Raster stehen kleine Punkte (10 px, Abstand 24 px, Klick springt zur Seite) und links/rechts je ein dezentes Dreieck (44 px Klickfläche, am Rand ausgegraut). Die **aktuelle Seite ist ein Wurm** in Akzentfarbe (10 px hoch, leichtes Leuchten), der **an der Position der Bahn hängt**: Er folgt also dem Finger 1:1, gleitet beim Seitenwechsel mit der Feder und streckt sich dabei zwischen zwei Punkten (bis etwa 26 px; erst läuft das vordere Ende, dann folgt das hintere). An den Enden schwingt er beim Gummiband ein Stück über den letzten Punkt hinaus. Punkte und Pfeile geben beim Drücken sofort nach und federn zurück (Skalierung 0,65 bzw. 0,75, Rückfeder mit Überschwingen, 0,4 s). Die Pfeile **lehnen sich bis 7 px in die Laufrichtung der Seiten** und setzen sich ab, wenn die Bahn ruht (ihre Geschwindigkeit wird aus der Bahn gelesen).
  - **Schatten:** Die Kachelschatten (`0 18px 50px`) reichen etwa 50 px seitlich, 32 px nach oben und 68 px nach unten. Das Seitenband beschneidet seinen Inhalt, deshalb hat es innen Platz dafür (72 px seitlich, 48 px oben, 96 px unten; auf dem Handy 16 px seitlich bei weicherem, engerem Schatten `0 8px 22px`). Die Seiten liegen 128 px auseinander, damit keine Nachbarseite oder ihr Schatten in diesen Rand hineinragt. `main` schneidet seitlich am Fensterrand ab (`overflow-x: clip`), damit die Seite nie seitlich scrollt.

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

## 10b. Projektseite und Kanban-Board

Stand 07.11.2026, von Janis beauftragt, in Chrome mit Testkonto geprüft (Anlegen, Umbenennen, Spaltenwechsel per Maus, Akzeptieren, Ablehnen, Papierkorb, endgültig Löschen, Leeren).

**Aufbau:** Links die Stationen (`.stations`, Glas, 210 px breit), rechts Projektname als große Überschrift (`clamp(1.8rem, 4vw, 2.6rem)`), oben rechts der Papierkorb-Knopf, darunter die drei Spalten. Der Inhalt ist **oben ausgerichtet** (springt nicht, wenn sich die Höhe ändert), Breite höchstens 1280 px. Unter 1000 px Breite stehen die Stationen als Zeile oben und die Spalten untereinander.
- **Stationen:** „← Alle Projekte“ (Link zum Dashboard), **Board** (aktiv, Akzentfläche 30 %), „Agenten“, „Dateiablage“, „Dokumentation“ (ausgegraut, „Kommt später“).
- **Spalten (`.column`, Glas, Rundung 24 px):** **Bugs**, **Kleine Updates**, **Major Updates**. Kopf: Name, Zähler (Anzahl der Punkte inkl. Vorschläge, aktualisiert sich beim Verschieben) und ein runder Plus-Knopf (36 px, Klickfläche 44 px, Akzentfarbe).
- **Punkte (`.card`):** kleine Karten (Feldfarbe, Rundung 16 px, Titel Gewicht 600). Von Hand angelegte Punkte gelten als zugestimmt und stehen **oben** (neuester zuerst). Beim Darüberfahren erscheint rechts ein kleiner Papierkorb-Knopf, die Karte hebt sich 2 px.
- **Claude-Vorschläge:** unter einer kleinen Zwischenzeile („Vorschläge von Claude“, Großbuchstaben, 0,74 rem) **unten** in der Spalte, mit gestricheltem Akzentrand und ohne Füllung. Rechts zwei runde Knöpfe: **Haken** (Akzeptieren, Akzentrand) und **Kreuz** (Ablehnen, beim Darüberfahren `--danger`). Akzeptierte Vorschläge landen unter den zugestimmten Punkten, abgelehnte im Papierkorb. Vorschläge lassen sich nicht ziehen.
- **Papierkorb:** standardmäßig zu. Der runde Knopf oben rechts (48 px, Mülleimer, kleiner Zähler) klappt ihn als Glasfläche über den Spalten auf, der Zustand bleibt beim Neuladen erhalten. Jede Zeile zeigt Titel und Spalte, rechts **Wiederherstellen** (Pfeil zurück) und **X** (endgültig löschen). Darunter der Textlink **Papierkorb leeren**. Leer: „Der Papierkorb ist leer.“
- **Wiederherstellen:** Von Hand angelegte Punkte kommen als zugestimmt zurück (oben), Claude-Vorschläge warten wieder auf Entscheidung.
- **Bestätigung bei endgültigem Löschen** (X und „Papierkorb leeren“): kleiner roter Dialog mit „Abbrechen“ (Standardfokus) und „Ja“, **ohne Passwort** (das bleibt Projekten vorbehalten).
- **Anlegen und Umbenennen:** Plus-Knopf öffnet den Dialog „Neuer Punkt“ (Titel, höchstens 200 Zeichen). Doppelklick auf einen Punkt öffnet „Punkt bearbeiten“ mit vorausgefülltem Titel. Leere Titel zeigen „Bitte ausfüllen.“
- **Drag and Drop:** Zugestimmte Punkte lassen sich innerhalb einer Spalte ordnen und **in eine andere Spalte ziehen** (der Punkt wechselt dann die Art). Es gilt dasselbe Ziehen wie bei den Kacheln (Abschnitt 10): Maus, Stift oder Finger (langes Drücken), die Karte wird als Klon angehoben (Schatten, Größe 1,05), hängt 1:1 am Zeiger, die anderen Karten gleiten per Feder beiseite, und beim Loslassen landet sie mit der Geschwindigkeit der Geste. Leere Spalten nehmen Karten ebenfalls an. Die Reihenfolge wird sofort gespeichert.
- Nach Aktionen lädt die Seite neu, **ohne** die Einblend-Animation zu wiederholen (Merker `noanim` in `sessionStorage`).
- Texte und Berechtigungen: alle Texte in Deutsch und Englisch (`i18n.py`), jeder Zugriff prüft, dass das Projekt dem Nutzer gehört.

**Marke „Agent-Hub“ oben links:** ist ein Link zum GitHub-Repo (`https://github.com/JanisWal/agent-hub`), öffnet in neuem Tab (`rel="noopener noreferrer"`), beim Darüberfahren unterstrichen. Gilt auf allen Seiten, auch beim Login.

## 11. Umsetzung

- `web/app/static/theme.css`: alle Werte als Variablen, alle Komponenten.
- `web/app/static/theme.js`: Umschalter und Formularmeldungen (Texte kommen vom Server über `data-msg-*`). Keine Abhängigkeit, kein Framework.
- `web/app/static/dashboard.js`: Begrüßung, Einstellungs-Schublade, Dialoge, Löschablauf, Drag and Drop der Kacheln.
- `web/app/static/board.js`: Kanban-Board (Anlegen, Umbenennen, Akzeptieren, Papierkorb, Drag and Drop zwischen Spalten). Nur auf der Projektseite geladen.
- `web/app/layout.py`: `page(title, body, lang, top_right, scripts)` ist die gemeinsame Hülle mit Meta-Tags, Inline-Skript für das Theme, Farbflächen, Kopfleiste und Umschalter. **Neue Seiten nutzen `page()`**, damit der Umschalter überall da ist. `fill()` setzt `%NAME%`-Platzhalter in einem Durchgang ein (Nutzertext kann so nichts einschleusen).
- `web/app/dashboard.py`: HTML von Dashboard und Einstellungs-Schublade. `web/app/projectpage.py`: HTML der Projektseite mit Board. `web/app/i18n.py`: Texte. `web/app/projects.py`: Projekte, `web/app/board.py`: Board-Punkte (beides SQLite). Die Claude-Vorschläge legt später der Agenten-Code mit `board.create_suggestion()` an.
- Reines CSS und JavaScript ohne Bibliotheken (Standardbibliothek zuerst, siehe CLAUDE.md), neue Abhängigkeiten nur nach Begründung.
- Einbindung: `/static` wird von FastAPI (`StaticFiles`) ausgeliefert; nach Änderungen an Dateien im Ordner `static` muss der Web-Container neu gebaut werden (`docker compose up -d --build web`).

## 12. Noch offen (Janis entscheidet bei Bedarf)

- **Berührung:** Ziehen und Wischen per Finger sind gebaut und mit selbst gesendeten Zeigerereignissen geprüft (Wisch mit Schwung, Gummiband, langes Drücken, Tragen über Spalten und Seiten). **Am echten Handy nicht geprüft**, besonders das Verhalten von iPhone-Safari (Scroll-Sperre beim Tragen, Kontextmenü beim langen Drücken). Umordnen per Tastatur gibt es noch nicht (nur Pfeiltasten für Seiten).
- Die Federn wurden in einem Fenster geprüft, in dem Chrome `requestAnimationFrame` pausiert (Test-Fenster ist minimiert); dort wurde der Takt durch einen 16-ms-Zeitgeber ersetzt. Die Werte (Ziel, kein Überschwingen, Dauer) stimmen, die **gefühlte Flüssigkeit** muss Janis in einem sichtbaren Fenster beurteilen.
- Handy-Layout am echten Gerät prüfen (Abschnitt 8, bisher nur am 390-px-Rahmen), dazu Aussparungen wie die iPhone-Notch (`safe-area-inset`).
- Seitenwechsel beim Ziehen ist gebaut (Abschnitt 10). Ungeprüft: Touch auf dem Handy, ein Ziehen mit der Tastatur und das Verhalten bei sehr vielen Seiten (Punkte am Rand, wenn es über 15 sind).
- Begrenzung falscher Passworteingaben (Anmeldung und Löschen), steht auch in der Checkliste vor dem Livegang.
- Login-Seite auf Englisch (erst nach der Anmeldung ist die Sprache bekannt).
- Board: Punkte per Tastatur ordnen, Touch, weitere Infos pro Punkt (Beschreibung, Priorität, Freigabe durch Janis laut PROJEKT.md) und die Agenten-Bugs folgen später.
- Inhalt der Kacheln („weitere Infos“) wird später festgelegt.
- Kontrastmessung aller Farbpaare (Abschnitt 2).
- Schriftcharakter: reine Systemschrift oder eine warme Serifenschrift für Überschriften.
- Hauptgerät (Mac/PC oder Handy) bestimmt, wie viel Aufwand das Handy-Layout bekommt.
- Passwort zurücksetzen: Link ist nur Platzhalter, das Modul folgt später.
