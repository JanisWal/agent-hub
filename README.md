# Agent-Hub

Selbst gehostetes Verwaltungstool für einen Raspberry Pi oder Linux-Server: Projekte als Kacheln, ein Kanban-Board, feste KI-Agenten-Rollen (Manager, Programmierer, Tester, Prüfer), Dateiablage und ein Tresor für Zugangsdaten. Jeder Nutzer verbindet sein eigenes KI-Konto.

## Installieren

Auf dem Server:

```bash
curl -fsSL https://raw.githubusercontent.com/JanisWal/agent-hub/main/install.sh | sudo bash
```

Vorher, auf einem Raspberry Pi: mit dem Raspberry Pi Imager „Raspberry Pi OS Lite (64-bit)“ schreiben, in den Einstellungen Benutzer, WLAN und SSH einschalten, dann `ssh benutzer@hostname.local`. Ohne `curl`: `sudo apt-get install -y curl`.

Am Ende nennt das Skript eine Adresse (`http://<IP>:8080`). Dort führt ein Assistent durch alles Weitere: Konto oder Backup einspielen, Erreichbarkeit von unterwegs (Cloudflare-Tunnel), Mail (Resend), Backup und KI. Jeder Schritt hat eine Anleitung zum Aufklappen.
