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
- "gateway mistral" (port 3131, since 15.11.2026): the same for Mistral Vibe: its API key never enters a run, the
  ticket (which names its AI, runner/tokens.py) is swapped for the key and the request goes to api.mistral.ai.
- "gateway chatgpt" (port 3133, since 21.11.2026): ChatGPT through Codex with the user's ChatGPT sign-in (no API key).
  The run's "access token" is a JWT-shaped wrapper of its ticket (runner/codex.py); the gateway takes the ticket out,
  puts in the real token and the account id from the ticket, and passes only Codex's model calls on to chatgpt.com.
- "gateway custom" (port 3132, since 20.11.2026): the user's own AI (any OpenAI-compatible API, runner/hubloop.py). The
  address stands in the ticket, never in the request: only the model calls go there, over TLS to a public address, or
  for the owner's own AI also in the home network (10/8, 192.168/16, Tailscale 100.64/10; never the Docker networks
  172.16/12, loopback or link-local), there plain http is allowed too.

The proxy resolves names itself and connects to the address it checked (no second lookup that could
answer differently). It never looks into the traffic (HTTPS passes through) and logs only the
decision and the host name.
"""
import asyncio
import ipaddress
import os
import re
import ssl
import sys
from dataclasses import dataclass

from runner import codex, tokens

API_HOSTS = ("anthropic.com", "claude.ai", "claude.com")   # a host matches itself and its subdomains
HEAD_LIMIT = 8192
CONNECT_TIMEOUT = 10
IDLE_TIMEOUT = 120
TOTAL_TIMEOUT = 300
MAX_CLIENTS = 32
# The gateways: AI -> (upstream host, port). A ticket only works at the gateway of its own AI.
GATEWAYS = {"claude": ("api.anthropic.com", 3130), "mistral": ("api.mistral.ai", 3131), "custom": ("", 3132),
            "chatgpt": ("chatgpt.com", 3133)}
PATH_ROOT = {"chatgpt": ("/backend-api/", "/v1/")}   # where a gateway's paths begin (the others: "/v1/")
HOME_NETS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "192.168.0.0/16", "100.64.0.0/10"))
# What a run may ask of its AI (20.11.2026): Claude only the model calls; Mistral everything but what costs money apart
# from the model calls or stores data with the provider (Vibe's own calls were not all known, so a list of what never).
GATEWAY_PATHS = {"claude": ("/v1/messages", "/v1/models"), "custom": ("/v1/chat/completions", "/v1/models"),
                 "chatgpt": ("/backend-api/codex/responses", "/backend-api/codex/models", "/v1/responses", "/v1/models")}
OPENAI_API = ("api.openai.com", ("/v1/responses", "/v1/models"))   # where ChatGPT goes with the user's API key
GATEWAY_NEVER = {"mistral": ("/v1/files", "/v1/libraries", "/v1/batch", "/v1/fine_tuning", "/v1/billing",
                             "/v1/workspaces", "/v1/audio")}
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


def home_address(address: str) -> bool:
    """True for an address of a home network (HOME_NETS) the owner's own AI may be reached at."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.version == 4 and any(ip in net for net in HOME_NETS)


@dataclass(frozen=True)
class Target:
    """Where the gateway of the user's own AI sends a request: from the ticket's address (tokens.ENDPOINT)."""
    host: str
    port: int
    tls: bool
    base: str          # the path before /chat/completions, e.g. "/v1" or "/api/v1"
    lan: bool

    @classmethod
    def of(cls, endpoint: str, lan: bool) -> "Target | None":
        match = re.fullmatch(r"(https?)://([A-Za-z0-9.-]{1,253})(?::([0-9]{1,5}))?(/[A-Za-z0-9._~/-]{0,200})?",
                             endpoint or "")
        if not match:
            return None
        scheme, host, port, base = match.groups()
        port = int(port or (443 if scheme == "https" else 80))
        if not 0 < port < 65536 or (scheme == "http" and not lan):
            return None
        return cls(host.lower().rstrip("."), port, scheme == "https", (base or "").rstrip("/"), lan)


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


