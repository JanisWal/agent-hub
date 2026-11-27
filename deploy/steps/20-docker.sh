#!/usr/bin/env bash
# Docker with Compose: used as it is when it is there (other containers stay untouched), else installed from Docker's
# own package source (Debian, Raspberry Pi OS, Ubuntu). On a Raspberry Pi the memory limits of containers need a boot
# option; then the server needs one restart.
set -euo pipefail
. "$STEPS/lib.sh"
say "Docker"
if docker compose version > /dev/null 2>&1; then
  note "Vorhanden: $(docker --version | cut -d, -f1), Compose $(docker compose version --short)"
else
  . /etc/os-release
  case "${ID:-}" in
    debian|raspbian) repo=debian ;;
    ubuntu) repo=ubuntu ;;
    *) die "Docker fehlt. Auf diesem System (${PRETTY_NAME:-unbekannt}) bitte Docker mit Compose selbst installieren und neu starten." ;;
  esac
  note "Installiere Docker aus der offiziellen Paketquelle …"
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$repo/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$repo ${VERSION_CODENAME:?} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin
  systemctl enable --now docker > /dev/null 2>&1 || true
  docker compose version > /dev/null || die "Docker ließ sich nicht starten."
fi
for cmdline in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
  if [ -f "$cmdline" ]; then
    if ! grep -q "cgroup_memory=1" "$cmdline"; then
      sed -i '1 s/$/ cgroup_enable=memory cgroup_memory=1/' "$cmdline"
      touch "$REBOOT_MARK"
      note "Speichergrenzen für Container eingeschaltet (wirkt nach einem Neustart)."
    fi
    break
  fi
done
