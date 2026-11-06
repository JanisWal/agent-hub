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
| Hintergrund | `#FFF1E3` | `#1F1713` |
| Glasfläche | `rgba(255, 232, 208, 0.62)` | `rgba(66, 46, 36, 0.55)` |
| Text | `#3A2A20` | `#F6E6D8` |
| Akzent (Hauptknopf) | `#E8845A` | `#F29A72` |

- Alle Werte als CSS-Variablen in einer Datei (`web/app/static/theme.css`), nirgends feste Farben im Code.
- Textkontrast mindestens 4,5 : 1 (WCAG AA), auch auf Glas. Besteht ein Wert die Prüfung nicht, wird der Wert angepasst, nicht der Kontrast gesenkt.
- Fehler, Warnung und Erfolg nicht nur über Farbe, immer mit Text oder Symbol.

## 3. Glas

- Gläserne Flächen: `backdrop-filter: blur(20px) saturate(1.4)`, halbtransparente Füllung, feiner heller Rand (1 px) und weicher Schatten.
- Glas sparsam: Kopfleiste, Kacheln, Dialoge. Nicht jedes Element.
- Rückfall: Fehlt `backdrop-filter` oder ist „Transparenz reduzieren“ aktiv (`prefers-reduced-transparency`), wird die Fläche deckend in derselben Farbe.

## 4. Formen und Knöpfe

- Weiche, große Rundungen: Knöpfe 14–16 px, Kacheln 22–24 px, Dialoge 28 px.
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
- `prefers-reduced-motion` wird immer beachtet: dann nur Einblenden, keine Bewegung.

## 7. Symmetrie und Raster

- 8-px-Raster für Abstände. Gleiche Abstände links/rechts und oben/unten innerhalb einer Fläche.
- Ein Inhaltsbereich mit begrenzter Breite (ca. 1200 px), auf kleinen Bildschirmen eine Spalte.

## 8. Technik

- Reines CSS mit Variablen, kein Framework (Standardbibliothek zuerst, siehe CLAUDE.md).
- Systemschrift (`system-ui`), keine Webfonts, damit Pi und Ladezeit schlank bleiben.

## 9. Noch offen (Janis entscheidet nach dem ersten Entwurf)

- Endgültiger Akzentton (die Werte oben sind ein Vorschlag).
- Schriftcharakter: reine Systemschrift oder eine warme Serifenschrift für Überschriften.
- Hauptgerät (Mac/PC oder Handy) bestimmt, wie viel Aufwand das Handy-Layout bekommt.
