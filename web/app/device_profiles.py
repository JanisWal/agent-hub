"""Operating-system profiles of devices (PROJEKT.md 11a, Stufe 4; 17.11.2026): the one source of the fixed commands
behind the buttons, the line for `sudoers`, the log views and the steps of "set up on the device".

Used by the web service (setup guide, sudoers line, which buttons work) and by the broker (the commands it runs). The
broker never runs a command that is not in here, and nothing a user or an AI writes ever goes into one: the only
values put in are the SSH user name and the public key in the setup guide (both checked by devices.py), never into
a command the broker runs. Standard library only, no imports from the hub, so the broker image can copy this file.

`{sudo}` in a command is replaced by the broker: "sudo -n " with a key (the sudoers rule must allow the command
without a password), "sudo -S -p '' " with a stored password (the password goes on stdin, only for a human). A family
without a command for an action shows that button greyed out; an unknown system gets no buttons at all (never guess).
"""
import re

FAMILIES = ("debian", "fedora", "arch", "suse", "alpine", "macos", "windows")
ACTIONS = ("reboot", "poweroff", "updates_check", "updates_install")
LOG_SOURCES = ("journal", "kernel")
REBOOT_MARK = "AGENTHUB_REBOOT_REQUIRED"
COUNT_MARK = "AGENTHUB_UPDATES="

_DEBIAN_UPGRADE = "/usr/bin/apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade"
_LINUX_POWER = {"reboot": "{sudo}/usr/bin/systemctl reboot", "poweroff": "{sudo}/usr/bin/systemctl poweroff"}
_LINUX_LOGS = {"journal": "journalctl -n 200 --no-pager 2>&1 | tail -n 200",
               "kernel": "dmesg 2>&1 | tail -n 200"}