def parse_request(head: bytes, root: str = "/v1/") -> tuple[str, str, list[tuple[str, str]]] | None:
    """(method, path, headers) of a plain HTTP request to the gateway, or None. Only GET and POST below `root`."""
    try:
        lines = head.decode("latin-1").split("\r\n")
        method, path, version = lines[0].split(" ")
    except ValueError:
        return None
    # A bare CR, LF or NUL inside a line would be read as a line end by the AI's server: a run could smuggle a
    # header or a second request past the checks here, with the real token on the connection.
    if any(c in line for line in lines for c in "\r\n\x00"):
        return None
    if method not in ("GET", "POST") or not version.startswith("HTTP/1.") or not path.startswith(root) \
            or any(c in path for c in "\\#") or ".." in path.split("?")[0].split("/") or "://" in path:
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


def path_allowed(provider: str, path: str) -> bool:
    """May a run call this path of its AI (GATEWAY_PATHS, GATEWAY_NEVER)? A path matches itself and what is below it."""
    bare = path.split("?", 1)[0].rstrip("/")
    def under(prefixes) -> bool:
        return any(bare == p or bare.startswith(p + "/") for p in prefixes)
    allowed = GATEWAY_PATHS.get(provider)
    return (allowed is None or under(allowed)) and not under(GATEWAY_NEVER.get(provider, ()))


