#!/usr/bin/env bash
# Rebuild the hub on a fresh Raspberry Pi OS from an encrypted backup (made by backup.sh).
#
#   1. Write Raspberry Pi OS Lite 64-bit to the new SD card with the Raspberry Pi Imager (set the user "admin",
#      the host name and your SSH key there), start the Pi, log in over SSH.
#   2. Plug in the USB stick and mount it:   sudo mkdir -p /mnt/stick && sudo mount /dev/sda1 /mnt/stick
#   3. This file must be on the stick as well: the new Pi cannot fetch it from GitHub (the key for that is
#      in the backup). Copy it from the PC onto the stick once (it is in the project folder, deploy/restore.sh,
#      and in the repository). Then run, with the stick mounted at /mnt/stick:
#        sudo bash restore.sh /mnt/stick/agent-hub            # the newest backup in that folder
#        sudo bash restore.sh /mnt/stick/agent-hub/hub-2026-11-12.tar.gz.gpg   # or one file
#      It asks for the backup password (the one backup.sh showed once, in your password manager).
#
# It installs Docker and Git, puts the data back (database, secrets, Claude logins, tunnel, deploy key), fetches the
# code from GitHub, builds the images and starts everything. It refuses to run on top of an existing hub.
# Switch the old Pi off first: two Pis must not run the same tunnel token.
#
# Settings (environment): BASE, ADMIN_USER, ADMIN_HOME, REPO, BACKUP_PASSPHRASE_FILE (instead of asking),
# SKIP_SYSTEM=1 (only decrypt and put the files in place: used by the tests, needs no root, no Docker, no network).
set -euo pipefail
umask 077

TARGET=${1:?"Usage: sudo bash restore.sh <backup file or the folder that holds the backups>"}
ADMIN_USER=${ADMIN_USER:-${SUDO_USER:-admin}}
ADMIN_HOME=${ADMIN_HOME:-$(getent passwd "$ADMIN_USER" | cut -d: -f6)}
BASE=${BASE:-/opt/agent-hub}
REPO=${REPO:-git@github.com:JanisWal/agent-hub.git}
CLONE=$BASE/workspaces/agent-hub
CLAUDE_DIR=$BASE/claude
WORK_DIR=$BASE/work
TUNNEL_DIR=$ADMIN_HOME/cloudflared
SSH_DIR=$ADMIN_HOME/.ssh
SKIP_SYSTEM=${SKIP_SYSTEM:-0}
NEED_REBOOT=0

say() { printf '\n== %s\n' "$*"; }
die() { printf 'Stopped: %s\n' "$*" >&2; exit 1; }
own() { [ "$SKIP_SYSTEM" = 1 ] || chown "$@"; }                       # owners only matter on the real system
as_admin() { if [ "$SKIP_SYSTEM" = 1 ]; then "$@"; else sudo -u "$ADMIN_USER" -H "$@"; fi; }

[ "$SKIP_SYSTEM" = 1 ] || [ "$(id -u)" = 0 ] || die "please run with sudo"
[ -n "$ADMIN_HOME" ] || die "user $ADMIN_USER does not exist"
if [ -d "$TARGET" ]; then
  FILE=$(ls -1 "$TARGET"/hub-*.tar.gz.gpg 2>/dev/null | sort | tail -1 || true)
  [ -n "$FILE" ] || die "no hub-*.tar.gz.gpg in $TARGET"
else
  FILE=$TARGET
fi
[ -f "$FILE" ] || die "backup file not found: $FILE"
# It only ever writes into places that are empty: a second run, or a run on a Pi that has a hub, stops here.
[ ! -e "$CLONE" ] || [ -z "$(ls -A "$CLONE" 2>/dev/null)" ] || die "$CLONE is not empty: there is a hub here already; this script never overwrites one"
[ -z "$(ls -A "$CLAUDE_DIR" 2>/dev/null)" ] || die "$CLAUDE_DIR is not empty (Claude logins of a running hub?)"
[ ! -e "$TUNNEL_DIR/.env" ] || die "$TUNNEL_DIR/.env exists already"
[ ! -e "$SSH_DIR/id_ed25519" ] || die "$SSH_DIR/id_ed25519 exists already (it is the deploy key of this Pi)"
echo "Backup: $FILE"