PROFILES = {
    "debian": {   # Raspberry Pi OS, Debian, Ubuntu, Linux Mint: apt for system and programs, snap and flatpak if there
        "name": "Debian / Ubuntu / Raspberry Pi OS",
        **_LINUX_POWER,
        "updates_check": ("{sudo}/usr/bin/apt-get update -qq >/dev/null 2>&1; "
                          "n=$(/usr/bin/apt list --upgradable 2>/dev/null | grep -c /); "
                          "s=0; command -v snap >/dev/null 2>&1 && s=$(snap refresh --list 2>/dev/null | tail -n +2 | grep -c .); "
                          "f=0; command -v flatpak >/dev/null 2>&1 && f=$(flatpak remote-ls --updates 2>/dev/null | grep -c .); "
                          "echo " + COUNT_MARK + "$((n + s + f))"),
        "updates_install": ("{sudo}" + _DEBIAN_UPGRADE + " && "
                            "{ command -v snap >/dev/null 2>&1 && {sudo}/usr/bin/snap refresh || true; } && "
                            "{ command -v flatpak >/dev/null 2>&1 && flatpak update -y --noninteractive || true; }; "
                            "test -f /var/run/reboot-required && echo " + REBOOT_MARK + "; true"),
        "sudo": ["/usr/bin/systemctl reboot", "/usr/bin/systemctl poweroff", "/usr/bin/apt-get update -qq",
                 _DEBIAN_UPGRADE, "/usr/bin/snap refresh"],
        "logs": _LINUX_LOGS,
        "ssh_on": "sudo apt install -y openssh-server && sudo systemctl enable --now ssh",
    },
    "fedora": {   # Fedora, RHEL, CentOS Stream, Rocky, Alma: dnf (exit code 100 = updates there)
        "name": "Fedora / RHEL",
        **_LINUX_POWER,
        "updates_check": "n=$(/usr/bin/dnf -q check-update 2>/dev/null | grep -c '^[^ ]'); echo " + COUNT_MARK + "$n",
        "updates_install": ("{sudo}/usr/bin/dnf -y upgrade && { command -v flatpak >/dev/null 2>&1 && "
                            "flatpak update -y --noninteractive || true; }; "
                            "/usr/bin/dnf needs-restarting -r >/dev/null 2>&1 || echo " + REBOOT_MARK + "; true"),
        "sudo": ["/usr/bin/systemctl reboot", "/usr/bin/systemctl poweroff", "/usr/bin/dnf -y upgrade"],
        "logs": _LINUX_LOGS,
        "ssh_on": "sudo dnf install -y openssh-server && sudo systemctl enable --now sshd",
    },
    "arch": {     # Arch, Manjaro, EndeavourOS: checkupdates is in pacman-contrib
        "name": "Arch Linux",
        **_LINUX_POWER,
        "updates_check": "n=$(checkupdates 2>/dev/null | grep -c .); echo " + COUNT_MARK + "$n",
        "updates_install": "{sudo}/usr/bin/pacman -Syu --noconfirm",
        "sudo": ["/usr/bin/systemctl reboot", "/usr/bin/systemctl poweroff", "/usr/bin/pacman -Syu --noconfirm"],
        "logs": _LINUX_LOGS,
        "ssh_on": "sudo pacman -S --needed openssh && sudo systemctl enable --now sshd",
    },
    "suse": {
        "name": "openSUSE",
        **_LINUX_POWER,
        "updates_check": "n=$(/usr/bin/zypper -q list-updates 2>/dev/null | grep -c '^v '); echo " + COUNT_MARK + "$n",
        "updates_install": "{sudo}/usr/bin/zypper -n update",
        "sudo": ["/usr/bin/systemctl reboot", "/usr/bin/systemctl poweroff", "/usr/bin/zypper -n update"],
        "logs": _LINUX_LOGS,
        "ssh_on": "sudo zypper install -y openssh && sudo systemctl enable --now sshd",
    },
    "alpine": {
        "name": "Alpine Linux",
        "reboot": "{sudo}/sbin/reboot", "poweroff": "{sudo}/sbin/poweroff",
        "updates_check": "{sudo}/sbin/apk update -q >/dev/null 2>&1; n=$(/sbin/apk -u list 2>/dev/null | grep -c .); echo " + COUNT_MARK + "$n",
        "updates_install": "{sudo}/sbin/apk upgrade",
        "sudo": ["/sbin/reboot", "/sbin/poweroff", "/sbin/apk update -q", "/sbin/apk upgrade"],
        "logs": {"journal": "tail -n 200 /var/log/messages 2>&1", "kernel": "dmesg 2>&1 | tail -n 200"},
        "ssh_on": "sudo apk add openssh && sudo rc-update add sshd && sudo rc-service sshd start",
    },
    "macos": {    # softwareupdate for macOS and Apple's programs, Homebrew for the others if it is there
        "name": "macOS",
        "reboot": "{sudo}/sbin/shutdown -r now", "poweroff": "{sudo}/sbin/shutdown -h now",
        "updates_check": ("n=$(/usr/sbin/softwareupdate -l 2>&1 | grep -c '^\\* '); b=0; "
                          "command -v brew >/dev/null 2>&1 && b=$(brew outdated -q 2>/dev/null | grep -c .); "
                          "echo " + COUNT_MARK + "$((n + b))"),
        "updates_install": ("{sudo}/usr/sbin/softwareupdate -i -a 2>&1 | tee /dev/stderr | grep -qi restart && echo "
                            + REBOOT_MARK + "; command -v brew >/dev/null 2>&1 && brew upgrade; true"),
        "sudo": ["/sbin/shutdown -r now", "/sbin/shutdown -h now", "/usr/sbin/softwareupdate -i -a"],
        "logs": {"journal": "log show --last 10m --style compact 2>&1 | tail -n 200", "kernel": "dmesg 2>&1 | tail -n 200"},
        "ssh_on": "",   # System Settings, General, Sharing, Remote Login (guide text)
    },
    "windows": {  # OpenSSH server of Windows 10/11 and Server 2019+; Windows Update has no built-in command
        "name": "Windows",
        "reboot": "shutdown /r /t 0", "poweroff": "shutdown /s /t 0",
        "updates_check": None, "updates_install": None,
        "sudo": [],
        "logs": {"journal": "powershell -NoProfile -Command \"Get-WinEvent -LogName System -MaxEvents 100 | "
                            "Format-Table -AutoSize -Wrap TimeCreated,LevelDisplayName,Message | Out-String -Width 200\""},
        "ssh_on": ("Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; "
                   "Start-Service sshd; Set-Service -Name sshd -StartupType Automatic"),
    },
}

_IDS = {"debian": "debian", "ubuntu": "debian", "raspbian": "debian", "linuxmint": "debian", "pop": "debian",
        "fedora": "fedora", "rhel": "fedora", "centos": "fedora", "rocky": "fedora", "almalinux": "fedora",
        "arch": "arch", "manjaro": "arch", "endeavouros": "arch",
        "opensuse": "suse", "opensuse-leap": "suse", "opensuse-tumbleweed": "suse", "sles": "suse", "suse": "suse",
        "alpine": "alpine"}
