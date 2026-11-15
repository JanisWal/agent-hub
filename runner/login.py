"""One sign-in of Claude Code, driven through a pseudo terminal. Standard library only.

`claude setup-token` (like `claude auth login`) prints "If the browser didn't open, visit: <link>" and then waits
at "Paste code here if prompted >". We read the link from that output and later type the code the user got. The
code is only written into the terminal of that one container, never printed or stored. At the end setup-token
prints the long-lived token (sk-ant-oat01-...) and then waits for a key instead of ending (that is why the first
try on 08.11.2026 failed): `extract_token` takes it out as soon as it is there, the runner then stops the container.
"""
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import termios
import time

# The link may be wrapped in an OSC 8 hyperlink (ESC ] 8 ; ; URL ST): take the URL out of it first.
_OSC8 = re.compile(r"\x1b\]8;[^;\x07\x1b]*;([^\x07\x1b]*)(?:\x07|\x1b\\)")
_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_URL = re.compile(r"https://claude\.(?:com|ai)/[^\s\x1b\x07\"'<>]+")
_TOKEN = re.compile(r"sk-ant-oat[0-9]{2}-[A-Za-z0-9_-]{20,400}")
# setup-token draws its result with a terminal UI: "Your OAuth token (valid for ...):", the token, "Store this token ...".
# The UI may wrap the long token over two lines and draws the screen more than once (14.11.2026: the first version
# saw a wrapped token as two different ones and took none). So the block between the two lines counts first.
_BLOCK = re.compile(r"Your OAuth token[^\n]*\n(.*?)(?=Store this token|Use this token)", re.S)
_LONG = re.compile(r"[A-Za-z0-9_\-#%.=&?/:+~*]{24,}")   # with "*": the masked code shows its last characters


def extract_login_url(raw: str) -> str | None:
    """The sign-in link in what the terminal printed, or None (yet)."""
    text = _OSC8.sub(lambda m: " " + m.group(1) + " ", raw)
    text = _ESCAPES.sub("", text)
    match = _URL.search(text)
    return match.group(0) if match else None


def _clean(raw: str) -> str:
    return _ESCAPES.sub("", _OSC8.sub(lambda m: " " + m.group(1) + " ", raw)).replace("\r", "\n")


def extract_token(raw: str) -> str | None:
    """The token setup-token printed, or None (yet). No guessing: from the newest result block (a token wrapped over
    lines is put together again); else the one token in the output, where shorter ones may only be its beginning
    (a screen drawn while the token was still being written or wrapped)."""
    text = _clean(raw)
    for block in reversed(_BLOCK.findall(text)):
        joined = re.sub(r"\s+", "", block)
        if _TOKEN.fullmatch(joined):
            return joined
    found = sorted(set(_TOKEN.findall(text)), key=len)
    if found and all(found[-1].startswith(part) for part in found):
        return found[-1]
    return None


def redacted_tail(raw: str, size: int = 700) -> str:
    """The end of what the terminal showed, for the log when a sign-in fails: every long run of letters, digits and
    URL characters (a token, the code, the link) is replaced by its length, so nothing secret reaches the log."""
    text = _LONG.sub(lambda m: f"<{len(m.group(0))}>", _clean(raw))
    return re.sub(r"\s+", " ", text).strip()[-size:]


class LoginSession:
    """A running `docker run ... claude setup-token` with its terminal."""

    def __init__(self, command: list[str], container: str, docker: str = "docker"):
        self.container = container
        self.docker = docker
        self.output = ""
        self.code_sent_at: float | None = None
        master, slave = pty.openpty()
        # Very wide, so the terminal never breaks the link into lines.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 2000, 0, 0))
        self.master = master
        self.process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)

    def _pump(self, wait: float) -> None:
        end = time.time() + wait
        while True:
            ready, _, _ = select.select([self.master], [], [], max(0.0, end - time.time()))
            if not ready:
                return
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                return
            if not chunk:
                return
            self.output += chunk.decode(errors="replace")
            self.output = self.output[-200000:]   # the screen is drawn again and again: keep enough
            end = time.time() + 0.05   # more may follow right away

    def url(self, timeout: float = 30) -> str | None:
        """Wait for the sign-in link."""
        end = time.time() + timeout
        while time.time() < end and self.process.poll() is None:
            self._pump(0.5)
            found = extract_login_url(self.output)
            if found:
                return found
        return extract_login_url(self.output)

    def send_code(self, code: str) -> None:
        """Type the code, then press Enter on its own: setup-token takes code and Enter in one go as pasted text and
        never sends it (found on 14.11.2026, the reason the first sign-ins ran into the time limit)."""
        self.mark = len(self.output)
        os.write(self.master, code.strip().encode())
        self._pump(0.6)
        os.write(self.master, b"\r")
        self.code_sent_at = time.time()

    def refused(self) -> bool:
        """Claude did not accept the code ("OAuth error: That code wasn't accepted ... Press Enter to retry"): the
        sign-in waits for ever then, so it counts as failed at once."""
        return self.code_sent_at is not None and "OAuth error" in _clean(self.output[getattr(self, "mark", 0):])

    def exit_code(self) -> int | None:
        """None while the sign-in is still running."""
        self._pump(0.1)
        return self.process.poll()

    def close(self) -> None:
        """Stop the container (if it still runs) and release the terminal. Forgets the output (it may hold the token)."""
        self.output = ""
        subprocess.run([self.docker, "rm", "-f", self.container], capture_output=True)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        try:
            os.close(self.master)
        except OSError:
            pass
