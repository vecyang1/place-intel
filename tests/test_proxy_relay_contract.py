"""Contract: an authenticated residential proxy reaches Chrome as a
credential-free localhost address, and the credential is attached upstream.

Measured 2026-08-31, the reason this module exists: the call production made,
`Driver(uc=True, headless=True, proxy="user:pass@proxy.example.com:823")`,
loaded a blank page and raised nothing — SeleniumBase answers proxy auth with a
generated Chrome extension, and extensions do not load in that headless mode.
The failure was silent, so the log line announcing the residential fallback was
followed by a scrape of nothing.

The tests run a real upstream socket server rather than mocking one: the property
under test is what bytes leave the relay, and a mock of the socket is a mock of
the answer.
"""

from __future__ import annotations

import base64
import os
import socket
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox  # noqa: E402,F401

from placeintel import proxy_relay, reviews  # noqa: E402
from placeintel.cache import Place  # noqa: E402

UPSTREAM_REPLY = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"


class _FakeUpstream:
    """A one-shot proxy that records the request head it was sent."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.head = b""
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        with conn:
            buf = b""
            conn.settimeout(10)
            try:
                while b"\r\n\r\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                self.head = buf
                conn.sendall(UPSTREAM_REPLY)
            except OSError:
                pass
        self.ready.set()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class NeedsRelayTest(unittest.TestCase):
    def test_only_credentialled_proxies_need_a_relay(self):
        self.assertFalse(proxy_relay.needs_relay(None))
        self.assertFalse(proxy_relay.needs_relay(""))
        # No credential: Chrome can take this directly, a relay would be waste.
        self.assertFalse(proxy_relay.needs_relay("http://127.0.0.1:8080"))
        self.assertTrue(
            proxy_relay.needs_relay("http://user:pass@proxy.example.com:823")
        )
        # A username with no password still cannot be expressed as a Chrome flag.
        self.assertTrue(proxy_relay.needs_relay("http://useronly@host:823"))


class RelayForwardingTest(unittest.TestCase):
    def test_relay_attaches_credentials_upstream(self):
        upstream = _FakeUpstream()
        self.addCleanup(upstream.close)
        upstream_url = f"http://alice:s3cr3t@127.0.0.1:{upstream.port}"

        with proxy_relay.local_relay(upstream_url) as local_url:
            self.assertTrue(local_url.startswith("http://127.0.0.1:"))
            host, port = local_url.rsplit("/", 1)[-1].split(":")
            with socket.create_connection((host, int(port)), timeout=10) as c:
                c.sendall(
                    b"GET http://example.invalid/ HTTP/1.1\r\n"
                    b"Host: example.invalid\r\n\r\n"
                )
                reply = c.recv(4096)

        self.assertTrue(upstream.ready.wait(timeout=10), "upstream never got a request")
        expected = base64.b64encode(b"alice:s3cr3t").decode()
        self.assertIn(
            f"Proxy-Authorization: Basic {expected}".encode(),
            upstream.head,
            "relay forwarded the request WITHOUT the credential — Chrome would "
            "get a 407 and render a blank page, exactly as production did",
        )
        # The original request line must survive intact.
        self.assertTrue(upstream.head.startswith(b"GET http://example.invalid/ HTTP/1.1"))
        self.assertIn(b"200 OK", reply)

    def test_relay_binds_only_to_loopback(self):
        """An unauthenticated open proxy must not be reachable off-box."""
        upstream = _FakeUpstream()
        self.addCleanup(upstream.close)
        with proxy_relay.local_relay(f"http://u:p@127.0.0.1:{upstream.port}") as url:
            self.assertIn("127.0.0.1", url)
            self.assertNotIn("0.0.0.0", url)

    def test_port_is_released_after_the_block(self):
        upstream = _FakeUpstream()
        self.addCleanup(upstream.close)
        with proxy_relay.local_relay(f"http://u:p@127.0.0.1:{upstream.port}") as url:
            port = int(url.rsplit(":", 1)[1])
        with socket.socket() as s:
            s.settimeout(2)
            with self.assertRaises(OSError, msg="relay port still accepting after exit"):
                s.connect(("127.0.0.1", port))
                s.sendall(b"GET / HTTP/1.1\r\n\r\n")
                if not s.recv(16):
                    raise OSError("closed")

    def test_missing_host_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            with proxy_relay.local_relay("not-a-url"):
                self.fail("accepted a proxy url with no host")


class ScraperUsesRelayTest(unittest.TestCase):
    """The wiring, not just the relay: an authenticated proxy must never reach
    the browser as a credential string."""

    @staticmethod
    def _place() -> Place:
        return Place(
            place_id="ChIJrelay",
            name="Relay Test",
            maps_url="https://www.google.com/maps/place/Relay+Test/?q=place_id:ChIJrelay",
            review_count=10,
        )

    def test_credentialled_proxy_is_replaced_by_a_loopback_url(self):
        seen: list[str | None] = []

        def capture(place, max_reviews, target_url=None, proxy_url=None):
            seen.append(proxy_url)

        with mock.patch.object(reviews, "_run_scraper_pro_unproxied", capture):
            reviews._run_scraper_pro(
                self._place(), 10,
                proxy_url="http://user:pass@proxy.example.com:823",
            )

        self.assertEqual(len(seen), 1)
        forwarded = seen[0]
        self.assertIsNotNone(forwarded)
        self.assertTrue(
            forwarded.startswith("http://127.0.0.1:"),
            f"scraper was handed {forwarded!r} instead of a loopback relay",
        )
        self.assertNotIn("user", forwarded)
        self.assertNotIn("pass", forwarded)

    def test_uncredentialled_proxy_is_passed_straight_through(self):
        """No relay when none is needed — an extra hop is latency, not safety."""
        seen: list[str | None] = []

        def capture(place, max_reviews, target_url=None, proxy_url=None):
            seen.append(proxy_url)

        with mock.patch.object(reviews, "_run_scraper_pro_unproxied", capture):
            reviews._run_scraper_pro(self._place(), 10, proxy_url="http://10.0.0.5:8080")
            reviews._run_scraper_pro(self._place(), 10, proxy_url=None)

        self.assertEqual(seen, ["http://10.0.0.5:8080", None])


if __name__ == "__main__":
    unittest.main()
