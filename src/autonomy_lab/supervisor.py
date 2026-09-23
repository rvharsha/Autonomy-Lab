"""Controller-owned deadlines for a worker and its process group (POSIX)."""

import math
import os
import signal
import subprocess
import time
from pathlib import Path


def supervise(command: list[str], *, timeout: float, log_path: Path) -> dict:
    if type(timeout) not in (float, int) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Worker timeout must be finite and positive")
    started = time.monotonic()
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            # This session belongs only to this worker. Also remove descendants
            # (e.g. port-forwards) after crashes or apparently successful exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    return {"timed_out": timed_out, "exit_code": process.returncode,
            "elapsed_seconds": time.monotonic() - started, "timeout_seconds": timeout}
