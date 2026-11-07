"""One sign-in of Claude Code, driven through a pseudo terminal. Standard library only.

`claude auth login` prints "If the browser didn't open, visit: <link>" and then waits at
"Paste code here if prompted >". We read the link from that output and later type the code the user
got. The code is only written into the terminal of that one container, never printed or stored.
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


def extract_login_url(raw: str) -> str | None:
    """The sign-in link in what the terminal printed, or None (yet)."""
    text = _OSC8.sub(lambda m: " " + m.group(1) + " ", raw)
    text = _ESCAPES.sub("", text)
    match = _URL.search(text)
    return match.group(0) if match else None


class LoginSession:
    """A running `docker run ... claude auth login` with its terminal."""

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
            self.output = self.output[-20000:]
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
        os.write(self.master, code.strip().encode() + b"\r")
        self.code_sent_at = time.time()

    def exit_code(self) -> int | None:
        """None while the sign-in is still running."""
        self._pump(0.1)
        return self.process.poll()

    def close(self) -> None:
        """Stop the container (if it still runs) and release the terminal."""
        subprocess.run([self.docker, "rm", "-f", self.container], capture_output=True)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        try:
            os.close(self.master)
        except OSError:
            pass
