# Agent-Hub – Mails: Wissen, Regeln, Stand

Stand: 16.11.2026 · Zweck: alles, was wir über HTML-Mails in den verschiedenen Mailprogrammen herausgefunden haben, damit es beim Bau neuer Mails und später bei **Skins** (auch für Mails) nicht verloren geht. Code: `web/app/mailtext.py` (Regeln dort oben, nummeriert), Versand `web/app/mail.py` (Resend), Texte `web/app/i18n.py` (`mail_*`), Tests `web/tests/test_resets.py`, Vorschau `web/tests/preview_mail.py`. Gestaltung kurz: DESIGN.md 10c. Verlauf: PROJEKT.md Abschnitt 12 (`mail-glass`, `mail-contrast`, `mail-caps`, `mail-rebuild`, `mail-outlook-dark`, `mail-yahoo-width`).

Quellen: eigene Bildschirmfotos von Janis (15./16.11.2026, iPhone und Mac), die Tabellen von [caniemail.com](https://www.caniemail.com) (API-Stand 16.09.2026, Rohdaten mit `curl https://www.caniemail.com/api/data.json`), [Parcel: Guide to dark mode](https://parcel.io/guides/dark-mode), [hteumeuleu: Outlook.com dark mode](https://www.hteumeuleu.com/2021/emails-react-outlook-com-dark-mode/), [Litmus: Dark mode](https://www.litmus.com/blog/the-ultimate-guide-to-dark-mode-for-email-marketers). Vendor-Quellen widersprechen sich oft; **eigene Tests gehen vor**.

## 1. Die Regeln in Kürze

1. **Keine Bilder, auch keine Hintergrundbilder.** Yahoo lässt im Dunkelmodus jede Zelle mit Bild oder Hintergrundbild unverändert, während es den Rest abdunkelt (helle Flecken in dunkler Karte). Viele Programme blockieren Bilder (Outlook für Windows standardmäßig, Yahoo im Spam), und Mail-Proxys (Apple, Gmail) behalten Bilder lange unter ihrer Adresse. Die Mail ist nur Text und Farbe.
2. **Alles Nötige inline.** Tabellen mit `role="presentation"`, `bgcolor` und Inline-Stile. `<style>` nur für Zugaben; ohne `<style>` (Gmail mit fremden Konten, GMX und WEB.DE im Browser) muss die Mail vollständig sein.
3. **Hell ist die Grundlage, Dunkel folgt dem Mailprogramm des Lesers** (`prefers-color-scheme` und `color-scheme: light dark`). Der Stil, den jemand auf der Seite gewählt hat, spielt keine Rolle (die Kopie auf dem Server ist seit 16.11.2026 entfernt).
4. **Farben, die jedes Umfärben überstehen:** kein reines Weiß oder Schwarz; Knopf mit **hellem Text auf dunklerem Orange** (`#B05530` / `#FFF6EE`), weil Umfärben dunklen Text aufhellt, das Orange aber oft lässt; Kontrast mindestens 4,5 : 1 in jedem Stil (Test).
5. **Glas und Glow nur als CSS-Zugabe**, immer mit fester Farbe darunter. Verläufe (Glanz, Farbfelder) nur hinter `[class~="…"]`, das Yahoo nicht versteht.
6. **Eigene `<style>`-Blöcke je Art**: Glas, Verläufe, Hell/Dunkel (nur Klassen-Selektoren), dunkle Farbfelder, Outlook-Regeln. Ein Programm, das einen Block verwirft, behält die anderen.
7. **Outlook für Windows** bekommt einen Block nur für sich (`<!--[if mso]>`): Arial, 96 dpi, Rand in Hex. Alle anderen Blöcke stehen in `<!--[if !mso]><!-->`.
8. **Umbruch ohne CSS:** `<wbr>` im angezeigten Link und in der Begrüßung (Yahoo kennt weder `word-break` noch `overflow-wrap`).
9. **Kleinigkeiten:** `!important` klein und mit Leerzeichen davor; `rgba` nur mit Kommas; keine CSS-Kommentare in `<style>`; Knopftext in einem `span` im Link; unsichtbarer Vorschautext; Mail weit unter 102 KB (Gmail kürzt darüber, unsere ≈ 7 KB); jeder `<style>`-Block unter 16 KB.
10. **Zustellung:** Links in Mails nur aus `HUB_BASE_URL`; immer eine Textfassung mit; SPF, DKIM und DMARC der Absender-Domain gehören zur Einrichtung.

## 2. Was die Programme tun (eigene Tests zuerst)

| Programm | Hell | Dunkel | Unser Stand |
|---|---|---|---|
| **Apple Mail** (iPhone, getestet 16.11.) | unser ganzes Design: Farbfelder, Glow, Knopf im Seiten-Orange | **unser eigener dunkler Stil** über `prefers-color-scheme` | perfekt |
| **Outlook-App** (iPhone, getestet 16.11.) | wendet unsere Hell-Regeln an: Seiten-Orange, Glow, runde Karte | wendet **trotzdem die Hell-Regeln** an und färbt das Ergebnis selbst um: Seite und Karte graubraun bis oliv („vergilbt“), Knopf dunkles Rostbraun mit hellem Text. Eigene Dunkel-Regeln und `[data-ogsc]`/`[data-ogsb]` wirken nicht | lesbar, nicht steuerbar; akzeptiert |
| **Gmail-App** (iPhone, getestet 16.11.) | Grundfarben, Knopf Terrakotta mit Glanz (Verlauf ja), **kein Glow** (kein `box-shadow`) | **volle Umkehrung**: Seite und Karte olivbraun, Knopf hell mit dunkler Schrift | lesbar; akzeptiert |
| **Yahoo-App** (iPhone, getestet 15./16.11.) | Grundfarben, kein Verlauf, kein Schatten | dunkelt Hintergründe ab, hellt Texte auf; **Randfarben: dunkle werden hell, helle bleiben hell**; Zellen mit Bild oder Hintergrundbild bleiben unverändert (Grund für Regel 1) | einheitlich und lesbar; der Kartenrand erscheint als helle Linie |
| **Yahoo Web** (Mac, getestet 15./16.11.) | wie App | wie App; hellt außerdem **Linkfarben** auf (Grund für den `span` im Knopf) | langer Link sprengte die Breite (Scrollen nach allen Seiten), seit `mail-yahoo-width` mit `<wbr>` behoben |
| **Gmail Web** | – | laut Quellen keine Änderung oder volle Umkehrung (widersprüchlich) | ungetestet |
| **Gmail Android** | – | laut Quellen Teil-Umfärbung (helle Flächen dunkler, dunkler Text heller) | ungetestet |
| **Outlook.com / neues Outlook** | – | Teil-Umfärbung, markiert geänderte Elemente mit `data-ogsc` (Text), `data-ogsb` (Hintergrund), `data-ogac`/`data-ogab` (Attribute); laut caniemail auch `prefers-color-scheme` | ungetestet |
| **Outlook für Windows** (Word) | kein `border-radius`, kein Schatten, keine Verläufe, kein `rgba` | volle Umkehrung | ungetestet; eckige Ecken gewollt |
| **GMX, WEB.DE, T-Online** (Browser) | GMX/WEB.DE im Browser ohne `<style>`, ohne `border-radius`; Apps können fast alles | Apps: `prefers-color-scheme` ja | ungetestet |
| Samsung Email, Thunderbird, Proton, Fastmail | laut caniemail weitgehend modern | Samsung: `prefers-color-scheme` ja | ungetestet |

**Spam und Zustellung (geprüft 15.11.):** SPF, DKIM (für `janis-home.de` und `amazonses.com`) und DMARC bestehen (Kopfzeilen der Yahoo-Mail). Yahoo legte die ersten Mails trotzdem in den Spam (neue Domain ohne Ruf, geteilte Versandadressen von Resend), Gmail stellte in den Posteingang zu. **Im Yahoo-Spam sind Bilder und Links deaktiviert**; „Kein Spam“ markieren hilft. `rua` im DMARC-Eintrag ist nicht nötig; `p=quarantine` ändert am Spam-Urteil nichts.

## 3. Wer kann was (caniemail, Stand 09/2026, Auszug)

| Eigenschaft | Apple | Gmail | Outlook Win | Outlook Mac/iOS/Android/.com | Yahoo/AOL | GMX/WEB.DE Browser |
|---|---|---|---|---|---|---|
| `<style>` | ja | ja (nur im Kopf, nur Google-Konten) | teilweise | ja | ja | nein |
| `border-radius` | ja | ja | nein (VML) | ja | ja | nein |
| `box-shadow` | ja | nein (Apps nur fremde Konten) | nein | ja | nein | nein |
| `linear-/radial-gradient` | ja | ja | nein | nein | nein | nein |
| Hintergrundbild (CSS) | ja | ja | nein | ja | teilweise | teilweise |
| `prefers-color-scheme` | ja | nein | nein | ja (Outlook-App iPhone im Test: nein, siehe oben) | nein (wird zu `@media ()`) | Apps ja |
| `color-scheme` (CSS/Meta) | ja | nein | nein | nein | nein | – |
| Attribut-Selektoren | ja | nur `[class~=…]` | nein | `[attr]`, nicht mit Klasse kombiniert, Klassen werden zu `x_…` | nur `[attr=value]` | nein |
| `rgba` | ja | ja (Kommas) | nein | ja | ja (Kommas) | nein |
| `word-break` / `overflow-wrap` | ja | – | – | – | **nein** | – |
| `max-width` | ja | ja | nur Tabellen | ja | ja | ja |
| `margin: auto` | ja | ja | – | – | teilweise | – |
| CSS-Variablen | ja | nein | nein | nein | nein | nein |
| SVG im HTML | teilweise | nein | nein | nein | nein | nein |

Weitere Fallen: Gmail entfernt den ganzen `<style>`-Block oder das ganze `style`-Attribut bei `url()` mit Bild und bei `rgba` mit Leerzeichen-Schreibweise; manche Programme verlieren die Regel nach einem CSS-Kommentar; `!important` ohne Leerzeichen davor wird bei Yahoo samt Angabe entfernt; Outlook (.com) verlangt `<style>` vor der Verwendung.

## 4. Was wir probiert haben und warum es scheiterte (15./16.11.2026)

1. **Glas als Bilder** (`mail-glass`): Lichtkante, Kartenenden, Glanz, Halo und Farbfelder als PNG. Ergebnis: in Gmail und Apple Mail hübsch, aber
   - Yahoo-Spam zeigte keine Bilder → flache Karte mit Lücken;
   - Yahoo dunkel ließ Zellen mit Bild hell → helle Kartenenden um eine dunkle Mitte, helles Rechteck um den Knopf;
   - Mail-Proxys zeigten noch alte Bilder (Streifen unter dem Knopf) → Adressen mit Inhalts-Hash halfen nur für künftige Änderungen;
   - Kartenenden aus Bildern plus Mittelteil ergaben Nähte.
2. **Kontrast-Nachbesserung** (`mail-contrast`): Yahoo Web hellte Linkfarbe und CSS-Ränder auf → Knopftext blass auf Orange, Seitenlinien creme.
3. **Karte als eine Zelle** (`mail-caps`): Nähte weg, Yahoo-Problem mit Bildern im Knopf und im Hintergrund blieb.
4. **Neubau** (`mail-rebuild`): alles oben, ohne Bilder, hell als Grundlage. Die Kopie des Seitenstils auf dem Server (`users.theme`) entfiel.
5. **Outlook dunkel** (`mail-outlook-dark`): Farbregeln in eigene Blöcke getrennt. Ergebnis im Test: Die Outlook-App nimmt die Hell-Regeln immer und färbt dann selbst um; nicht steuerbar.
6. **Yahoo Web zu breit** (`mail-yahoo-width`): `word-break` wird nicht unterstützt → `<wbr>` im Text.

Verworfen: Bilder für Glas; VML-Knopf für Outlook (zweiter Link nur für ein auslaufendes Programm); Mail nach dem Seitenstil färben (ein dunkler Grundstil wird von umkehrenden Programmen hell gedreht); „immer hell“ ohne Dunkelstil (Janis: Hell und Dunkel bleiben Ziele).

## 5. Aufbau der heutigen Mail

- **Gerüst:** `<body>` und äußere Tabelle (Klasse `page`, `bgcolor`), Zelle mit Klasse `fields` (Farbfelder), innere Tabelle `width="100%"`, `max-width:520px`, für Outlook eine Geistertabelle mit 520 px. Darin die Marke „Agent-Hub“, **eine** Kartenzelle (Klasse `card`, Rundung 28 px, Innenabstand 36 × 32 px, am Handy 28 × 22 px), Überschrift (30 px), Text (17 px), Knopf (Zelle `btn` mit `mso-padding-alt`, Link `bt` mit Padding, Text im `span`), Linkhilfe und Link (13 px, `<wbr>`), Hinweis, Fußzeile außerhalb der Karte. Vorschautext unsichtbar am Anfang.
- **Klassen:** `page`, `fields`, `card`, `t` (Text), `m` (gedämpft), `h1`, `btn`, `bt`. Sie sind die Schnittstelle zwischen Inline-Farben und den Zugaben.
- **Blöcke und wer sie liest:**

| Block | Inhalt | Wer liest ihn |
|---|---|---|
| `STYLE_OUTLOOK` (`[if mso]`) | Arial, Hex-Rand der Karte | nur Outlook für Windows |
| `STYLE_GLASS` | `color-scheme`, Kartenrand `rgba`, Lichtkante und Schatten, Glow des Knopfs, schmaler Bildschirm | alle mit `<style>` |
| `STYLE_GRADIENTS` | Farbfelder, Glanz des Knopfs (hinter `[class~=…]`), Apples Datenerkennung | Apple, Gmail, Samsung; nicht Yahoo |
| `STYLE_SCHEMES` | Hell: Knopf im Seiten-Orange; Dunkel: ganze dunkle Palette (nur Klassen) | Apple, Outlook-Programme (Hell), Samsung, GMX/WEB.DE-Apps |
| `STYLE_DARK_FIELDS` | dunkle Farbfelder | wie oben, soweit Verläufe gehen |
| `STYLE_OUTLOOK_DARK` | `[data-ogsc]`/`[data-ogsb]` | Outlook.com (in der App wirkungslos) |

- **Farben** (in `mailtext.py`): `LIGHT` (Grundlage, inline: Seite `#EFDCC6`, Karte `#F7E6D3`, Rand `#E2C7A8`, Text `#3A2A20`, gedämpft `#6F5848`, Knopf `#B05530` mit `#FFF6EE`), `SITE_BUTTON` (wo Hell gesteuert wird: `#E8845A` mit `#2B1D14`), `DARK` (Seite `#1F1713`, Karte `#33241C`, Text `#F6E6D8`, gedämpft `#BDA591`, Knopf `#F29A72` mit `#2B1D14`).

## 6. Für Skins (auch für Mails)

Skins sollen später das Aussehen austauschen (CLAUDE.md „Skins mitdenken“, PROJEKT.md 11a Merkliste). Für Mails heißt das:

- **Ein Mail-Skin ist Daten, kein CSS:** die drei Paletten (`LIGHT`, `SITE_BUTTON`, `DARK`), die Farben der Farbfelder, Rundungen von Karte und Knopf, Schatten. Die Struktur und die Regeln oben bleiben fest; ein Skin darf weder Bilder noch eigenes CSS mitbringen.
- **Ableitung von der Seite:** `--bg` → Seite, `--glass` deckend gerechnet → Karte, `--text`, `--muted`, `--accent`/`--on-accent` → `SITE_BUTTON` und dunkler Knopf; der **robuste Knopf** (`LIGHT.accent` mit hellem Text) muss eigens gewählt werden (Akzentfarbe so weit abgedunkelt, dass heller Text 4,5 : 1 erreicht).
- **Prüfung beim Import** (wie die Tests heute): Kontraste ≥ 4,5 : 1 für Text/Karte, gedämpft/Karte, gedämpft/Seite, Knopftext/Knopf in beiden Stilen und für `SITE_BUTTON`; heller Knopftext in `LIGHT`; kein reines Weiß oder Schwarz.
- **Farbton der hellen Grundfarbe bestimmt das Umfärben:** Outlook und Gmail dunkeln die helle Grundlage ab und behalten den Farbton. Gelbliche Cremetöne werden **oliv**, rosé oder neutrale Töne werden neutral dunkelbraun oder grau. Wer einen Skin baut, sieht in der Simulation (Abschnitt 7), was daraus wird.
- **Ränder:** Yahoo hellt dunkle Ränder im Dunkelmodus auf; ein Skin sollte blasse Ränder wählen und mit einer hellen Linie im Dunkeln leben können.
- **Hell und Dunkel gehören zusammen:** Jeder Skin liefert beide Paletten.

## 7. Prüfen

- **Tests:** `test_resets.py`, Klasse `LinkMailTest`: keine Bilder, nur Hell inline, Kontraste, CSS-Regeln (Kommentare, `!important`, `rgba`, Verläufe nur hinter `[class~=…]`, Farbregeln ohne Attribut-Selektoren), Größe, Vorschautext, Outlook-Teile, Umbruchstellen.
- **Vorschau:** `python tests/preview_mail.py OUT` im Container (Abschnitt 9 in PROJEKT.md, `~/prev`-Ablauf; auf dem Pi `bash ~/pm.sh <branch>` schreibt nach `~/prevmail`), dann im Browser mit Farbschema hell und dunkel ansehen.
- **Simulationen im Browser** (Konsole der Vorschau):
  - ohne `<style>` (GMX/WEB.DE Browser, Gmail fremde Konten): `document.querySelectorAll('style').forEach(s => s.remove())`
  - Umfärben wie Yahoo/Gmail Android (helle Flächen dunkler, dunkler Text heller): für jedes Element mit hellem `background-color` (Helligkeit > 0,6) den Wert umkehren und abdunkeln, für dunklen Text (< 0,45) aufhellen
  - volle Umkehrung wie Gmail iPhone / Outlook Windows: `document.documentElement.style.filter = 'invert(1) hue-rotate(180deg)'`
  - schmales Lesefenster (Yahoo Web): Breite 400–430 px
- **Echte Programme:** eine Einladung an Gmail, Yahoo, Outlook, Apple Mail; hell und dunkel; App und Browser. Bei Gmail „Original anzeigen“, bei Yahoo „Rohtext“ für SPF/DKIM/DMARC.

## 8. Offen

- Ungetestet: Gmail Web und Android, Outlook.com im Browser, Outlook für Windows, GMX, WEB.DE, T-Online, Samsung.
- Outlook-App und Gmail-App dunkel: trübes Oliv durch deren eigenes Umfärben; nur über einen anderen Farbton der hellen Grundlage zu ändern (nicht gemacht, verändert Hell überall).
- Yahoo: Spam bei neuer Domain (Ruf baut sich mit der Zeit auf).
