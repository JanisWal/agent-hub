#!/usr/bin/env bash
# Runs the steps of this version in order (NN-name.sh). Called by install.sh (MODE=install) and update.sh
# (MODE=update) with SRC (this version's code) and HUB_DIR (the base folder). Each step is a file of its own and decides
# by MODE what it does; a new version adds or changes step files, install.sh and update.sh stay as they are.
set -euo pipefail
: "${MODE:?}" "${SRC:?}" "${HUB_DIR:?}"
STEPS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -f "$SRC/.env" ]; then APP=$SRC; else APP=$HUB_DIR/app; fi   # update from Git: the code is already in place
export MODE SRC HUB_DIR APP STEPS HUB_PORT="${HUB_PORT:-}"
for step in "$STEPS"/[0-9][0-9]-*.sh; do
  bash "$step"
done
