"""The egress proxy: who may leave the agent network, and where to.

    docker compose run --rm --no-deps -v "$PWD/runner:/app/runner" web python -W ignore -m unittest runner.test_egress
"""
import asyncio
import unittest

from runner import egress as E

QUIET = lambda text: None


class PolicyTest(unittest.TestCase):
    def test_only_public_addresses(self):
        public = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"]
        private = ["10.0.0.1", "192.168.1.20", "172.17.0.1", "172.31.255.254", "127.0.0.1", "127.1.2.3", "169.254.169.254",
                   "100.64.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255", "::1", "fe80::1", "fc00::1", "::ffff:192.168.1.1",
                   "::ffff:127.0.0.1", "not an ip", ""]
        for address in public:
            self.assertTrue(E.is_public(address), address)
        for address in private:
            self.assertFalse(E.is_public(address), address)

    def test_hosts_of_the_api_policy(self):
        for host in ("api.anthropic.com", "claude.ai", "console.anthropic.com", "statsig.anthropic.com", "anthropic.com"):
            self.assertTrue(E.API.host_allowed(host), host)
        for host in ("evil.com", "anthropic.com.evil.com", "notanthropic.com", "claude.ai.evil.org", "example.com", "localhost"):
            self.assertFalse(E.API.host_allowed(host), host)
        self.assertTrue(E.WEB.host_allowed("anything.example"))

    def test_only_https_by_default(self):
        self.assertEqual(E.WEB.ports, (443,))
        self.assertEqual(E.API.ports, (443,))

    def test_parse_connect(self):
        self.assertEqual(E.parse_connect(b"CONNECT Example.COM.:443 HTTP/1.1\r\nHost: x\r\n\r\n"), ("example.com", 443))
        self.assertEqual(E.parse_connect(b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n"), ("::1", 443))
        for bad in (b"GET http://example.com/ HTTP/1.1\r\n\r\n", b"CONNECT example.com HTTP/1.1\r\n\r\n",
                    b"CONNECT :443 HTTP/1.1\r\n\r\n", b"CONNECT example.com:99999 HTTP/1.1\r\n\r\n",
                    b"CONNECT example.com:443\r\n\r\n", b"CONNECT a b c d\r\n\r\n", b"\xff\xfe\r\n\r\n", b""):
            self.assertIsNone(E.parse_connect(bad), bad)


class ProxyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen: list[bytes] = []

        async def echo(reader, writer):
            data = await reader.read(100)
            self.seen.append(data)
            writer.write(b"echo:" + data)
            await writer.drain()
            writer.close()

        self.upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        self.upstream_port = self.upstream.sockets[0].getsockname()[1]
        self.servers = [self.upstream]

    async def asyncTearDown(self):
        for server in self.servers:
            server.close()
            await server.wait_closed()

    async def proxy(self, policy):
        server = await E.serve(policy, "127.0.0.1", 0, log=QUIET)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def ask(self, port, request: bytes, then: bytes = b""):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        rest = b""
        if head.startswith(b"HTTP/1.1 200") and then:
            writer.write(then)
            await writer.drain()
            rest = await asyncio.wait_for(reader.read(100), 5)
        writer.close()
        return head.split(b"\r\n")[0].decode(), rest

    async def test_tunnel_works_when_the_policy_allows_it(self):
        port = await self.proxy(E.Policy(ports=(self.upstream_port,), allow_private=True))
        status, rest = await self.ask(port, f"CONNECT 127.0.0.1:{self.upstream_port} HTTP/1.1\r\n\r\n".encode(), b"hello")
        self.assertEqual(status, "HTTP/1.1 200 Connection Established")
        self.assertEqual(rest, b"echo:hello")

    async def test_private_and_loopback_addresses_are_refused(self):
        port = await self.proxy(E.Policy(ports=(self.upstream_port,)))          # the real web policy but this port
        for target in (f"127.0.0.1:{self.upstream_port}", f"localhost:{self.upstream_port}",
                       f"192.168.0.1:{self.upstream_port}", f"169.254.169.254:{self.upstream_port}",
                       f"10.1.2.3:{self.upstream_port}"):
            status, _ = await self.ask(port, f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
            self.assertEqual(status, "HTTP/1.1 403 Forbidden", target)
        self.assertEqual(self.seen, [])                                          # the upstream never saw a connection

    async def test_other_ports_are_refused(self):
        port = await self.proxy(E.WEB)
        status, _ = await self.ask(port, f"CONNECT 127.0.0.1:{self.upstream_port} HTTP/1.1\r\n\r\n".encode())
        self.assertEqual(status, "HTTP/1.1 403 Forbidden")
        status, _ = await self.ask(port, b"CONNECT example.com:22 HTTP/1.1\r\n\r\n")
        self.assertEqual(status, "HTTP/1.1 403 Forbidden")

    async def test_api_policy_refuses_every_other_host(self):
        port = await self.proxy(E.Policy(hosts=E.API_HOSTS, ports=(self.upstream_port,), allow_private=True))
        for target in (f"evil.example:{self.upstream_port}", f"127.0.0.1:{self.upstream_port}",
                       f"anthropic.com.evil.example:{self.upstream_port}"):
            status, _ = await self.ask(port, f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
            self.assertEqual(status, "HTTP/1.1 403 Forbidden", target)

    async def test_plain_http_and_garbage_are_not_carried(self):
        port = await self.proxy(E.WEB)
        status, _ = await self.ask(port, b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
        self.assertEqual(status, "HTTP/1.1 405 Method Not Allowed")
        status, _ = await self.ask(port, b"hello\r\n\r\n")
        self.assertEqual(status, "HTTP/1.1 405 Method Not Allowed")

    async def test_unresolvable_names_fail_cleanly(self):
        port = await self.proxy(E.WEB)
        status, _ = await self.ask(port, b"CONNECT no-such-host.invalid:443 HTTP/1.1\r\n\r\n")
        self.assertIn(status, ("HTTP/1.1 502 Bad Gateway", "HTTP/1.1 403 Forbidden"))



class GatewayTest(unittest.IsolatedAsyncioTestCase):
    """The gateway: a run's request goes to Anthropic with the user's token instead of the ticket (14.11.2026)."""
    TOKEN = "sk-ant-oat01-" + "r" * 90

    async def asyncSetUp(self):
        import tempfile
        from runner import tokens
        self.tmp = tempfile.TemporaryDirectory()
        self.ticket = tokens.Tickets(self.tmp.name).issue(self.TOKEN)
        self.received = []

        async def upstream(reader, writer):
            data = b""
            try:
                while True:
                    chunk = await asyncio.wait_for(reader.read(65536), 0.5)
                    if not chunk:
                        break
                    data += chunk
            except asyncio.TimeoutError:
                pass
            self.received.append(data)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\nevent: ping\n\ndata: hi\n\n")
            await writer.drain()
            writer.close()

        self.upstream = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = self.upstream.sockets[0].getsockname()[1]
        open_upstream = lambda host: asyncio.open_connection("127.0.0.1", port)
        self.logs = []
        self.server = await asyncio.start_server(
            lambda r, w: E.gateway(r, w, self.tmp.name, open_upstream=open_upstream, log=self.logs.append), "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        self.upstream.close()
        self.tmp.cleanup()

    async def send(self, raw: bytes) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(raw)
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        return answer

    def request(self, body=b'{"model":"claude-haiku-5-5"}', ticket=None, path="/v1/messages?beta=true", extra=""):
        return (f"POST {path} HTTP/1.1\r\nHost: egress:3130\r\nAuthorization: Bearer {ticket or self.ticket}\r\n"
                f"anthropic-beta: oauth-2025-04-20\r\nContent-Type: application/json\r\n{extra}"
                f"Content-Length: {len(body)}\r\n\r\n").encode() + body

    async def test_the_ticket_is_swapped_for_the_token(self):
        answer = await self.send(self.request())
        self.assertTrue(answer.startswith(b"HTTP/1.1 200 OK"))
        self.assertIn(b"data: hi", answer)                                    # the stream comes back as it is
        sent = self.received[0]
        head, _, body = sent.partition(b"\r\n\r\n")
        self.assertIn(f"Authorization: Bearer {self.TOKEN}".encode(), head)
        self.assertNotIn(self.ticket.encode(), sent)                          # the ticket never leaves the Pi
        self.assertIn(b"Host: api.anthropic.com", head)
        self.assertIn(b"Connection: close", head)
        self.assertIn(b"anthropic-beta: oauth-2025-04-20", head)               # Claude Code's own headers stay
        self.assertEqual(body, b'{"model":"claude-haiku-5-5"}')
        self.assertTrue(any("-> 200" in line for line in self.logs))
        self.assertFalse(any(self.TOKEN in line or self.ticket in line for line in self.logs))

    async def test_a_second_request_on_the_connection_is_not_passed_on(self):
        await self.send(self.request() + self.request(body=b"second", ticket="hubrun-" + "Q" * 43))
        self.assertNotIn(b"second", self.received[0])
        self.assertEqual(self.received[0].count(b"POST "), 1)

    async def test_without_a_valid_ticket_nothing_reaches_anthropic(self):
        for ticket in ("hubrun-" + "Z" * 43, self.TOKEN, "x"):
            answer = await self.send(self.request(ticket=ticket))
            self.assertTrue(answer.startswith(b"HTTP/1.1 403"), ticket)
        answer = await self.send(b"POST /v1/messages HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}")
        self.assertTrue(answer.startswith(b"HTTP/1.1 403"))
        self.assertEqual(self.received, [])

    async def test_the_mistral_gateway_takes_only_mistral_tickets_and_never_says_invalid_key(self):
        server = await asyncio.start_server(
            lambda r, w: E.gateway(r, w, self.tmp.name, open_upstream=lambda host: None, log=self.logs.append,
                                   provider="mistral"), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(self.request())                                       # a valid ticket, but Claude's
            await writer.drain()
            answer = await asyncio.wait_for(reader.read(), 5)
            writer.close()
        finally:
            server.close()
        self.assertTrue(answer.startswith(b"HTTP/1.1 502"))                    # not 401/403: the key is kept
        self.assertEqual(self.received, [])

    async def test_only_the_api_paths_and_plain_lengths(self):
        for path in ("/admin", "http://evil.example/v1/messages", "/v1/../etc", "/v2/messages"):
            answer = await self.send(self.request(path=path))
            self.assertTrue(answer.startswith(b"HTTP/1.1 400"), path)
        for extra in ("X-A: 1\nAuthorization: Bearer x\r\n", "X-A: 1\rHost: evil.example\r\n", "X-A: \x00\r\n"):
            answer = await self.send(self.request(extra=extra))                # no bare line break or NUL in a header
            self.assertTrue(answer.startswith(b"HTTP/1.1 400"), repr(extra))
        answer = await self.send(self.request(path="/v1/messages/.."))
        self.assertTrue(answer.startswith(b"HTTP/1.1 400"))
        answer = await self.send(self.request(extra="Transfer-Encoding: chunked\r\n"))
        self.assertTrue(answer.startswith(b"HTTP/1.1 411"))
        answer = await self.send(b"CONNECT api.anthropic.com:443 HTTP/1.1\r\n\r\n")
        self.assertTrue(answer.startswith(b"HTTP/1.1 400"))
        self.assertEqual(self.received, [])

    async def test_a_run_reaches_only_the_model_calls(self):
        for path in ("/v1/files", "/v1/organizations/x", "/v1/messages_x", "/v1/messages/batches/../x"):
            answer = await self.send(self.request(path=path))
            self.assertTrue(answer.startswith((b"HTTP/1.1 404", b"HTTP/1.1 400")), path)
        self.assertEqual(self.received, [])

    def test_paths_per_ai(self):
        self.assertTrue(E.path_allowed("claude", "/v1/messages?beta=true"))
        self.assertTrue(E.path_allowed("claude", "/v1/messages/count_tokens"))
        self.assertFalse(E.path_allowed("claude", "/v1/files"))
        self.assertTrue(E.path_allowed("mistral", "/v1/chat/completions"))
        self.assertTrue(E.path_allowed("mistral", "/v1/conversations"))
        self.assertFalse(E.path_allowed("mistral", "/v1/files/abc"))
        self.assertFalse(E.path_allowed("mistral", "/v1/batch/jobs"))


class OwnAiGatewayTest(unittest.IsolatedAsyncioTestCase):
    """The gateway of the user's own AI (20.11.2026): the address comes from the ticket, never from the request."""

    async def asyncSetUp(self):
        import tempfile
        from runner import tokens
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = tokens.Tickets(self.tmp.name)
        self.received, self.targets = [], []

        async def upstream(reader, writer):
            data = await asyncio.wait_for(reader.read(65536), 2)
            self.received.append(data)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}")
            await writer.drain()
            writer.close()

        self.upstream = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = self.upstream.sockets[0].getsockname()[1]

        def open_upstream(target):
            self.targets.append(target)
            return asyncio.open_connection("127.0.0.1", port)
        self.server = await asyncio.start_server(
            lambda r, w: E.gateway(r, w, self.tmp.name, open_upstream=open_upstream, log=lambda line: None,
                                   provider="custom"), "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        self.upstream.close()
        self.tmp.cleanup()

    async def send(self, ticket, path="/v1/chat/completions"):
        body = b'{"model":"llama3.1:8b"}'
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write((f"POST {path} HTTP/1.1\r\nHost: egress:3132\r\nAuthorization: Bearer {ticket}\r\n"
                      f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        return answer

    async def test_the_address_and_key_of_the_ticket(self):
        ticket = self.tickets.issue("sk-own-key-123", "custom", upstream="https://api.example.com/openai/v1")
        answer = await self.send(ticket)
        self.assertTrue(answer.startswith(b"HTTP/1.1 200"))
        head = self.received[0].split(b"\r\n\r\n")[0]
        self.assertIn(b"POST /openai/v1/chat/completions HTTP/1.1", head)
        self.assertIn(b"Host: api.example.com", head)
        self.assertIn(b"Authorization: Bearer sk-own-key-123", head)
        target = self.targets[0]
        self.assertEqual((target.host, target.port, target.tls, target.lan), ("api.example.com", 443, True, False))

    async def test_a_local_ai_without_a_key(self):
        ticket = self.tickets.issue("-", "custom", upstream="http://192.168.178.50:11434/v1", lan=True)
        await self.send(ticket)
        head = self.received[0].split(b"\r\n\r\n")[0]
        self.assertNotIn(b"Authorization", head)                              # an API without a key
        self.assertIn(b"Host: 192.168.178.50:11434", head)
        self.assertEqual((self.targets[0].tls, self.targets[0].lan), (False, True))

    async def test_refused_cases_never_look_like_a_bad_key(self):
        plain = self.tickets.issue("k", "custom", upstream="http://ai.example.com/v1")   # http without lan: no
        mistral = self.tickets.issue("A" * 32, "mistral")
        for ticket, path in ((plain, "/v1/chat/completions"), (mistral, "/v1/chat/completions"),
                             ("hubrun-" + "Z" * 43, "/v1/chat/completions")):
            answer = await self.send(ticket, path)
            self.assertTrue(answer.startswith(b"HTTP/1.1 502"), ticket)
        good = self.tickets.issue("k", "custom", upstream="https://api.example.com/v1")
        self.assertTrue((await self.send(good, "/v1/files")).startswith(b"HTTP/1.1 404"))   # only the model calls
        self.assertEqual(self.received, [])

    def test_home_addresses_only_for_the_owner_and_never_dockers(self):
        self.assertTrue(E.home_address("192.168.178.50"))
        self.assertTrue(E.home_address("100.101.1.2"))                         # Tailscale
        for address in ("172.20.0.5", "127.0.0.1", "169.254.1.1", "8.8.8.8", "::1"):
            self.assertFalse(E.home_address(address), address)
        self.assertIsNone(E.Target.of("http://x.example/v1", False))
        self.assertIsNone(E.Target.of("ftp://x.example/v1", True))
        self.assertEqual(E.Target.of("http://pc:8080/v1/", True).base, "/v1")


class ChatGptGatewayTest(OwnAiGatewayTest):
    """The gateway of ChatGPT (21.11.2026): the ticket inside the wrapper, the account from the ticket."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.server.close()
        self.server = await asyncio.start_server(
            lambda r, w: E.gateway(r, w, self.tmp.name, open_upstream=self._open, log=lambda line: None,
                                   provider="chatgpt"), "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    def _open(self, target):
        self.targets.append(target)
        return asyncio.open_connection("127.0.0.1", self.upstream.sockets[0].getsockname()[1])

    async def ask(self, bearer, path="/backend-api/codex/responses", account="planted"):
        body = b'{"model":"gpt-6-luna"}'
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write((f"POST {path} HTTP/1.1\r\nHost: egress:3133\r\nAuthorization: Bearer {bearer}\r\n"
                      f"ChatGPT-Account-Id: {account}\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        return answer

    async def test_the_real_token_and_account_go_to_chatgpt(self):
        from runner import codex
        real = "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjF9.signaturexyz"
        ticket = self.tickets.issue(real, "chatgpt", upstream="acct-777")
        answer = await self.ask(codex.ticket_jwt(ticket, {"account": "acct-777"}))
        self.assertTrue(answer.startswith(b"HTTP/1.1 200"))
        head = self.received[0].split(b"\r\n\r\n")[0]
        self.assertIn(f"Authorization: Bearer {real}".encode(), head)
        self.assertIn(b"ChatGPT-Account-Id: acct-777", head)
        self.assertNotIn(b"planted", head)                                     # never the run's own account header
        self.assertIn(b"Host: chatgpt.com", head)
        self.assertEqual(self.targets, ["chatgpt.com"])

    async def test_other_addresses_and_bare_tickets_are_refused(self):
        from runner import codex
        ticket = self.tickets.issue("eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjF9.signaturexyz", "chatgpt", upstream="acct-777")
        wrapped = codex.ticket_jwt(ticket, {"account": "acct-777"})
        self.assertTrue((await self.ask(wrapped, "/backend-api/wham/accounts/check")).startswith(b"HTTP/1.1 404"))
        self.assertTrue((await self.ask(ticket)).startswith(b"HTTP/1.1 502"))   # not wrapped
        self.assertTrue((await self.ask(wrapped, "/v1/chat/completions")).startswith(b"HTTP/1.1 400"))
        self.assertEqual(self.received, [])

    # the own-AI cases of the parent class do not apply here
    test_the_address_and_key_of_the_ticket = test_a_local_ai_without_a_key = None
    test_refused_cases_never_look_like_a_bad_key = test_home_addresses_only_for_the_owner_and_never_dockers = None


if __name__ == "__main__":
    unittest.main()
