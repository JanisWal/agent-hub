#!/usr/bin/env bash
# Build the images: the services (compose.yml) and the images of the AI runs (images.list). On a Raspberry Pi this
# takes a while (the first time half an hour or more).
set -euo pipefail
. "$STEPS/lib.sh"
say "Images bauen (das dauert eine Weile)"
network=$(place HUB_WEB_NETWORK web)
docker network inspect "$network" > /dev/null 2>&1 || docker network create "$network" > /dev/null
compose build --quiet
while read -r tag dockerfile context; do
  case "$tag" in ''|'#'*) continue ;; esac
  note "$tag"
  docker build --quiet -t "$tag" -f "$APP/$dockerfile" "$APP/$context" > /dev/null
done < "$STEPS/images.list"
