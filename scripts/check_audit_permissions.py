"""Real native-Linux audit ownership and rotation check; no model calls."""

import os
import sys
import time
import uuid

import yaml

from autonomy_lab import environment
from autonomy_lab.audit import configure, read_events
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT


def rotation_config(run_dir, base):
    path = configure(run_dir, base)
    config = yaml.safe_load(path.read_text())
    node = config["nodes"][0]
    patch = yaml.safe_load(node["kubeadmConfigPatches"][0])
    # Lower only this probe's rotation threshold; generate real API requests.
    patch["apiServer"]["extraArgs"]["audit-log-maxsize"] = "1"
    node["kubeadmConfigPatches"][0] = yaml.safe_dump(patch)
    path.write_text(yaml.safe_dump(config))
    return path


def main():
    if sys.platform != "linux" or os.getuid() == 0:
        raise RuntimeError("Run as the nonroot Linux controller to test actual read permission")
    identity = uuid.uuid4().hex[:8]
    output = ROOT / "artifacts" / ("audit-permissions-" + identity)
    output.mkdir(mode=0o700, parents=True)
    result = {"status": "running", "controller_uid": os.getuid(), "rotation_megabytes": 1}
    try:
        environment.configure = rotation_config
        try:
            kube = environment.provision(output, identity)
        finally:
            environment.configure = configure
        directory = output / "server-audit"
        deadline = time.monotonic() + 180
        for request in range(1, 3001):
            if time.monotonic() >= deadline:
                raise TimeoutError("Audit rotation request deadline exceeded")
            kube.get_service(kube.namespace, "inventory")
            if list(directory.glob("events-*.jsonl")):
                break
        else:
            raise RuntimeError("No real audit rotation observed within 3000 API reads")
        result["api_reads"] = request
        # Stop the real writer before parsing, retaining its bind-mounted logs.
        environment.teardown(output)
        result["cleanup"] = "deleted"
        files = [{"name": p.name, "uid": p.stat().st_uid, "mode": oct(p.stat().st_mode & 0o777)}
                 for p in sorted(directory.glob("events*.jsonl"))]
        result["files"] = files  # Retain ownership even when the read is denied.
        captured = read_events(directory)
        result.update(event_count=len(captured["events"]),
                      malformed_lines=captured["malformed_lines"])
        if (len(files) < 2 or not captured["events"] or captured["malformed_lines"]
                or any(p["uid"] != os.getuid() or p["mode"] != "0o600" for p in files)):
            raise RuntimeError("Audit ownership, privacy, rotation or read check failed")
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        try:
            if (output / "environment.json").exists() and result.get("cleanup") != "deleted":
                environment.teardown(output)
                result["cleanup"] = "deleted"
        except BaseException as error:
            result.update(status="failed", cleanup="failed", cleanup_error_type=type(error).__name__)
            raise
        finally:
            save(output / "result.json", result)
            print(output, flush=True)


if __name__ == "__main__":
    main()