# --- 1. open the backup into a temporary folder; nothing is changed on the system before it is known to be good
WORK=$(mktemp -d /var/tmp/hub-restore.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
if [ -n "${BACKUP_PASSPHRASE_FILE:-}" ]; then
  PASS=$(cat "$BACKUP_PASSPHRASE_FILE")
else
  read -r -s -p "Backup password: " PASS < /dev/tty; echo
fi
say "Decrypting and checking"
command -v gpg > /dev/null || { [ "$SKIP_SYSTEM" = 1 ] && die "gpg is missing"; apt-get update -qq && apt-get install -y gnupg; }
gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 3 --decrypt "$FILE" 3<<< "$PASS" | tar -xz -C "$WORK" \
  || die "wrong password or damaged backup"
unset PASS
P=$WORK/payload
(cd "$P" && sha256sum --quiet -c MANIFEST.sha256) || die "the checksums do not match: the backup is damaged"
for needed in hub.db hub.env tunnel.env tunnel-compose.yml ssh/id_ed25519 claude; do
  [ -e "$P/$needed" ] || die "the backup lacks $needed"
done
echo "The backup is complete and unchanged."

# --- 2. system: Git, Docker, group, memory limit
if [ "$SKIP_SYSTEM" != 1 ]; then
  say "Installing Git and Docker"
  apt-get update -qq
  apt-get install -y git curl ca-certificates gnupg
  if ! docker compose version > /dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin
  fi
  usermod -aG docker "$ADMIN_USER"
  # Raspberry Pi only: without this the memory limits of the containers do not work (see PROJEKT.md)
  if [ -f /boot/firmware/cmdline.txt ] && ! grep -q cgroup_memory /boot/firmware/cmdline.txt; then
    sed -i '1 s/$/ cgroup_enable=memory cgroup_memory=1/' /boot/firmware/cmdline.txt
    NEED_REBOOT=1
  fi
fi

# --- 3. the deploy key first: it is what lets us fetch the code
say "Putting the files in place"
install -d -m 700 "$SSH_DIR"
install -m 600 "$P/ssh/id_ed25519" "$SSH_DIR/id_ed25519"
install -m 644 "$P/ssh/id_ed25519.pub" "$SSH_DIR/id_ed25519.pub"
own -R "$ADMIN_USER": "$SSH_DIR"

install -d -m 755 "$BASE/workspaces"
own "$ADMIN_USER": "$BASE" "$BASE/workspaces"
if [ "$SKIP_SYSTEM" = 1 ]; then
  mkdir -p "$CLONE"                                                   # tests: no network
else
  rmdir "$CLONE" 2> /dev/null || true                                 # git clone wants a missing or empty folder
  GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new" as_admin git clone "$REPO" "$CLONE"
fi

# --- 4. the data
install -d -m 755 "$CLONE/data"
install -m 600 "$P/hub.db" "$CLONE/data/hub.db"                         # root: the web container writes it as root
cp -a "$P/data/." "$CLONE/data/"
install -m 600 "$P/hub.env" "$CLONE/.env"
own "$ADMIN_USER": "$CLONE/.env"

rmdir "$CLAUDE_DIR" 2> /dev/null || true                              # an empty folder may be here, never a full one (checked above)
cp -a "$P/claude" "$CLAUDE_DIR"                                       # owners and 0700 are kept (the run users are 10000+id)
chmod 700 "$CLAUDE_DIR"
if [ -d "$P/repos" ]; then                                            # the projects' code (since 15.11.2026)
  install -d -m 700 "$WORK_DIR"
  cp -a "$P/repos" "$WORK_DIR/repos"
fi

install -d -m 755 "$TUNNEL_DIR"
install -m 600 "$P/tunnel.env" "$TUNNEL_DIR/.env"
install -m 644 "$P/tunnel-compose.yml" "$TUNNEL_DIR/compose.yml"
own -R "$ADMIN_USER": "$TUNNEL_DIR"
echo "Database, secrets, Claude logins, tunnel and deploy key are back."

if [ "$SKIP_SYSTEM" = 1 ]; then
  say "Done (SKIP_SYSTEM: nothing was installed or started)"
  exit 0
fi

# --- 5. build and start
say "Building and starting the hub (this takes a few minutes on a Pi)"
docker network inspect web > /dev/null 2>&1 || docker network create web
cd "$CLONE"
as_admin docker build -t agent-hub-agent -f runner/Dockerfile runner
as_admin docker build -t agent-hub-vibe -f runner/Dockerfile.vibe runner
as_admin docker compose up -d --build
cd "$TUNNEL_DIR"
as_admin docker compose up -d

say "Checking"
for _ in $(seq 1 30); do
  if curl -fs http://127.0.0.1:8000/health > /dev/null; then OK=1; break; fi
  sleep 2
done
if [ "${OK:-0}" = 1 ]; then echo "The hub answers on this Pi."; else echo "The hub does not answer yet: look at 'docker compose logs web' in $CLONE"; fi
cat <<EOF

Next:
  - open https://hub.janis-home.de and log in (the tunnel runs from the restored token);
  - look at the Claude connection in the drawer: if it says expired, connect again (a login can run out);
  - set the nightly backup up again:  sudo bash $CLONE/deploy/setup-backup.sh
    (it makes a NEW backup password; keep the old one for the old backups).
EOF
[ "$NEED_REBOOT" = 0 ] || echo "  - reboot once (sudo reboot): the memory limit of the containers needs it."
