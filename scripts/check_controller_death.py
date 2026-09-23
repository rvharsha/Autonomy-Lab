"""SIGKILL a real provisioning controller and require detached resource cleanup."""

import json
import os
import signal
import subprocess
import sys
import time
import uuid

from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT


def main():
    identity = uuid.uuid4().hex[:8]
    output = ROOT / "artifacts" / ("controller-death-" + identity)
    output.mkdir(mode=0o700, parents=True)
    code = '''from pathlib import Path
import sys,time
from autonomy_lab.environment import provision
p=Path(sys.argv[1]);provision(p,sys.argv[2]);(p/'ready').touch()
while True: time.sleep(1)
'''
    with (output / "controller.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-c", code, str(output), identity],
                                   env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                   stdout=log, stderr=log, start_new_session=True)
    result = {"controller_pid": process.pid, "cluster": "autolab-" + identity, "status": "running"}
    try:
        deadline = time.monotonic() + 600
        while not (output / "ready").exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Controller did not provision the real application")
            time.sleep(1)
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        result["controller_exit_code"] = process.returncode
        deadline = time.monotonic() + 160
        while not (output / "janitor-result.json").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("Detached janitor did not finish")
            time.sleep(1)
        result["janitor"] = json.loads((output / "janitor-result.json").read_text())
        remaining = subprocess.check_output(["docker", "ps", "-a", "--filter",
                                            f"label=io.x-k8s.kind.cluster=autolab-{identity}",
                                            "--format", "{{.Names}}"], text=True, timeout=15).splitlines()
        result["remaining_nodes"] = remaining
        if remaining or result["janitor"]["status"] != "deleted":
            raise RuntimeError("Controller-independent cleanup failed")
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        save(output / "result.json", result)
        print(output, flush=True)


if __name__ == "__main__":
    main()
