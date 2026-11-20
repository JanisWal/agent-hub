"""Checks the user's own AI before the runner keeps its key (runner.handle_keys, Janis 20.11.2026). Standard library only.

The user gives the address of any API in the OpenAI chat format and, if it needs one, a key. This module asks
`GET <address>/models` once. The address must lead where the gateway would send the runs later (egress.Target): a
public address, or for the owner's own AI one in the home network (`lan`); never the server's Docker networks. The
address is resolved here and the checked address is the one connected to.
"""
import http.client
import json
import socket
import ssl

from . import egress, tokens


def verify(api_key: str, endpoint: str, lan: bool = False, resolve=socket.getaddrinfo) -> str:
    """"ok", "refused" (401/403), "address" (not allowed or not a valid address) or "error" (not reachable)."""
    target = egress.Target.of(endpoint, lan) if tokens.ENDPOINT.fullmatch(endpoint or "") else None
    if target is None:
        return "address"
    try:
        addresses = [info[4][0] for info in resolve(target.host, target.port, type=socket.SOCK_STREAM)]
    except OSError:
        return "error"
    allowed = [a for a in addresses if egress.is_public(a) or (lan and egress.home_address(a))]
    if not allowed or len(allowed) != len(addresses):
        return "address"
    host = target.host if target.port in (80, 443) else f"{target.host}:{target.port}"
    auth = "" if api_key == tokens.NO_KEY else f"Authorization: Bearer {api_key}\r\n"
    request = (f"GET {target.base}/models HTTP/1.1\r\nHost: {host}\r\nAccept: application/json\r\n{auth}"
               "Connection: close\r\n\r\n").encode()
    sock = None
    try:   # to the checked address, the certificate checked for the name
        sock = socket.create_connection((allowed[0], target.port), timeout=20)
        if target.tls:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=target.host)
        sock.sendall(request)
        answer = http.client.HTTPResponse(sock)
        answer.begin()
        body = answer.read(200_000)
    except (OSError, ssl.SSLError, http.client.HTTPException):
        return "error"
    finally:
        if sock is not None:
            sock.close()
    if answer.status in (401, 403):
        return "refused"
    if answer.status != 200:
        return "error"
    try:
        json.loads(body)
    except ValueError:
        return "error"
    return "ok"
