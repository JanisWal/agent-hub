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


if __name__ == "__main__":
    unittest.main()
