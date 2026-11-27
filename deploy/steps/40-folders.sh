#!/usr/bin/env bash
# The folders of a new install, next to the code: data/ (the web service, user 9000), claude/ and work/ (root only:
# logins and the code of the projects), backups/ (written by root, read by the web service). An update only adds a
# folder that is missing.
set -euo pipefail
. "$STEPS/lib.sh"
say "Ordner"
if [ "$MODE" = install ]; then
  touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
  env_add HUB_BASE_HOST_DIR "$HUB_DIR"
  env_add HUB_APP_HOST_DIR "$APP"
  env_add HUB_DATA_HOST_DIR "$HUB_DIR/data"
  env_add HUB_CLAUDE_HOST_DIR "$HUB_DIR/claude"
  env_add HUB_WORK_HOST_DIR "$HUB_DIR/work"
  env_add HUB_BACKUP_HOST_DIR "$HUB_DIR/backups"
fi
data=$(place HUB_DATA_HOST_DIR "$APP/data")
claude=$(place HUB_CLAUDE_HOST_DIR /opt/agent-hub/claude)
work=$(place HUB_WORK_HOST_DIR /opt/agent-hub/work)
backups=$(place HUB_BACKUP_HOST_DIR /opt/agent-hub/hub-backups)
[ -d "$data" ] || { install -d -m 750 -o 9000 -g 9000 "$data"; note "Angelegt: $data"; }
[ -d "$data/files" ] || install -d -m 750 -o 9000 -g 9000 "$data/files"
[ -d "$claude" ] || { install -d -m 700 "$claude"; note "Angelegt: $claude"; }
[ -d "$work" ] || { install -d -m 700 "$work"; note "Angelegt: $work"; }
[ -d "$backups" ] || { install -d -m 750 -g 9000 "$backups"; note "Angelegt: $backups"; }