DETECT = "uname -s 2>/dev/null; cat /etc/os-release 2>/dev/null; sw_vers 2>/dev/null"
DETECT_WINDOWS = "cmd /c ver"
SUDO_TEST = "sudo -n true"
_SUDOERS_SPECIAL = re.compile(r"([\\,:=!@()])")
_USER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,63}")


def detect(output: str, windows: str = "") -> tuple[str, str]:
    """(family, readable name) from the output of DETECT (or DETECT_WINDOWS); family '' when unknown."""
    if "Microsoft Windows" in windows or "Microsoft Windows" in output:
        line = next((l for l in (windows or output).splitlines() if "Microsoft Windows" in l), "Windows")
        return "windows", line.strip()[:80]
    if "Darwin" in output:
        version = re.search(r"ProductVersion:\s*([\d.]+)", output)
        return "macos", "macOS " + (version.group(1) if version else "")
    fields = dict(re.findall(r'^([A-Z_]+)=\"?([^\"\n]*)\"?$', output, re.M))
    pretty = fields.get("PRETTY_NAME", "")[:80]
    for word in [fields.get("ID", "")] + fields.get("ID_LIKE", "").split():
        family = _IDS.get(word.lower()) or (_IDS["opensuse"] if word.lower().startswith("opensuse") else None)
        if family:
            return family, pretty or PROFILES[family]["name"]
    return "", pretty


def command(family: str, action: str) -> str | None:
    """The command of an action for a family (with `{sudo}` still in it), or None if it has none."""
    profile = PROFILES.get(family)
    if profile is None or action not in ACTIONS:
        return None
    return profile.get(action)


def supported(family: str) -> tuple[str, ...]:
    """The actions a family can do; empty for an unknown system."""
    return tuple(a for a in ACTIONS if command(family, a))


def log_command(family: str, source: str) -> str | None:
    profile = PROFILES.get(family)
    return None if profile is None else profile["logs"].get(source)


def count_updates(output: str) -> int | None:
    """How many updates the check found (the marker line), None if the output has no marker."""
    found = re.search(re.escape(COUNT_MARK) + r"(\d+)", output or "")
    return int(found.group(1)) if found else None


def sudoers(family: str, user: str) -> str:
    """The line for /etc/sudoers.d/agent-hub that allows exactly the commands of the buttons without a password, for
    this user. Special characters of sudoers are escaped. Empty for systems without sudo (Windows) or a bad name."""
    profile = PROFILES.get(family)
    if profile is None or not profile["sudo"] or not _USER.fullmatch(user or ""):
        return ""
    commands = ", ".join(_SUDOERS_SPECIAL.sub(r"\\\1", c) for c in profile["sudo"])
    return f"{user} ALL=(root) NOPASSWD: {commands}"


def guide(family: str, user: str, public_key: str, hostname: str) -> list[tuple[str, str]]:
    """The steps of "set up on the device": (step, command) with the device's values put in; the step's text comes
    from i18n.py ("setup_<step>_<family>" or "setup_<step>"). An empty command means the step is text only."""
    profile = PROFILES.get(family) or PROFILES["debian"]
    user = user if _USER.fullmatch(user or "") else "agenthub"
    key = public_key.strip() if re.fullmatch(r"ssh-[a-z0-9-]+ [A-Za-z0-9+/=]+( [\w@.-]*)?", public_key.strip() or "") else ""
    windows = family == "windows"
    steps = [("ssh_on", profile["ssh_on"])]
    if windows:
        steps.append(("user", f"net user {user} * /add"))
        steps.append(("key", ("$k = '" + key + "'; Add-Content -Path \"$env:ProgramData\\ssh\\administrators_authorized_keys\" "
                              "-Value $k; icacls \"$env:ProgramData\\ssh\\administrators_authorized_keys\" /inheritance:r "
                              "/grant \"Administrators:F\" /grant \"SYSTEM:F\"") if key else ""))
    else:
        steps.append(("user", "" if family == "macos" else f"sudo adduser {user}"))
        steps.append(("key", (f"sudo -u {user} sh -c 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                              f"echo \"{key}\" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'") if key else ""))
        rule = sudoers(family, user)
        steps.append(("sudoers", f"echo '{rule}' | sudo tee /etc/sudoers.d/agent-hub && sudo chmod 440 "
                                 f"/etc/sudoers.d/agent-hub && sudo visudo -c" if rule else ""))
        steps.append(("no_password", "" if family == "macos" else
                      "echo 'PasswordAuthentication no' | sudo tee /etc/ssh/sshd_config.d/10-agent-hub.conf && "
                      "sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd"))
    steps.append(("test", ""))
    return steps
