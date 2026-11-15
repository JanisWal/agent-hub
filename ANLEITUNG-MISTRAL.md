# Mistral im Agent-Hub verknüpfen

So nutzt du dein Mistral-Abo als KI für den Manager im Agent-Hub. Du brauchst etwa 5 Minuten und musst **nichts installieren**: Alles läuft im Browser.

## Was du brauchst

- Dein Konto beim Agent-Hub (Einladung per Mail von Janis).
- Dein Mistral-Konto mit dem **Pro-Abo**. Im Pro-Abo ist jeden Monat ein Guthaben für die Mistral-Schnittstelle enthalten; davon zahlt der Hub. Laut Mistrals Preisseite (Stand November 2026) sind das 15 US-Dollar im Monat. Mistral hat diesen Betrag schon mehrmals geändert.

## 1. Schlüssel bei Mistral anlegen

1. Öffne **https://console.mistral.ai/api-keys** und melde dich mit deinem Mistral-Konto an (wie bei Le Chat bzw. Vibe).
2. Klicke auf **„New key“**.
3. Name: `Agent-Hub`.
4. Ablaufdatum: am besten in einem Jahr. Danach legst du einfach einen neuen Schlüssel an.
5. Zugriff auf Connectors: **„Shared connectors only“** (der Hub braucht keine).
6. Erstellen und den Schlüssel **sofort kopieren**. Mistral zeigt ihn nur einmal.

Fragt Mistral nach einer Zahlungsart oder ist der Knopf ausgegraut: Prüf unter **Admin → Billing**, ob das Pro-Abo diesem Konto (dieser Organisation) zugeordnet ist.

## 2. Keine Zusatzkosten

Unter **Admin → Billing** kannst du „Pay-as-you-go“ einschalten. **Lass das aus.** Dann verbraucht der Hub nur das Guthaben aus deinem Abo. Ist es für den Monat aufgebraucht, antwortet der Manager bis zum nächsten Monat mit einer Fehlermeldung, kostet dich aber nichts extra.

Achtung: Le Chat bzw. Vibe und die Schnittstelle zehren vom selben Monatsguthaben.

## 3. Im Hub verknüpfen

1. Melde dich unter **https://hub.janis-home.de** an.
2. Öffne oben rechts das **Zahnrad**.
3. Im Kasten **Claude** klickst du auf den kleinen **Pfeil** oben rechts. Darunter klappen die weiteren KIs auf.
4. Klicke bei **Mistral** auf **„Verknüpfen“**, füge den Schlüssel ein und klicke auf **„Bestätigen“**.
5. Nach ein paar Sekunden steht da **„Mistral ist verknüpft“**. Schließen, fertig.

Den Schlüssel sieht danach niemand mehr, auch Janis nicht: Der Hub speichert ihn verschlüsselt und schickt ihn nur an Mistral.

## 4. Mistral im Manager nutzen

Hast du nur Mistral verknüpft, ist Mistral automatisch deine **Standard-KI**: der Manager-Chat und die Agenten arbeiten damit. Hast du mehrere KIs, klickst du im Zahnrad bei Mistral auf **„Als Standard“**.

1. Öffne ein Projekt und dort die Ansicht **Manager**.
2. Oben im Chat steht die Kapsel mit **Modell** und **Stufe**. Wähle als Modell:
   - **Mistral Small**: schnell und sparsam, gut für den Alltag. Stufe **„Ohne Nachdenken“** ist am schnellsten, **„Hoch“** denkt vorher nach.
   - **Mistral Large**: gründlicher, braucht mehr Guthaben. Stufen Niedrig, Mittel und Hoch.
3. Jetzt einfach fragen. Unter deiner Frage steht „Mistral antwortet“.

## Gut zu wissen

- **Mistral kann im Web suchen, Seiten lesen und Code ausführen** (über Mistral Vibe auf dem Server). Der Globus-Knopf („Web + Code“) schaltet das offene Internet für den Code an oder aus, wie bei Claude. Websuchen verbrauchen ebenfalls Guthaben aus deinem Abo.
- **Agenten:** Auf dem Board kannst du einen Punkt „An die Agenten geben“. Programmierer, Tester und Prüfer arbeiten dann mit Mistral, am Ende gibst du auf der Karte frei. Das verbraucht deutlich mehr Guthaben als eine Chat-Frage.
- Die Erinnerung des Projekts (MEMORY.md und die anderen Dateien unter „Erinnerungen“) funktioniert mit Mistral genauso wie mit Claude. Du kannst die KI also wechseln, ohne dass das Projekt etwas vergisst.
- **„Schlüssel abgelehnt“** im Menü heißt: Der Schlüssel ist abgelaufen oder wurde bei Mistral gelöscht. Leg einen neuen an (Schritt 1) und klicke auf **„Erneuern“**.
- **Trennen** (Zahnrad → Mistral → „Trennen“) löscht den gespeicherten Schlüssel im Hub. Den Schlüssel selbst löschst du zusätzlich unter console.mistral.ai/api-keys.
