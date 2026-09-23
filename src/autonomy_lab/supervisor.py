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
        from autonomy_lab.harness import save
        timed_out = False
        cleanup_errors = []
        try:
            if any((parent / "janitor-lease.json").exists() for parent in log_path.parents):
                from autonomy_lab.harness import save
                from autonomy_lab.janitor import process_identity
                identity = process_identity(process.pid)
                if identity:
                    save(log_path.parent / "worker-lease.json", {"pid": process.pid, "identity": identity})
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
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cleanup_errors.append("WorkerReapTimeout")
            runtime = log_path.parent / "agent-runtime.json"
            if runtime.exists():
                from autonomy_lab.janitor import remove_agent
                try:
                    remove_agent(runtime)
                except Exception as error:
                    cleanup_errors.append(type(error).__name__)
    return {"timed_out": timed_out, "exit_code": process.returncode,
            "elapsed_seconds": time.monotonic() - started, "timeout_seconds": timeout,
            **({"error_type": "CleanupError", "cleanup_errors": cleanup_errors} if cleanup_errors else {})}
