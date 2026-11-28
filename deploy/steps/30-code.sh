#!/usr/bin/env bash
# The code into <dir>/app. An update keeps .env and moves the old code to app.old (to go back: move it back and run
# its update.sh); from Git the code is already in place. Last, the version (commit and its date, from Git) goes into
# web/app/VERSION: the web image carries it and the administration shows it (web/app/updates.py, 28.11.2026).
set -euo pipefail
. "$STEPS/lib.sh"
say "Code"
version=$(git -c safe.directory='*' -C "$SRC" log -1 --format='%H %cs' 2>/dev/null || true)
if [ "$SRC" = "$APP" ]; then
  note "Code liegt schon in $APP"
elif [ "$MODE" = install ]; then
  install -d -m 755 "$APP"
  cp -a "$SRC/." "$APP/"
  chown -R root:root "$APP" && chmod -R go-w,go+rX "$APP"   # whoever unpacked the ZIP does not own the hub's code
  note "Kopiert nach $APP"
else
  # The first hub keeps its data inside the code folder (./data); swapping the folder would take the data away.
  [ -n "$(env_get HUB_DATA_HOST_DIR)" ] || die "Diese Installation hat ihre Daten im Code-Ordner. Hier nur aus Git aktualisieren: update.sh --git"
  rm -rf "$APP.new"
  install -d -m 755 "$APP.new"
  cp -a "$SRC/." "$APP.new/"
  chown -R root:root "$APP.new" && chmod -R go-w,go+rX "$APP.new"
  cp -a "$APP/.env" "$APP.new/.env"
  rm -rf "$APP.old"
  mv "$APP" "$APP.old"
  mv "$APP.new" "$APP"
  note "Neue Version in $APP, die vorige liegt in $APP.old"
fi
if [ -n "$version" ]; then
  printf '%s\n' "$version" > "$APP/web/app/VERSION"
  note "Version ${version:0:7} vom ${version#* }"
fi
