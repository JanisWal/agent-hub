#!/usr/bin/env bash
# Agent-Hub entfernen (27.11.2026): stoppt und löscht die Container, Images und Netze des Hubs und den Ordner mit Code,
# Daten, Logins und Backups. Docker selbst und andere Container bleiben. Nur für Installationen mit install.sh.
#
#   sudo bash /opt/agent-hub/app/uninstall.sh                 # fragt vorher nach
#   sudo bash /opt/agent-hub/app/uninstall.sh --keep-backups  # die Backups bleiben in <dir>/backups
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --keep-backups) KEEP=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo starten." >&2; exit 1; }
ENV_FILE=$HERE/.env
get() { sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | tail -1; }
BASE=$(get HUB_BASE_HOST_DIR)
# Only a hub made by install.sh knows its places; the first hub (data inside the code folder) is never removed here.
[ -n "$BASE" ] && [ -n "$(get HUB_DATA_HOST_DIR)" ] || { echo "Das ist keine Installation von install.sh. Abbruch." >&2; exit 1; }
case "$BASE" in /|/opt|/home|/root|/usr|/var|/etc) echo "Ungültiger Ordner: $BASE" >&2; exit 1 ;; esac
NAME=$(get HUB_NAME); NAME=${NAME:-agent-hub}
NETWORK=$(get HUB_WEB_NETWORK)

echo "Das löscht den Hub unter $BASE: Container, Images, Daten, Logins$([ "$KEEP" = 1 ] || echo ", Backups")."
read -r -p "Zum Bestätigen LÖSCHEN eintippen: " answer < /dev/tty
[ "$answer" = "LÖSCHEN" ] || { echo "Nichts gelöscht."; exit 1; }

cd "$HERE"
docker compose --project-directory "$HERE" -p "$NAME" --profile tunnel down --remove-orphans --volumes --rmi all || true
docker ps -aq --filter "name=^${NAME}-hubctl-" --filter "name=^agent-run-" --filter "name=^agent-chat-" --filter "name=^agent-test-" \
  | xargs -r docker rm -f > /dev/null
while read -r tag _; do
  case "$tag" in ''|'#'*) continue ;; esac
  docker image rm -f "$tag" > /dev/null 2>&1 || true
done < "$HERE/deploy/steps/images.list"
docker image rm -f agent-hub-hub-runner > /dev/null 2>&1 || true
for net in agent-hub-agents agent-hub-devices ${NETWORK:+"$NETWORK"}; do
  [ "$net" = web ] && continue   # a network of that name may belong to something else
  docker network rm "$net" > /dev/null 2>&1 || true
done
cd /
if [ "$KEEP" = 1 ]; then
  find "$BASE" -mindepth 1 -maxdepth 1 ! -name backups -exec rm -rf {} +
  echo "Entfernt. Die Backups liegen weiter in $BASE/backups."
else
  rm -rf "$BASE"
  echo "Entfernt: $BASE"
fi
echo "Docker bleibt installiert. Den Speicher der Bauschritte gibt frei: sudo docker builder prune"
