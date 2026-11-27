#!/usr/bin/env bash
# The key pair of the device vault (web/app/vault.py, age): made once with the web image's own library. The web service
# gets only the public half, the broker the private one.
set -euo pipefail
. "$STEPS/lib.sh"
[ -z "$(env_get HUB_VAULT_PUBLIC)" ] || exit 0
say "Schlüssel des Tresors"
pair=$(docker run --rm --network none --entrypoint python "$(place HUB_NAME agent-hub)-web" -c \
  "import pyrage; i = pyrage.x25519.Identity.generate(); print(i); print(i.to_public())")
env_add HUB_VAULT_IDENTITY "$(printf '%s\n' "$pair" | sed -n 1p)"
env_add HUB_VAULT_PUBLIC "$(printf '%s\n' "$pair" | sed -n 2p)"
note "Erzeugt"
