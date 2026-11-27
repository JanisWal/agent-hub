#!/usr/bin/env bash
# Agent-Hub installieren (27.11.2026). Auf einem frischen Raspberry Pi OS Lite (64 Bit) oder einem anderen Linux mit
# Debian oder Ubuntu, auch neben anderen Docker-Containern:
#
#   Code als ZIP holen (GitHub: Code > Download ZIP), auf den Server kopieren, entpacken, dann im entpackten Ordner:
#     sudo bash install.sh
#   oder ohne ZIP, nur mit dieser Datei (lädt den Code mit Git):
#     sudo bash install.sh --source https://github.com/JanisWal/agent-hub.git
#   oder direkt aus dem Netz (sobald das Repo öffentlich ist):
#     curl -fsSL https://raw.githubusercontent.com/JanisWal/agent-hub/main/install.sh | sudo bash
#
# Optionen: --dir /opt/agent-hub (Zielordner), --port 8080 (Port im Heimnetz), --branch main, --source <Git-Adresse>.
# Danach im Browser http://<IP des Servers>:<Port> öffnen; der Einrichtungsassistent übernimmt den Rest.
#
# Diese Datei ist nur der Einstieg: sie findet den Code und startet die Schritte dieser Version (deploy/steps/,
# deploy/steps/run.sh). Eine neue Version ändert nur ihre Schritte; update.sh führt dieselben Schritte aus.
set -euo pipefail

HUB_DIR=/opt/agent-hub
HUB_PORT=8080
BRANCH=main
SOURCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) HUB_DIR=${2:?}; shift 2 ;;
    --port) HUB_PORT=${2:?}; shift 2 ;;
    --branch) BRANCH=${2:?}; shift 2 ;;
    --source) SOURCE=${2:?}; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Bitte mit sudo starten: sudo bash install.sh" >&2; exit 1; }
case "$HUB_DIR" in /*) ;; *) echo "--dir braucht einen absoluten Pfad" >&2; exit 2 ;; esac
case "$HUB_PORT" in ''|*[!0-9]*) echo "--port braucht eine Zahl" >&2; exit 2 ;; esac

HERE=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)
if [ -z "$SOURCE" ] && [ -n "$HERE" ] && [ -f "$HERE/deploy/steps/run.sh" ] && [ -f "$HERE/compose.yml" ]; then
  SRC=$HERE                                  # the code lies next to this file (unpacked ZIP or a clone)
else
  SOURCE=${SOURCE:-https://github.com/JanisWal/agent-hub.git}
  command -v git > /dev/null || { apt-get update -qq && apt-get install -y -qq git ca-certificates; }
  SRC=$(mktemp -d /var/tmp/agent-hub-src.XXXXXX)
  trap 'rm -rf "$SRC"' EXIT
  echo "Lade den Code von $SOURCE ($BRANCH) …"
  git clone --quiet --depth 1 --branch "$BRANCH" "$SOURCE" "$SRC" \
    || { echo "Der Code ließ sich nicht laden. Ist das Repo privat? Dann den Code als ZIP holen (siehe oben)." >&2; exit 1; }
fi

MODE=install HUB_DIR=$HUB_DIR HUB_PORT=$HUB_PORT SRC=$SRC bash "$SRC/deploy/steps/run.sh"
