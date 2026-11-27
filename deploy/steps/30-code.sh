#!/usr/bin/env bash
# The code into <dir>/app. An update keeps .env and moves the old code to app.old (to go back: move it back and run
# its update.sh); from Git the code is already in place.
set -euo pipefail
. "$STEPS/lib.sh"
say "Code"
if [ "$SRC" = "$APP" ]; then
  note "Code liegt schon in $APP"
  exit 0
fi
if [ "$MODE" = install ]; then
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
