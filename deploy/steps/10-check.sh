#!/usr/bin/env bash
# Is this server fit for the hub? 64-bit, enough memory and space, the port free; an existing hub is never installed over.
set -euo pipefail
. "$STEPS/lib.sh"
say "Voraussetzungen prüfen"
case "$(uname -m)" in
  aarch64|arm64|x86_64) note "System: $(uname -m)" ;;
  *) die "Der Hub braucht ein 64-Bit-System (gefunden: $(uname -m)). Auf dem Pi: Raspberry Pi OS Lite 64-Bit." ;;
esac
mem=$(awk '/^MemTotal:/ {print int($2/1024)}' /proc/meminfo)
[ "$mem" -ge 850 ] || die "Zu wenig Arbeitsspeicher: $mem MB (mindestens 1 GB)."
note "Arbeitsspeicher: $mem MB"
mkdir -p "$HUB_DIR"
free=$(df -Pk "$HUB_DIR" | awk 'NR==2 {print int($4/1024/1024)}')
if [ "$MODE" = install ]; then
  [ "$free" -ge 12 ] || die "Zu wenig freier Platz unter $HUB_DIR: $free GB (mindestens 12 GB für Programme und Daten)."
fi
note "Freier Platz: $free GB"
if findmnt -no SOURCE / 2>/dev/null | grep -q mmcblk; then
  note "Das System liegt auf einer Speicherkarte. Läuft, eine SSD hält aber deutlich länger."
fi
if [ "$MODE" = install ]; then
  [ ! -e "$HUB_DIR/app/.env" ] || die "Unter $HUB_DIR ist schon ein Hub installiert. Für eine neue Version: update.sh."
  if command -v ss > /dev/null && [ -n "$(ss -ltnH "( sport = :${HUB_PORT:?} )" 2>/dev/null)" ]; then
    die "Port $HUB_PORT ist belegt. Einen anderen wählen: --port 8090"
  fi
else
  [ -f "$APP/.env" ] || die "Unter $APP ist kein Hub installiert (keine .env)."
fi
