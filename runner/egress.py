"""The only way out of the agent network: a small filtering proxy (CONNECT only, standard library).

The agent containers sit on a Docker network without any route to the outside (`internal: true`), so a
run can reach nothing but this proxy. The proxy listens twice, with two policies:

- "web" (port 3128): any host on port 443, but only if every address it resolves to is a public one.
  Web search and page fetching therefore work, while the home network, the Pi itself, the Docker
  networks, link-local and loopback addresses stay out of reach (no SSRF into the LAN).
- "api" (port 3129): only the hosts of Anthropic (the API and the login), nothing else. The code
  sandbox uses this one: Claude Code can talk to its API, and code it runs can reach nothing.
- "gateway" (port 3130, since 14.11.2026): the only way a run talks to the Claude API. Claude Code sends its
  requests here in plain HTTP (ANTHROPIC_BASE_URL, inside the agent network only) with the run's ticket as its
  token; the gateway swaps the ticket for the user's real token (runner/tokens.py) and sends the request on to
  api.anthropic.com over TLS. So the real token never enters a run: code in a run can not read it or send it out.

The proxy resolves names itself and connects to the address it checked (no second lookup that could
answer differently). It never looks into the traffic (HTTPS passes through) and logs only the
decision and the host name.
"""
import asyncio
import ipaddress
import os
import ssl
import sys
from dataclasses import dataclass

from runner import tokens

API_HOSTS = ("anthropic.com", "claude.ai", "claude.com")   # a host matches itself and its subdomains
HEAD_LIMIT = 8192
CONNECT_TIMEOUT = 10
IDLE_TIMEOUT = 120
TOTAL_TIMEOUT = 300
MAX_CLIENTS = 32
UPSTREAM = "api.anthropic.com"
GATEWAY_HEAD_LIMIT = 65536
GATEWAY_BODY_LIMIT = 64 * 1024 * 1024    # a request with images or long context; Claude Code always sends the length
GATEWAY_IDLE = 300                       # a long answer streams with pauses (thinking); the ping events keep it alive
GATEWAY_TOTAL = 1800
# Headers the gateway never passes on: the run's ticket, hop-by-hop headers, and anything about another host.
_DROP = {"authorization", "x-api-key", "host", "connection", "keep-alive", "proxy-authorization", "proxy-connection",
         "te", "trailer", "upgrade", "transfer-encoding", "content-length"}


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


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, idle: int = IDLE_TIMEOUT) -> None:
    try:
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), idle)
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


def parse_request(head: bytes) -> tuple[str, str, list[tuple[str, str]]] | None:
    """(method, path, headers) of a plain HTTP request to the gateway, or None. Only GET and POST to /v1/..."""
    try:
        lines = head.decode("latin-1").split("\r\n")
        method, path, version = lines[0].split(" ")
    except ValueError:
        return None
    if method not in ("GET", "POST") or not version.startswith("HTTP/1.") or not path.startswith("/v1/") \
            or any(c in path for c in "\\#") or "/../" in path or "://" in path:
        return None
    headers = []
    for line in lines[1:]:
        if not line:
            continue
        name, sep, value = line.partition(":")
        if not sep or not name or name != name.strip() or any(c in name for c in " \t"):
            return None
        headers.append((name, value.strip()))
    return method, path, headers


def rewrite(method: str, path: str, headers: list[tuple[str, str]], token: str, length: int) -> bytes:
    """The request as it goes to Anthropic: the real token instead of the ticket, one request per connection."""
    keep = [(n, v) for n, v in headers if n.lower() not in _DROP]
    out = [f"{method} {path} HTTP/1.1", f"Host: {UPSTREAM}", f"Authorization: Bearer {token}",
           *(f"{n}: {v}" for n, v in keep), f"Content-Length: {length}", "Connection: close", "", ""]
    return "\r\n".join(out).encode("latin-1")


async def _gateway_reply(writer: asyncio.StreamWriter, status: str, message: str) -> None:
    body = ('{"type":"error","error":{"type":"hub_gateway","message":"' + message + '"}}').encode()
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                 f"Connection: close\r\n\r\n".encode() + body)
    try:
        await writer.drain()
    except ConnectionError:
        pass


