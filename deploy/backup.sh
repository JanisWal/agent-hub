#!/usr/bin/env bash
# Nightly encrypted backup of everything the hub cannot rebuild from GitHub:
# database, secrets (.env files), Claude logins, tunnel config, deploy key, later uploads.
# Runs as root (the Claude folder is root-only). Every path can be overridden from the environment (for tests).
set -euo pipefail
umask 077

HUB_DIR=${HUB_DIR:-/opt/agent-hub/workspaces/agent-hub}
CLAUDE_DIR=${CLAUDE_DIR:-/opt/agent-hub/claude}   # Claude tokens and (keys/) the API keys of other AIs, encrypted
WORK_DIR=${WORK_DIR:-/opt/agent-hub/work}         # repos/: the code the agents wrote (runner/workspace.py)
TUNNEL_DIR=${TUNNEL_DIR:-/home/admin/cloudflared}
SSH_DIR=${SSH_DIR:-/home/admin/.ssh}
MOUNT_POINT=${MOUNT_POINT-/mnt/backup}      # empty = do not require a mounted stick (tests)
DEST=${DEST:-/mnt/backup/agent-hub}
PASS_FILE=${PASS_FILE:-/etc/agent-hub-backup.pass}
KEEP_DAILY=${KEEP_DAILY:-7}
KEEP_WEEKLY=${KEEP_WEEKLY:-4}
DEPLOY_COPIES=${DEPLOY_COPIES:-/opt/agent-hub/backups}   # the copies made before each deploy (database, .env)
KEEP_COPY_DAYS=${KEEP_COPY_DAYS:-35}                      # as long as the nightly backups keep a state (7 days + 4 Sundays)

if [ -n "$MOUNT_POINT" ] && ! mountpoint -q "$MOUNT_POINT"; then
  echo "Backup stick is not mounted at $MOUNT_POINT" >&2
  exit 1
fi
mkdir -p "$DEST"
trap 'echo "$(date -Is) FAILED at line $LINENO" >> "$DEST/backup.log"' ERR

STAGE=$(mktemp -d /var/tmp/hub-backup.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT
P="$STAGE/payload"
mkdir -p "$P/data" "$P/ssh"

# 1. Database: SQLite's own backup call gives a consistent copy while the hub is running.
python3 - "$HUB_DIR/data/hub.db" "$P/hub.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PY

# 2. Everything else that is not in Git.
cp -a "$HUB_DIR/.env" "$P/hub.env"
cp -a "$TUNNEL_DIR/.env" "$P/tunnel.env"
cp -a "$TUNNEL_DIR/compose.yml" "$P/tunnel-compose.yml"
cp -a "$SSH_DIR/id_ed25519" "$SSH_DIR/id_ed25519.pub" "$P/ssh/"
cp -a "$CLAUDE_DIR" "$P/claude"
if [ -d "$WORK_DIR/repos" ]; then cp -a "$WORK_DIR/repos" "$P/repos"; fi   # task folders are not kept: work in progress
# Other files in data/ (later: uploads); the old database copies are skipped.
find "$HUB_DIR/data" -mindepth 1 -maxdepth 1 ! -name 'hub.db*' -exec cp -a {} "$P/data/" \;

# 3. Checksums, so a restore can tell that nothing is damaged.
(cd "$P" && find . -type f ! -name MANIFEST.sha256 -exec sha256sum {} + > MANIFEST.sha256)

# 4. Pack and encrypt. Written under a temporary name, renamed only when complete.
STAMP=$(date +%F)
OUT="$DEST/hub-$STAMP.tar.gz.gpg"
tar -C "$STAGE" -czf - payload \
  | gpg --batch --yes --pinentry-mode loopback --symmetric --cipher-algo AES256 \
        --passphrase-file "$PASS_FILE" -o "$OUT.part"
mv -f "$OUT.part" "$OUT"

# 5. Self-check: the file must decrypt and unpack.
gpg --batch --quiet --pinentry-mode loopback --decrypt --passphrase-file "$PASS_FILE" "$OUT" | tar -tz > /dev/null

# 6. Keep the newest KEEP_DAILY files, plus the newest KEEP_WEEKLY Sunday files beyond those.
daily=0; weekly=0
for f in $(ls -1 "$DEST"/hub-*.tar.gz.gpg | sort -r); do
  d=${f##*/hub-}; d=${d%%.*}
  if [ "$daily" -lt "$KEEP_DAILY" ]; then daily=$((daily + 1)); continue; fi
  if [ "$(date -d "$d" +%u)" = 7 ] && [ "$weekly" -lt "$KEEP_WEEKLY" ]; then weekly=$((weekly + 1)); continue; fi
  rm -- "$f"
done

# 7. Deploy copies older than KEEP_COPY_DAYS go, so data of a deleted account does not stay there either (15.11.2026).
if [ -d "$DEPLOY_COPIES" ]; then
  find "$DEPLOY_COPIES" -mindepth 1 -maxdepth 1 -type f -mtime +$((KEEP_COPY_DAYS - 1)) -delete
fi

SIZE=$(stat -c %s "$OUT")
echo "$(date -Is) ok $(basename "$OUT") $SIZE bytes" | tee -a "$DEST/backup.log" > "$DEST/last-ok.txt"
