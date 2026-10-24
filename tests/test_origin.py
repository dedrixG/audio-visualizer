"""Origin checks for /ws/pcm.

Browsers do not apply CORS to WebSockets. A handshake is accepted only for
the page this server is serving.
"""

from __future__ import annotations

import socket
import threading
import time
import unittest
from unittest import mock

import server

WS_ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
WS_KEY = "dGhlIHNhbXBsZSBub25jZQ=="


class OriginPolicyTests(unittest.TestCase):
    def test_allows_loopback_page(self) -> None:
        allowed = (
            "http://127.0.0.1:8765",
            "http://localhost:8765",
            "http://LOCALHOST:8765",
            "http://[::1]:8765",
            "HTTP://127.0.0.1:8765",
        )
        for origin in allowed:
            with self.subTest(origin=origin):
                self.assertTrue(server.origin_allowed(origin, "127.0.0.1:8765", 8765))

    def test_rejects_cross_origin_and_malformed(self) -> None:
        rejected = (
            None,
            "",
            "null",
            "https://example.com",
            "http://example.com:8765",
            "https://127.0.0.1:8765",
            "http://127.0.0.1",
            "http://127.0.0.1:80",
            "http://127.0.0.1:8766",
            "http://127.0.0.1:8765/",
            "http://user@127.0.0.1:8765",
            "http://192.168.1.5:8765",
        )
        for origin in rejected:
            with self.subTest(origin=origin):
                self.assertFalse(server.origin_allowed(origin, "127.0.0.1:8765", 8765))

    def test_allows_the_ip_the_request_came_in_on(self) -> None:
        self.assertTrue(
            server.origin_allowed("http://192.168.1.20:8765", "192.168.1.20:8765", 8765)
        )
        self.assertTrue(
            server.origin_allowed("http://100.64.0.8:8765", "100.64.0.8:8765", 8765)
        )

    def test_rejects_lan_origin_aimed_at_the_loopback_page(self) -> None:
        self.assertFalse(
            server.origin_allowed("http://192.168.1.20:8765", "127.0.0.1:8765", 8765)
        )

    def test_rejects_dns_name_even_when_host_matches(self) -> None:
        self.assertFalse(
            server.origin_allowed("http://pc.local:8765", "pc.local:8765", 8765)
        )
        self.assertFalse(
            server.origin_allowed("https://example.com", "example.com", 8765)
        )

    def test_default_bind_is_loopback(self) -> None:
        self.assertEqual(server.DEFAULT_BIND, "127.0.0.1")
        self.assertFalse(server.listens_on_network(server.DEFAULT_BIND))
        self.assertFalse(server.listens_on_network("localhost"))
        self.assertFalse(server.listens_on_network("[::1]"))
        self.assertTrue(server.listens_on_network("0.0.0.0"))
        self.assertTrue(server.listens_on_network("192.168.1.20"))


def _read_http(sock: socket.socket) -> bytes:
    sock.settimeout(2)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            break
    head, sep, rest = data.partition(b"\r\n\r\n")
    if not sep:
        return data
    length = 0
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(rest) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        rest += chunk
    return head + sep + rest[:length]


def _status_code(raw: bytes) -> int:
    line = raw.split(b"\r\n", 1)[0].decode("iso-8859-1")
    return int(line.split()[1])


def _wait_idle() -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with server.HUB.lock:
            if not server.HUB.clients:
                return
        time.sleep(0.01)
    with server.HUB.lock:
        stuck = list(server.HUB.clients)
    for client in stuck:
        try:
            client.sock.close()
        except OSError:
            pass
        server.HUB.remove(client)


class HandshakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._capture = mock.patch.object(server.HUB, "_start_capture")
        cls._capture.start()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.VizHandler)
        cls.httpd.daemon_threads = True
        cls.port = int(cls.httpd.server_address[1])
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        _wait_idle()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._capture.stop()

    def setUp(self) -> None:
        _wait_idle()
        with server.HUB.lock:
            self.assertEqual(server.HUB.clients, [])

    def _handshake(self, origin: str | None, host: str | None = None) -> bytes:
        host = host or f"127.0.0.1:{self.port}"
        headers = [
            "GET /ws/pcm HTTP/1.1",
            f"Host: {host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {WS_KEY}",
            "Sec-WebSocket-Version: 13",
        ]
        if origin is not None:
            headers.append(f"Origin: {origin}")
        payload = ("\r\n".join(headers) + "\r\n\r\n").encode()
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        try:
            sock.sendall(payload)
            raw = _read_http(sock)
            if _status_code(raw) == 101:
                sock.sendall(bytes([0x88, 0x80, 0, 0, 0, 0]))
                sock.settimeout(1)
                try:
                    while sock.recv(4096):
                        pass
                except OSError:
                    pass
            return raw
        finally:
            sock.close()
            _wait_idle()

    def test_cross_origin_is_forbidden(self) -> None:
        raw = self._handshake("https://example.com")
        self.assertEqual(_status_code(raw), 403)
        self.assertNotIn(b"sec-websocket-accept", raw.lower())
        with server.HUB.lock:
            self.assertEqual(server.HUB.clients, [])

    def test_missing_origin_is_forbidden(self) -> None:
        raw = self._handshake(None)
        self.assertEqual(_status_code(raw), 403)

    def test_same_origin_loopback_switches_protocols(self) -> None:
        raw = self._handshake(f"http://127.0.0.1:{self.port}")
        self.assertEqual(_status_code(raw), 101)
        self.assertIn(WS_ACCEPT.encode(), raw)

    def test_localhost_origin_switches_protocols(self) -> None:
        raw = self._handshake(
            f"http://localhost:{self.port}",
            host=f"localhost:{self.port}",
        )
        self.assertEqual(_status_code(raw), 101)
        self.assertIn(WS_ACCEPT.encode(), raw)

    def test_phone_origin_switches_when_it_matches_host(self) -> None:
        host = f"192.168.1.20:{self.port}"
        raw = self._handshake(f"http://{host}", host=host)
        self.assertEqual(_status_code(raw), 101)

    def test_phone_origin_is_forbidden_for_the_loopback_host(self) -> None:
        raw = self._handshake(f"http://192.168.1.20:{self.port}")
        self.assertEqual(_status_code(raw), 403)

    def test_dns_name_is_forbidden_even_when_host_matches(self) -> None:
        raw = self._handshake(
            f"http://evil.example:{self.port}",
            host=f"evil.example:{self.port}",
        )
        self.assertEqual(_status_code(raw), 403)

    def test_status_is_same_origin_only(self) -> None:
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        try:
            request = (
                "GET /api/status HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            sock.sendall(request.encode())
            raw = b""
            sock.settimeout(2)
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
        finally:
            sock.close()
        head, _, body = raw.partition(b"\r\n\r\n")
        self.assertEqual(_status_code(raw), 200)
        self.assertNotIn(b"access-control-allow-origin", head.lower())
        self.assertIn(b'"local"', body)
        self.assertIn(b'"lan": []', body)


if __name__ == "__main__":
    unittest.main()