async def _open_upstream():
    addresses = await asyncio.wait_for(_resolve(UPSTREAM, 443), CONNECT_TIMEOUT)
    context = ssl.create_default_context()
    for address in addresses:   # connect to an address we checked, with the certificate checked for the name
        if not is_public(address):
            continue
        try:
            return await asyncio.wait_for(asyncio.open_connection(
                address, 443, ssl=context, server_hostname=UPSTREAM), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, OSError, ssl.SSLError):
            continue
    raise OSError("no upstream")


async def gateway(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, tickets_dir: str,
                  open_upstream=_open_upstream, log=print) -> None:
    """One request of a run: check it, swap ticket for token, pass it to Anthropic, stream the answer back.

    Exactly one request per connection: the body is read by its length and nothing after it is passed on, so a
    second request on the same connection can never reach Anthropic with the ticket in it. The log names the path
    and the status, never a header."""
    upstream_w = None
    try:
        try:
            head = await asyncio.wait_for(client_r.readuntil(b"\r\n\r\n"), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            return
        request = parse_request(head) if len(head) <= GATEWAY_HEAD_LIMIT else None
        if request is None:
            await _gateway_reply(client_w, "400 Bad Request", "bad request")
            return
        method, path, headers = request
        values = {n.lower(): v for n, v in headers}
        if "transfer-encoding" in values:
            await _gateway_reply(client_w, "411 Length Required", "length required")
            return
        try:
            length = int(values.get("content-length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= GATEWAY_BODY_LIMIT:
            await _gateway_reply(client_w, "413 Payload Too Large", "bad length")
            return
        auth = values.get("authorization", "")
        token = tokens.lookup(tickets_dir, auth[7:].strip()) if auth.lower().startswith("bearer ") else None
        if token is None:   # 403, not 401: an unknown ticket is the hub's matter, not a lost sign-in of the user
            log(f"gateway: refused {method} {path} (no valid ticket)")
            await _gateway_reply(client_w, "403 Forbidden", "no valid ticket")
            return
        body = await asyncio.wait_for(client_r.readexactly(length), GATEWAY_IDLE) if length else b""
        try:
            upstream_r, upstream_w = await open_upstream()
        except (asyncio.TimeoutError, OSError):
            await _gateway_reply(client_w, "502 Bad Gateway", "anthropic not reachable")
            return
        upstream_w.write(rewrite(method, path, headers, token, length) + body)
        await upstream_w.drain()
        first = await asyncio.wait_for(upstream_r.read(65536), GATEWAY_IDLE)
        status = first.split(b"\r\n", 1)[0].decode("latin-1", "replace")[9:12]
        log(f"gateway: {method} {path.split('?')[0]} -> {status or '?'}")
        if first:
            client_w.write(first)
            await client_w.drain()
            await asyncio.wait_for(_pipe(upstream_r, client_w, GATEWAY_IDLE), GATEWAY_TOTAL)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError, ssl.SSLError):
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


async def serve_gateway(host: str, port: int, tickets_dir: str, log=print) -> asyncio.AbstractServer:
    slots = asyncio.Semaphore(MAX_CLIENTS)

    async def on_client(reader, writer):
        async with slots:
            await gateway(reader, writer, tickets_dir, log=log)

    return await asyncio.start_server(on_client, host, port, limit=GATEWAY_HEAD_LIMIT * 2)


async def main() -> None:
    bind = os.environ.get("EGRESS_BIND", "0.0.0.0")
    servers = [
        await serve(WEB, bind, int(os.environ.get("EGRESS_WEB_PORT", "3128"))),
        await serve(API, bind, int(os.environ.get("EGRESS_API_PORT", "3129"))),
        await serve_gateway(bind, int(os.environ.get("EGRESS_GATEWAY_PORT", "3130")),
                            os.environ.get("HUB_TICKETS_DIR", "/tickets")),
    ]
    print("egress: listening (web 3128, api 3129, gateway 3130)", file=sys.stderr, flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
