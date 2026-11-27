#!/usr/bin/env bash
# Before an update: a consistent copy of the database (SQLite's backup call, inside the running web container) in
# data/before-update/; copies older than 35 days go (as long as backups keep a state).
set -euo pipefail
. "$STEPS/lib.sh"
[ "$MODE" = update ] || exit 0
say "Datenbank sichern"
data=$(place HUB_DATA_HOST_DIR "$APP/data")
stamp=$(date +%Y-%m-%d-%H%M%S)
if compose exec -T web python -c "
import sqlite3, os
os.makedirs('/data/before-update', exist_ok=True)
s = sqlite3.connect('file:/data/hub.db?mode=ro', uri=True); d = sqlite3.connect('/data/before-update/hub-$stamp.db')
s.backup(d); d.close(); s.close()
" ; then
  note "Gesichert: $data/before-update/hub-$stamp.db"
else
  die "Die Datenbank ließ sich nicht sichern (läuft der Hub?). Nichts wurde geändert."
fi
find "$data/before-update" -maxdepth 1 -type f -name 'hub-*.db' -mtime +34 -delete 2>/dev/null || true
