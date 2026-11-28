#!/usr/bin/env bash
# Start (or restart with the new images), wait for the hub, say where to go.
set -euo pipefail
. "$STEPS/lib.sh"
say "Starten"
compose up -d --remove-orphans
port=$(place HUB_PORT 8000)
for _ in $(seq 1 60); do
  if compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" \
       > /dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ "${ok:-0}" = 1 ] || die "Der Hub antwortet nicht. Nachsehen mit: docker compose --project-directory $APP logs web"
ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true)   # an update runs in a container (hubctl)
if [ "$MODE" = install ]; then
  say "Fertig"
  note "Öffne im Browser:  http://${ip:-<IP des Servers>}:$port"
  note "Die Einrichtung ist eine Stunde lang offen (danach den Server neu starten)."
else
  say "Aktualisiert"
fi
if [ -e "$REBOOT_MARK" ]; then
  note "Einmal neu starten, damit die Speichergrenzen gelten: sudo reboot"
fi
