#!/usr/bin/env bash
# One-time setup of the nightly backup on the Pi. Run by hand: sudo bash deploy/setup-backup.sh [STICK_UUID]
# What it changes on the system: installs gnupg if missing, adds one line to /etc/fstab (nofail), creates /mnt/backup,
# creates the passphrase file /etc/agent-hub-backup.pass (only if missing), installs the script and a systemd timer.
# It never formats the stick.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Please run with sudo." >&2; exit 1; }
UUID=${1:-BA30-7261}
HERE=$(cd "$(dirname "$0")" && pwd)
PASS_FILE=/etc/agent-hub-backup.pass

command -v gpg > /dev/null || apt-get install -y gnupg

mkdir -p /mnt/backup
if ! grep -q "UUID=$UUID" /etc/fstab; then
  echo "UUID=$UUID /mnt/backup vfat umask=0077,nofail,x-systemd.device-timeout=10 0 0" >> /etc/fstab
  systemctl daemon-reload
fi
mountpoint -q /mnt/backup || mount /mnt/backup
mkdir -p /mnt/backup/agent-hub

if [ ! -f "$PASS_FILE" ]; then
  umask 077
  head -c 24 /dev/urandom | base64 > "$PASS_FILE"
  echo
  echo "=============================================================="
  echo " Backup password (shown only now, write it down and put it into"
  echo " your password manager; without it the backups cannot be opened):"
  echo
  echo "   $(cat "$PASS_FILE")"
  echo "=============================================================="
  echo
else
  echo "Password file already exists, left unchanged."
fi

install -m 700 "$HERE/backup.sh" /usr/local/sbin/agent-hub-backup

cat > /etc/systemd/system/agent-hub-backup.service <<'UNIT'
[Unit]
Description=Agent-Hub encrypted backup to the USB stick
RequiresMountsFor=/mnt/backup

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/agent-hub-backup
UNIT

cat > /etc/systemd/system/agent-hub-backup.timer <<'UNIT'
[Unit]
Description=Nightly Agent-Hub backup

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now agent-hub-backup.timer
echo "Done. First run now with:  sudo systemctl start agent-hub-backup.service"
echo "Check the result with:     cat /mnt/backup/agent-hub/last-ok.txt"
