"""Real finite loopback responses exercise HTTP duration and allocation limits."""

import gzip
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from autonomy_lab.bounded_http import ResponseTooLarge, request, request_deadline
from autonomy_lab.verifier import _http_observation


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                if self.path == "/headers":
                    for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.02)
                    return
                body = b'"' + b"a" * (100_000 if self.path == "/large" else 80) + b'"'
                self.send_response(200)
                if self.path == "/gzip":
                    body = gzip.compress(body)
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.path == "/drip":
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.02)
                else:
                    self.wfile.write(body)
            except OSError:
                pass  # The bounded reader deliberately closes early.

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("path", ["/headers", "/drip"])
def test_total_deadline_interrupts_continuous_progress(server, path):
    started = time.monotonic()
    with httpx.Client(trust_env=False) as client, pytest.raises(httpx.TimeoutException):
        request(client, "GET", server + path, timeout=0.2, max_bytes=1024)
    assert time.monotonic() - started < 1.5
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_body_size_is_rejected_before_parsing(server):
    with httpx.Client(trust_env=False) as client, pytest.raises(ResponseTooLarge):
        request(client, "GET", server + "/large", timeout=1, max_bytes=1024)


def test_compressed_response_is_rejected_before_decompression(server):
    with httpx.Client(trust_env=False) as client, pytest.raises(httpx.HTTPError, match="Compressed"):
        request(client, "GET", server + "/gzip", timeout=1, max_bytes=1024)


@pytest.mark.parametrize("path, error", [("/large", "ResponseTooLarge"), ("/drip", "TimeoutException")])
def test_verifier_retains_bounded_failure_as_observation(server, path, error):
    with httpx.Client(timeout=0.2, trust_env=False) as client:
        result = _http_observation(client, server + path)
    assert result["kind"] == "error" and result["error"] == error
    assert "body" not in result


def test_deadline_preserves_existing_alarm_and_handler():
    previous = signal.getsignal(signal.SIGALRM)
    signal.setitimer(signal.ITIMER_REAL, 20)
    try:
        with pytest.raises(RuntimeError, match="existing alarm"), request_deadline(1):
            pytest.fail("Should refuse incompatible caller timer")
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 10
        assert signal.getsignal(signal.SIGALRM) == previous
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def test_non_main_thread_refuses_before_dispatch():
    errors = []

    def run():
        try:
            with request_deadline(1):
                errors.append("unexpected_dispatch")
        except RuntimeError:
            errors.append("refused")

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=2)
    assert errors == ["refused"]
