#!/usr/bin/env bash
# Agent-Hub aktualisieren (27.11.2026). Zwei Wege:
#   Neue Version als ZIP holen, entpacken und dort:   sudo bash update.sh [--dir /opt/agent-hub]
#   Installation aus Git (app/ ist ein Klon):        sudo bash /opt/agent-hub/app/update.sh --git
# Vorher sichert es die Datenbank (data/before-update/, 35 Tage), tauscht den Code (der alte bleibt als app.old, zum
# Zurückholen), ergänzt neue Einstellungen in .env, baut die Images und startet neu. Daten, Logins und .env bleiben.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HUB_DIR=""
GIT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) HUB_DIR=${2:?}; shift 2 ;;
    --git) GIT=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo starten." >&2; exit 1; }
if [ "$GIT" = 1 ]; then
  [ -d "$HERE/.git" ] || { echo "$HERE ist kein Git-Klon." >&2; exit 1; }
  git -C "$HERE" pull --ff-only
  HUB_DIR=${HUB_DIR:-$(dirname "$HERE")}
else
  HUB_DIR=${HUB_DIR:-/opt/agent-hub}
fi
MODE=update HUB_DIR=$HUB_DIR SRC=$HERE bash "$HERE/deploy/steps/run.sh"
