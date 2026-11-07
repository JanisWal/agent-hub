"""The only way out of the agent network: a small filtering proxy (CONNECT only, standard library).

The agent containers sit on a Docker network without any route to the outside (`internal: true`), so a
run can reach nothing but this proxy. The proxy listens twice, with two policies:

- "web" (port 3128): any host on port 443, but only if every address it resolves to is a public one.
  Web search and page fetching therefore work, while the home network, the Pi itself, the Docker
  networks, link-local and loopback addresses stay out of reach (no SSRF into the LAN).
- "api" (port 3129): only the hosts of Anthropic (the API and the login), nothing else. The code
  sandbox uses this one: Claude Code can talk to its API, and code it runs can reach nothing.

The proxy resolves names itself and connects to the address it checked (no second lookup that could
answer differently). It never looks into the traffic (HTTPS passes through) and logs only the
decision and the host name.
"""
import asyncio
import ipaddress
import os
import sys
from dataclasses import dataclass

API_HOSTS = ("anthropic.com", "claude.ai", "claude.com")   # a host matches itself and its subdomains
HEAD_LIMIT = 8192
CONNECT_TIMEOUT = 10
IDLE_TIMEOUT = 120
TOTAL_TIMEOUT = 300
MAX_CLIENTS = 32


@dataclass(frozen=True)
class Policy:
    hosts: tuple[str, ...] | None = None   # None = any host; else only these hosts and their subdomains
    ports: tuple[int, ...] = (443,)
    allow_private: bool = False            # only for tests: addresses that are not public are refused

    def host_allowed(self, host: str) -> bool:
        if self.hosts is None:
            return True
        return any(host == h or host.endswith("." + h) for h in self.hosts)


WEB = Policy()
API = Policy(hosts=API_HOSTS)


def is_public(address: str) -> bool:
    """True only for a global unicast address: no private, loopback, link-local, CGNAT, multicast or reserved one."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def parse_connect(head: bytes) -> tuple[str, int] | None:
    """(host, port) from `CONNECT host:port HTTP/1.x`, else None."""
    try:
        line = head.split(b"\r\n", 1)[0].decode("ascii")
        method, target, version = line.split(" ")
    except (UnicodeDecodeError, ValueError):
        return None
    if method != "CONNECT" or not version.startswith("HTTP/"):
        return None
    host, _, port = target.rpartition(":")
    host = host.strip("[]").lower().rstrip(".")
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        return None
    return host, int(port)


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=0)
    seen: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in seen:
            seen.append(address)
    return seen


async def _reply(writer: asyncio.StreamWriter, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())
    try:
        await writer.drain()
    except ConnectionError:
        pass


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


async def handle(policy: Policy, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter,
                 log=print) -> None:
    """One client: read the CONNECT line, check it against the policy, then pass the bytes through."""
    upstream_w = None
    try:
        try:
            head = await asyncio.wait_for(client_r.readuntil(b"\r\n\r\n"), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            return
        if len(head) > HEAD_LIMIT:
            await _reply(client_w, "431 Request Header Fields Too Large")
            return
        target = parse_connect(head)
        if target is None:
            await _reply(client_w, "405 Method Not Allowed")   # plain HTTP is not carried: https only
            return
        host, port = target
        if port not in policy.ports or not policy.host_allowed(host):
            log(f"egress: refused {host}:{port} (policy)")
            await _reply(client_w, "403 Forbidden")
            return
        try:
            addresses = await asyncio.wait_for(_resolve(host, port), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, OSError):
            await _reply(client_w, "502 Bad Gateway")
            return
        if not addresses or (not policy.allow_private and not all(is_public(a) for a in addresses)):
            log(f"egress: refused {host}:{port} (not a public address)")
            await _reply(client_w, "403 Forbidden")
            return
        upstream_r = None
        for address in addresses:   # connect to an address we have checked, not to the name again
            try:
                upstream_r, upstream_w = await asyncio.wait_for(asyncio.open_connection(address, port), CONNECT_TIMEOUT)
                break
            except (asyncio.TimeoutError, OSError):
                continue
        if upstream_r is None:
            await _reply(client_w, "502 Bad Gateway")
            return
        log(f"egress: ok {host}:{port}")
        client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_w.drain()
        await asyncio.wait_for(
            asyncio.gather(_pipe(client_r, upstream_w), _pipe(upstream_r, client_w)), TOTAL_TIMEOUT)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        for w in (client_w, upstream_w):
            if w is not None:
                try:
                    w.close()
                except OSError:
                    pass


async def serve(policy: Policy, host: str, port: int, log=print) -> asyncio.AbstractServer:
    slots = asyncio.Semaphore(MAX_CLIENTS)

    async def on_client(reader, writer):
        async with slots:
            await handle(policy, reader, writer, log)

    return await asyncio.start_server(on_client, host, port, limit=HEAD_LIMIT * 2)


async def main() -> None:
    bind = os.environ.get("EGRESS_BIND", "0.0.0.0")
    servers = [
        await serve(WEB, bind, int(os.environ.get("EGRESS_WEB_PORT", "3128"))),
        await serve(API, bind, int(os.environ.get("EGRESS_API_PORT", "3129"))),
    ]
    print("egress: listening (web 3128, api 3129)", file=sys.stderr, flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
