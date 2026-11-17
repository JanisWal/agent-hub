"""The web service's line to the broker (broker/broker.py; 17.11.2026): one TCP connection per request inside the
Docker network `devices`, one JSON line out, JSON lines back. Standard library only.

Only routes that checked the user and the ownership call this (devices.payload builds the one device). The token
HUB_BROKER_TOKEN goes with every request; without HUB_BROKER_URL ("host:port") the broker is off and every call fails
with "off". Errors are BrokerError(code), the codes of the broker plus "off".
"""
import asyncio
import json
import os
import socket

TIMEOUTS = {"hostkey": 15, "resolve": 8, "online": 6, "test": 45, "start": 10, "job": 5, "logs": 45, "keygen": 10,
            "ls": 30, "read": 30, "write": 30, "rename": 20, "delete": 20, "mkdir": 20}
MAX_LINE = 256 * 1024


class BrokerError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _address() -> tuple[str, int]:
    value = os.environ.get("HUB_BROKER_URL", "").strip()
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise BrokerError("off")
    return host, int(port)


def available() -> bool:
    try:
        _address()
    except BrokerError:
        return False
    return bool(os.environ.get("HUB_BROKER_TOKEN"))


def _request(op: str, device: dict | None, origin: str, args: dict) -> bytes:
    return json.dumps({"token": os.environ.get("HUB_BROKER_TOKEN", ""), "op": op, "device": device or {},
                       "origin": origin, "args": args}, separators=(",", ":")).encode() + b"\n"


def _answer(line: bytes) -> dict:
    if not line:
        raise BrokerError("failed")
    try:
        message = json.loads(line)
    except ValueError:
        raise BrokerError("failed") from None
    if not message.get("ok"):
        raise BrokerError(str(message.get("error") or "failed"))
    return message


def call(op: str, device: dict | None = None, origin: str = "human", **args) -> dict:
    """One request with one answer (everything but shell, get and put)."""
    host, port = _address()
    try:
        with socket.create_connection((host, port), timeout=TIMEOUTS.get(op, 30)) as sock:
            sock.sendall(_request(op, device, origin, args))
            reader = sock.makefile("rb")
            return _answer(reader.readline(MAX_LINE))
    except (OSError, socket.timeout):
        raise BrokerError("off") from None


def stream(op: str, device: dict, **args):
    """A request whose answer is several lines (get): yields the lines as dicts after the first ok."""
    host, port = _address()
    try:
        sock = socket.create_connection((host, port), timeout=120)
    except OSError:
        raise BrokerError("off") from None
    reader = sock.makefile("rb")
    sock.sendall(_request(op, device, "human", args))
    first = _answer(reader.readline(MAX_LINE))

    def lines():
        try:
            while True:
                line = reader.readline(MAX_LINE)
                if not line:
                    return
                message = json.loads(line)
                yield message
                if message.get("end") or message.get("ok") is False:
                    return
        finally:
            sock.close()
    return first, lines()


def upload(device: dict, path: str, size: int, chunks) -> dict:
    """put: send the file in base64 lines; `chunks` yields bytes."""
    import base64
    host, port = _address()
    try:
        with socket.create_connection((host, port), timeout=120) as sock:
            reader = sock.makefile("rb")
            sock.sendall(_request("put", device, "human", {"path": path, "size": size}))
            _answer(reader.readline(MAX_LINE))
            for data in chunks:
                sock.sendall(json.dumps({"data": base64.b64encode(data).decode("ascii")}).encode() + b"\n")
            sock.sendall(b'{"end":true}\n')
            return _answer(reader.readline(MAX_LINE))
    except (OSError, socket.timeout):
        raise BrokerError("off") from None


async def open_shell(device: dict, cols: int, rows: int):
    """The shell: (reader, writer) of an asyncio connection after the broker said ok."""
    host, port = _address()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, limit=MAX_LINE + 1024), 10)
    except (OSError, asyncio.TimeoutError):
        raise BrokerError("off") from None
    writer.write(_request("shell", device, "human", {"size": [cols, rows]}))
    await writer.drain()
    _answer(await asyncio.wait_for(reader.readline(), 30))
    return reader, writer
