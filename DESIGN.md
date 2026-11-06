# Agent-Hub – Designrichtlinien

Stand: 07.11.2026 · Entscheidungen von Janis. Zahlen sind Startwerte und werden am echten Bildschirm feinjustiert. Änderungen an dieser Datei sind Designentscheidungen und gehören Janis.

## 1. Leitidee

Zwei Welten gemischt, nicht Apple in Reinform:
- **Von Apple:** runde Glasoptik, Symmetrie, Schatten und Lichtspiele, flüssige Bewegung. Hier 100 % Apple-Niveau, Grundlage ist der Skill `apple-design` (`.claude/skills/apple-design/SKILL.md`) und die Apple Human Interface Guidelines.
- **Von Claude:** warme, ruhige Farben, kein kaltes Weiß, viel Luft.

## 2. Farben

Nie reines Weiß oder reines Schwarz. Flächen sind warm getönt, Richtung Aprikose.

| Rolle | Hell | Dunkel |
|---|---|---|
| Hintergrund | `#EFDCC6` | `#1F1713` |
| Glasfläche | `rgba(247, 221, 196, 0.5)` | `rgba(66, 46, 36, 0.45)` |
| Eingabefeld | `rgba(222, 170, 125, 0.28)` | `rgba(20, 12, 8, 0.4)` |
| Text | `#3A2A20` | `#F6E6D8` |
| Text gedämpft | `#6F5848` | `#BDA591` |
| Akzent (Hauptknopf) | `#E8845A` | `#F29A72` |
| Fehler | `#A63A1F` | `#FF9B7E` |

- Der helle Stil ist bewusst gedämpft: Der erste Entwurf (`#FFF1E3`) wirkte zu grell. Heller als die Werte oben wird er nicht.

- Alle Werte als CSS-Variablen in einer Datei (`web/app/static/theme.css`), nirgends feste Farben im Code.
- Textkontrast mindestens 4,5 : 1 (WCAG AA), auch auf Glas. Besteht ein Wert die Prüfung nicht, wird der Wert angepasst, nicht der Kontrast gesenkt.
- Fehler, Warnung und Erfolg nicht nur über Farbe, immer mit Text oder Symbol.

## 3. Glas

- Gläserne Flächen: `backdrop-filter: blur(28px) saturate(1.6)`, halbtransparente Füllung und ein weicher, zweilagiger Schatten.
- **Lichtkante:** Statt eines flachen Rands eine feine Kante (1,5 px), die oben links und unten rechts Licht fängt (Verlauf, per Maske nur am Rand).
- **Farbflächen dahinter:** Drei weiche, stark verschwommene Farbflächen treiben sehr langsam hinter dem Glas (Unschärfe 70 px, Deckkraft 0,3–0,36). Sie machen den Glaseffekt sichtbar, dürfen aber nie auffallen. Die beiden großen in den Ecken bleiben bewusst unauffällig.
- Glas sparsam: Kopfleiste, Kacheln, Dialoge. Nicht jedes Element.
- Rückfall: Fehlt `backdrop-filter` oder ist „Transparenz reduzieren“ aktiv (`prefers-reduced-transparency`), wird die Fläche deckend in derselben Farbe.

## 4. Formen und Knöpfe

- Weiche, große Rundungen: Knöpfe und Felder 16 px, Karten und Dialoge 28 px, runde Symbolknöpfe voll rund.
- Hauptknopf: Akzentfarbe mit Glanz oben (heller Verlauf), farbigem Schatten und feiner Lichtkante innen. Hover hebt ihn leicht an, Klick drückt ihn federnd ein.
- Nebenaktionen (z. B. „Passwort vergessen?“) sind dezente Textlinks ohne Kasten, zentriert unter dem Hauptknopf. Noch nicht gebaute Funktionen werden ausgegraut und mit „Kommt später“ beschriftet.
- **Wenige, große Schaltflächen** statt vieler kleiner. Mindestgröße 44 × 44 px.
- Ein Knopf zeigt **entweder Symbol oder Text**. Beides nur als Ausnahme, wenn es Missverständnisse verhindert (z. B. „Endgültig löschen“ mit Symbol).
- Pro Ansicht genau ein Hauptknopf (Akzentfarbe). Alles andere ist zurückhaltend.
- Löschen und Verwerfen sind nie die Hauptfarbe und brauchen eine Bestätigung.

