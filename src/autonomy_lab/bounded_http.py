"""Bounded synchronous HTTP for the lab's POSIX main-thread workers."""

import math
import signal
import threading
from contextlib import contextmanager

import httpx


class ResponseTooLarge(httpx.HTTPError):
    def __init__(self, status_code):
        super().__init__("HTTP response exceeded the byte limit")
        self.status_code = status_code


@contextmanager
def request_deadline(seconds):
    if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("HTTP deadline must be finite and positive")
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        raise RuntimeError("Bounded HTTP requires a POSIX main-thread worker")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise RuntimeError("Bounded HTTP cannot replace an existing alarm")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise httpx.TimeoutException("Total HTTP request deadline exceeded")

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def request(client, method, url, *, timeout, max_bytes, **kwargs):
    """Read at most max_bytes, including a deadline over headers and body.

    Request identity encoding and reject compressed responses before decoding to
    avoid allocating an unbounded decompressed chunk. No retries or redirects.
    """
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("HTTP byte limit must be a positive integer")
    headers = {**kwargs.pop("headers", {}), "Accept-Encoding": "identity"}
    with request_deadline(timeout):
        with client.stream(method, url, timeout=timeout, headers=headers,
                           follow_redirects=False, **kwargs) as response:
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise httpx.HTTPError("Compressed HTTP responses are not accepted")
            content = bytearray()
            # Injected test transports may already have buffered their response.
            chunks = response.iter_bytes() if response.is_stream_consumed else response.iter_raw()
            for chunk in chunks:
                if len(chunk) > max_bytes - len(content):
                    raise ResponseTooLarge(response.status_code)
                content.extend(chunk)
            return httpx.Response(response.status_code, headers=response.headers,
                                  content=bytes(content), request=response.request)