def rewrite(method: str, path: str, headers: list[tuple[str, str]], token: str, length: int,
            upstream: str) -> bytes:
    """The request as it goes to the AI: the real token instead of the ticket, one request per connection. No
    Authorization at all for an API without a key (tokens.NO_KEY)."""
    keep = [(n, v) for n, v in headers if n.lower() not in _DROP]
    auth = ([] if token == tokens.NO_KEY else [f"x-api-key: {token}"] if tokens.CLAUDE_API.fullmatch(token)
            else [f"Authorization: Bearer {token}"])
    out = [f"{method} {path} HTTP/1.1", f"Host: {upstream}", *auth,
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


async def _open_upstream(upstream):
    """A connection to the AI: `upstream` is a host name (TLS on 443) or a Target (the user's own AI)."""
    target = upstream if isinstance(upstream, Target) else Target(upstream, 443, True, "", False)
    addresses = await asyncio.wait_for(_resolve(target.host, target.port), CONNECT_TIMEOUT)
    context = ssl.create_default_context() if target.tls else None
    for address in addresses:   # connect to an address we checked, with the certificate checked for the name
        if not (is_public(address) or (target.lan and home_address(address))):
            continue
        try:
            return await asyncio.wait_for(asyncio.open_connection(
                address, target.port, ssl=context, server_hostname=target.host if context else None), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, OSError, ssl.SSLError):
            continue
    raise OSError("no upstream")


async def gateway(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, tickets_dir: str,
                  open_upstream=_open_upstream, log=print, provider: str = "claude") -> None:
    """One request of a run: check it, swap ticket for token, pass it to the AI of this gateway (`provider`), stream
    the answer back. `open_upstream(host)` opens the connection there (tests pass their own).

    Exactly one request per connection: the body is read by its length and nothing after it is passed on, so a
    second request on the same connection can never reach Anthropic with the ticket in it. The log names the path
    and the status, never a header."""
    upstream_w = None
    try:
        try:
            head = await asyncio.wait_for(client_r.readuntil(b"\r\n\r\n"), CONNECT_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            return
        request = parse_request(head, PATH_ROOT.get(provider, "/v1/")) if len(head) <= GATEWAY_HEAD_LIMIT else None
        if request is None:
            await _gateway_reply(client_w, "400 Bad Request", "bad request")
            return
        method, path, headers = request
        if not path_allowed(provider, path):
            log(f"gateway {provider}: refused {method} {path.split('?')[0]} (path)")
            await _gateway_reply(client_w, "404 Not Found", "not available through the hub")
            return
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
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if provider == "chatgpt" and not tokens.TICKET.fullmatch(bearer):   # the plan: the ticket inside its wrapper
            bearer = codex.ticket_of(bearer)
        if provider == "claude" and not bearer:            # Claude Code with an API key sends it as x-api-key
            bearer = values.get("x-api-key", "").strip()
        found = tokens.lookup_route(tickets_dir, bearer, provider=provider) if bearer else None
        token = found[0] if found else None
        upstream = GATEWAYS[provider][0]
        target = Target.of(found[1], found[2]) if found and provider == "custom" else None
        if provider == "custom" and found and target is None:
            token = None                                   # an address the gateway does not take: like no ticket
        if token is None:   # 403, not 401: an unknown ticket is the hub's matter, not a lost sign-in of the user.
            # Mistral Vibe reads a 403 as "invalid API key" (the runner would delete the user's key), so the Mistral
            # gateway says 502: a fault of the hub, the saved key stays (15.11.2026).
            log(f"gateway {provider}: refused {method} {path} (no valid ticket)")
            await _gateway_reply(client_w, "403 Forbidden" if provider == "claude" else "502 Bad Gateway",
                                 "no valid ticket")
            return
        if provider == "chatgpt":   # the plan goes to ChatGPT, the user's API key to the OpenAI API: never mixed
            keyed = bool(tokens.OPENAI_API.fullmatch(token))
            if keyed != path.startswith("/v1/"):
                await _gateway_reply(client_w, "404 Not Found", "not available through the hub")
                return
            if keyed:
                upstream = OPENAI_API[0]
        if target is not None:   # the path at the user's AI: its base and what follows /v1 in the request
            path = target.base + path[len("/v1"):]
            upstream = target.host if target.port in (80, 443) else f"{target.host}:{target.port}"
        body = await asyncio.wait_for(client_r.readexactly(length), GATEWAY_IDLE) if length else b""
        try:
            upstream_r, upstream_w = await open_upstream(target or upstream)
        except (asyncio.TimeoutError, OSError):
            await _gateway_reply(client_w, "502 Bad Gateway", f"{provider} not reachable")
            return
        if provider == "chatgpt" and tokens.OPENAI_API.fullmatch(token):   # the user's API key: the OpenAI API
            headers = [(n, v) for n, v in headers if n.lower() != "chatgpt-account-id"]
        elif provider == "chatgpt":   # the account comes from the ticket, never from the run
            headers = [(n, v) for n, v in headers if n.lower() != "chatgpt-account-id"] + [("ChatGPT-Account-Id", found[1])]
        upstream_w.write(rewrite(method, path, headers, token, length, upstream) + body)
        await upstream_w.drain()
        first = await asyncio.wait_for(upstream_r.read(65536), GATEWAY_IDLE)
        status = first.split(b"\r\n", 1)[0].decode("latin-1", "replace")[9:12]
        log(f"gateway {provider}: {method} {path.split('?')[0]} -> {status or '?'}")
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


async def serve_gateway(host: str, port: int, tickets_dir: str, log=print,
                        provider: str = "claude") -> asyncio.AbstractServer:
    slots = asyncio.Semaphore(MAX_CLIENTS)

    async def on_client(reader, writer):
        async with slots:
            await gateway(reader, writer, tickets_dir, log=log, provider=provider)

    return await asyncio.start_server(on_client, host, port, limit=GATEWAY_HEAD_LIMIT * 2)


async def main() -> None:
    bind = os.environ.get("EGRESS_BIND", "0.0.0.0")
    servers = [
        await serve(WEB, bind, int(os.environ.get("EGRESS_WEB_PORT", "3128"))),
        await serve(API, bind, int(os.environ.get("EGRESS_API_PORT", "3129"))),
        await serve_gateway(bind, int(os.environ.get("EGRESS_GATEWAY_PORT", "3130")),
                            os.environ.get("HUB_TICKETS_DIR", "/tickets")),
        await serve_gateway(bind, int(os.environ.get("EGRESS_MISTRAL_PORT", "3131")),
                            os.environ.get("HUB_TICKETS_DIR", "/tickets"), provider="mistral"),
        await serve_gateway(bind, int(os.environ.get("EGRESS_CUSTOM_PORT", "3132")),
                            os.environ.get("HUB_TICKETS_DIR", "/tickets"), provider="custom"),
        await serve_gateway(bind, int(os.environ.get("EGRESS_CHATGPT_PORT", "3133")),
                            os.environ.get("HUB_TICKETS_DIR", "/tickets"), provider="chatgpt"),
    ]
    print("egress: listening (web 3128, api 3129, gateways claude 3130, mistral 3131, own AI 3132, chatgpt 3133)",
          file=sys.stderr, flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