## 5. Hell und Dunkel

- Zwei Stile, Umschalter **in der Kopfleiste auf jeder Seite**, auch auf der Login-Seite. Immer sichtbar, ein Klick.
- Erststart folgt der Geräteeinstellung (`prefers-color-scheme`); die Wahl wird im Browser gespeichert (`localStorage`) und gilt danach für alle Seiten.
- Kein Aufblitzen beim Laden: Das Theme wird vor dem ersten Zeichnen gesetzt (kleines Inline-Skript im `<head>`).

## 6. Bewegung

- Kurz und federnd, Bewegung folgt dem Finger oder der Maus. Details im Skill `apple-design`.
- Karten blenden beim Laden federnd ein (ca. 0,7 s, leichtes Überschwingen).
- Farbflächen im Hintergrund driften sehr langsam (24–38 s), nur als ruhiges Hintergrundleben.
- `prefers-reduced-motion` wird immer beachtet: dann nur Einblenden, keine Bewegung.

## 7. Symmetrie und Raster

- 8-px-Raster für Abstände. Gleiche Abstände links/rechts und oben/unten innerhalb einer Fläche.
- Ein Inhaltsbereich mit begrenzter Breite (ca. 1200 px), auf kleinen Bildschirmen eine Spalte.

## 8. Formulare

- **Keine Browser-Blasen** („Bitte füllen Sie dieses Feld aus“): Formulare bekommen `novalidate`, Meldungen erscheinen im Design direkt unter dem Feld in Fehlerfarbe, kurz und deutsch („Bitte ausfüllen.“), das Feld bekommt roten Rand mit Glow. Die Meldung verschwindet beim Tippen. Der Server prüft trotzdem immer selbst.
- Meldungen des Servers (z. B. „E-Mail oder Passwort falsch.“) stehen in einer getönten Box oben im Formular, nicht als lose Schrift.
- Fokus: Rand in Akzentfarbe plus weicher Ring (4 px), Cursor in Akzentfarbe.
- Platzhalter blass (z. B. `name@beispiel.de`). Autofill des Browsers bekommt den Ton der Seite statt Gelb oder Blau.
- `color-scheme` wird mit dem Stil gesetzt, damit Browser-Elemente (Vorschläge, Scrollbalken) passen.
- Seiten tragen eine kurze Überschrift mit freundlicher Unterzeile („Willkommen zurück.“).

## 9. Technik

- Reines CSS mit Variablen, kein Framework (Standardbibliothek zuerst, siehe CLAUDE.md).
- Systemschrift (`system-ui`), keine Webfonts, damit Pi und Ladezeit schlank bleiben.

## 10. Umsetzung

- Alle Werte stehen als Variablen in `web/app/static/theme.css`, der Umschalter und die Formularmeldungen in `web/app/static/theme.js`, die gemeinsame Seitenhülle (Kopfleiste, Umschalter) in `page()` in `web/app/main.py`. Neue Seiten nutzen `page()`.
- Login-Seite ist der Referenzentwurf (Stand 07.11.2026, von Janis abgenommen).

## 11. Noch offen (Janis entscheidet bei Bedarf)

- Handy-Layout (noch nicht geprüft).
- Schriftcharakter: reine Systemschrift oder eine warme Serifenschrift für Überschriften.
- Hauptgerät (Mac/PC oder Handy) bestimmt, wie viel Aufwand das Handy-Layout bekommt.
