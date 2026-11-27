#!/usr/bin/env bash
# The settings in .env. A new install gets its places, port and the tokens and keys of the services (made here, never
# shown). An update only adds keys a newer version needs; nothing that is set changes.
set -euo pipefail
. "$STEPS/lib.sh"
say "Einstellungen"
if [ "$MODE" = install ]; then
  env_add HUB_NAME agent-hub
  env_add HUB_BIND 0.0.0.0
  env_add HUB_PORT "${HUB_PORT:?}"
  env_add HUB_SECURE_COOKIE auto
  env_add HUB_TRUSTED_PROXY tunnel
  env_add HUB_WEB_NETWORK agent-hub-web
fi
if [ -z "$(env_get RUNNER_TOKEN)" ]; then
  token=$(random 32)
  env_add RUNNER_TOKEN "$token"
  env_add HUB_RUNNER_TOKEN_HASH "$(printf '%s' "$token" | sha256sum | cut -d' ' -f1)"
fi
# Fernet key of the saved logins (runner/tokens.py): 32 random bytes, URL-safe base64 with padding.
[ -n "$(env_get HUB_TOKEN_KEY)" ] || env_add HUB_TOKEN_KEY "$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')"
env_add HUB_BROKER_TOKEN "$(random 32)"
chmod 600 "$ENV_FILE"
note "Gespeichert in $ENV_FILE (nur für root lesbar)"
