#!/usr/bin/env bash
# Shared by the steps (source it). Messages in German: they are what the person at the server reads.
say()  { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '   Achtung: %s\n' "$*"; }
die()  { printf '\nAbbruch: %s\n' "$*" >&2; exit 1; }

ENV_FILE=${APP:?}/.env

# The value of KEY in .env ("" when missing).
env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 || true; }
# Add KEY=VALUE to .env only when KEY is not there yet: an update never changes what is set.
env_add() {
  if [ -z "$(env_get "$1")" ] && ! grep -q "^$1=" "$ENV_FILE" 2>/dev/null; then
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
  fi
}
# A place of the hub (host path): from .env, else the default of compose.yml (the first hub's layout).
place() { local v; v=$(env_get "$1"); printf '%s' "${v:-$2}"; }
# Random text for tokens and keys (URL-safe base64, no line breaks).
random() { head -c "${1:-32}" /dev/urandom | base64 | tr -d '\n=' | tr '+/' '-_'; }
compose() { docker compose --project-directory "$APP" -p "$(place HUB_NAME agent-hub)" "$@"; }
REBOOT_MARK=/run/agent-hub-needs-reboot
