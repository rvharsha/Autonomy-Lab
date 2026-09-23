"""Bounded JSON frames for the agent's credential-free process boundary."""

import json

MAX_FRAME_BYTES = 8 * 1024 * 1024


class RemoteError(RuntimeError):
    def __init__(self, record):
        super().__init__(record.get("error_type", "RemoteError"))
        self.status_code = record.get("status_code")
        self.response = record.get("response")


def read_frame(stream):
    line = stream.readline(MAX_FRAME_BYTES + 1)
    if not line or len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
        raise ValueError("Missing or oversized RPC frame")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("RPC frame must be an object")
    return value


def write_frame(stream, value):
    data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError("RPC frame too large")
    stream.write(data)
    stream.flush()


def error_record(error):
    record = {"error_type": type(error).__name__}
    code = getattr(error, "status_code", None)
    if type(code) is int and 100 <= code <= 599:
        record["status_code"] = code
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        record["response"] = response
    return record


class PipeReader:
    """Retain surplus bytes and enforce a deadline across partial pipe writes."""
    def __init__(self, stream):
        import os
        self.fd = stream.fileno()
        self.buffer = bytearray()
        os.set_blocking(self.fd, False)

    def read(self, deadline):
        import os
        import select
        import time
        while True:
            end = self.buffer.find(b"\n")
            if end >= 0:
                if end + 1 > MAX_FRAME_BYTES:
                    raise ValueError("Oversized RPC frame")
                line = bytes(self.buffer[:end + 1])
                del self.buffer[:end + 1]
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("RPC frame must be an object")
                return value
            if len(self.buffer) >= MAX_FRAME_BYTES:
                raise ValueError("Oversized RPC frame")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
                raise TimeoutError("RPC frame deadline")
            try:
                chunk = os.read(self.fd, min(65536, MAX_FRAME_BYTES - len(self.buffer)))
            except BlockingIOError:
                continue
            if not chunk:
                raise ValueError("Missing RPC frame")
            self.buffer.extend(chunk)


class PipeWriter:
    def __init__(self, stream):
        import os
        self.fd = stream.fileno()
        os.set_blocking(self.fd, False)

    def write(self, value, deadline):
        import os
        import select
        import time
        data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(data) > MAX_FRAME_BYTES:
            raise ValueError("RPC frame too large")
        offset = 0
        while offset < len(data):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError("RPC write deadline")
            try:
                offset += os.write(self.fd, data[offset:offset + 65536])
            except BlockingIOError:
                continue
