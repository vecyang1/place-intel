"""A localhost proxy that hands Chrome an authenticated upstream it can use.

Chrome takes `--proxy-server=host:port` and has no flag for proxy credentials.
SeleniumBase papers over that by generating a Chrome extension that answers the
auth challenge — and extensions do not load in the headless mode this project
runs. Measured 2026-08-31 with the exact call `_run_scraper_pro` makes today,
`Driver(uc=True, headless=True, proxy="user:pass@proxy.example.com:823")`:  # nosec: mock

    egress = ""      # blank page, no title, no tabs, and NO exception

That silence is the expensive part. The residential fallback logs
"已自动切换至住宅 IP 代理池" and then scrapes nothing, which reads downstream as
"the proxy did not help" rather than "the proxy was never used".

This relay removes the credential from the browser's problem entirely: Chrome
connects to 127.0.0.1 with no auth, and the relay adds `Proxy-Authorization` on
the way upstream. Same call through the relay, same minute:

    egress = {"ip": "113.182.209.222"}    # Vietnamese residential

It binds to 127.0.0.1 only, so the open (unauthenticated) port is not reachable
off the machine, and the credential never appears in a Chrome command line,
a process listing, or a `--user-data-dir`.
"""

from __future__ import annotations

import base64
import logging
import socket
import socketserver
import threading
import urllib.parse
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

# A CONNECT tunnel to Google Maps stays open for the life of a page load.
_SOCKET_TIMEOUT_S = 120
_CHUNK = 65536
_MAX_HEAD_BYTES = 64 * 1024


class _RelayHandler(socketserver.BaseRequestHandler):
    """Forward one client connection upstream with credentials attached."""

    # Set on the server instance by ProxyRelay.
    upstream_host: str
    upstream_port: int
    auth_header: bytes

    def handle(self) -> None:  # noqa: D102 - socketserver contract
        client = self.request
        client.settimeout(_SOCKET_TIMEOUT_S)
        try:
            head = self._read_head(client)
        except OSError:
            return
        if not head:
            return
        try:
            upstream = socket.create_connection(
                (self.server.upstream_host, self.server.upstream_port),
                timeout=_SOCKET_TIMEOUT_S,
            )
        except OSError as exc:
            logger.debug("proxy relay could not reach upstream: %s", exc)
            return
        try:
            request_line, _, rest = head.partition(b"\r\n")
            upstream.sendall(
                request_line + b"\r\n" + self.server.auth_header + rest
            )
            self._pump(client, upstream)
        finally:
            upstream.close()

    @staticmethod
    def _read_head(sock: socket.socket) -> bytes:
        """Read up to and including the blank line that ends the request head."""
        buf = b""
        while b"\r\n\r\n" not in buf:
            if len(buf) > _MAX_HEAD_BYTES:
                return b""
            chunk = sock.recv(_CHUNK)
            if not chunk:
                return b""
            buf += chunk
        return buf

    @staticmethod
    def _pump(a: socket.socket, b: socket.socket) -> None:
        """Copy bytes both ways until either side closes."""

        def copy(src: socket.socket, dst: socket.socket) -> None:
            try:
                while True:
                    data = src.recv(_CHUNK)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t = threading.Thread(target=copy, args=(a, b), daemon=True)
        t.start()
        copy(b, a)
        t.join(timeout=_SOCKET_TIMEOUT_S)


class _RelayServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def needs_relay(proxy_url: str | None) -> bool:
    """True when *proxy_url* carries credentials Chrome cannot supply itself."""
    if not proxy_url:
        return False
    parsed = urllib.parse.urlparse(proxy_url)
    return bool(parsed.username or parsed.password)


@contextmanager
def local_relay(proxy_url: str) -> Iterator[str]:
    """Serve an unauthenticated localhost proxy for *proxy_url*.

    Yields a ``http://127.0.0.1:<port>`` URL usable as a Chrome
    ``--proxy-server`` value. The relay stops when the block exits.
    """
    parsed = urllib.parse.urlparse(proxy_url)
    if not parsed.hostname:
        raise ValueError(f"proxy url has no host: {proxy_url!r}")
    credential = f"{parsed.username or ''}:{parsed.password or ''}".encode()
    server = _RelayServer(("127.0.0.1", 0), _RelayHandler)
    server.upstream_host = parsed.hostname
    server.upstream_port = parsed.port or 8080
    server.auth_header = (
        b"Proxy-Authorization: Basic " + base64.b64encode(credential) + b"\r\n"
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(
        "proxy relay on 127.0.0.1:%d -> %s:%d (credential kept out of Chrome)",
        port, server.upstream_host, server.upstream_port,
    )
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
