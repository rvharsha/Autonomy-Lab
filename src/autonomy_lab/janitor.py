"""Detached cleanup of a controller's explicitly owned local resources."""

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT


def process_identity(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, timeout=5,
                            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TZ": "UTC", "LC_ALL": "C"})
    return result.stdout.strip() if result.returncode == 0 else ""


def start(run_dir, *, lifetime_seconds=7200):
    run_dir = Path(run_dir).resolve()
    metadata = json.loads((run_dir / "environment.json").read_text())
    if not valid_cluster(metadata["cluster"]):
        raise ValueError("Invalid janitor cluster identity")
    lease = {"controller_pid": os.getpid(), "controller_identity": process_identity(os.getpid()),
             "cluster": metadata["cluster"], "expires_at": time.time() + lifetime_seconds}
    if metadata["cluster"] == "autonomy-ax-spike":
        lease["kubeconfig"] = str(ROOT / ".state/ax-spike/runtime/kubeconfig")
    if not lease["controller_identity"]:
        raise ValueError("Cannot establish controller process identity")
    save(run_dir / "janitor-lease.json", lease)
    endpoint = os.environ.get("DOCKER_HOST") or subprocess.check_output(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True).strip()
    with (run_dir / "janitor.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, "-m", "autonomy_lab.janitor", str(run_dir)],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                                   env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                        "PYTHONPATH": str(ROOT / "src"), "DOCKER_HOST": endpoint})
    save(run_dir / "janitor-process.json", {"pid": process.pid})
    return process.pid


def remove_agent(path):
    runtime = json.loads(path.read_text())
    name = runtime.get("name", "")
    if not re.fullmatch(r"autolab-agent-[a-f0-9]{12}", name):
        raise ValueError("Invalid cleanup container")
    result = subprocess.run(["docker", "inspect", "--format", '{{index .Config.Labels "autonomy-lab.role"}}', name],
                            text=True, capture_output=True, timeout=15)
    if result.returncode == 0 and result.stdout.strip() == "agent":
        subprocess.run(["docker", "rm", "-f", name], check=True, timeout=30, capture_output=True)


def valid_cluster(cluster):
    return cluster == "autonomy-ax-spike" or bool(re.fullmatch(r"autolab-[a-f0-9]{8}", cluster))


def cleanup(run_dir, lease):
    cluster = lease["cluster"]
    if not valid_cluster(cluster):
        raise ValueError("Invalid cleanup target")
    errors = []
    # Only kill registered process groups whose leader still has the same start time.
    for path in [run_dir / "worker-lease.json", *run_dir.glob("trial-*/worker-lease.json")]:
        if not path.exists():
            continue
        try:
            worker = json.loads(path.read_text())
            pid = worker["pid"]
            if type(pid) is int and pid > 1 and worker.get("identity") and process_identity(pid) == worker["identity"]:
                if os.getpgid(pid) == pid:
                    os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception as error:
            errors.append({"resource": path.name, "error_type": type(error).__name__})
    for path in run_dir.glob("trial-*/agent-runtime.json"):
        try:
            remove_agent(path)
        except Exception as error:
            errors.append({"resource": path.name, "error_type": type(error).__name__})
    # The kind selector avoids deleting any unrelated Docker resource.
    nodes = subprocess.check_output(["docker", "ps", "-a", "--filter",
                                    f"label=io.x-k8s.kind.cluster={cluster}", "--format", "{{.Names}}"],
                                   text=True, timeout=15).splitlines()
    if any(not name.startswith(cluster + "-") for name in nodes):
        raise ValueError("Cluster ownership mismatch")
    subprocess.run([str(ROOT / ".tools/kind"), "delete", "cluster", "--name", cluster,
                    "--kubeconfig", lease.get("kubeconfig", str(run_dir / "kubeconfig"))], check=True, timeout=120, capture_output=True)
    if cluster == "autonomy-ax-spike":
        registry = cluster + "-registry"
        found = subprocess.run(["docker", "inspect", "--format", '{{index .Config.Labels "created-by"}}', registry],
                               capture_output=True, text=True, timeout=15)
        if found.returncode == 0:
            if found.stdout.strip() != "autonomy-lab-ax-spike":
                raise ValueError("Registry ownership mismatch")
            subprocess.run(["docker", "rm", "-f", "-v", registry], check=True, timeout=30, capture_output=True)
        # The launcher treats this exact owned path as an active-run marker.
        # kind removes its context but may leave an empty kubeconfig behind.
        (ROOT / ".state/ax-spike/runtime/kubeconfig").unlink(missing_ok=True)
    metadata = json.loads((run_dir / "environment.json").read_text())
    metadata["status"] = "deleted"
    save(run_dir / "environment.json", metadata)
    save(run_dir / "janitor-result.json", {"status": "deleted" if not errors else "partial", "nodes": nodes,
                                          "errors": errors, "finished_at": time.time()})


def main(run_dir):
    lease = json.loads((run_dir / "janitor-lease.json").read_text())
    try:
        while True:
            try:
                metadata = json.loads((run_dir / "environment.json").read_text())
                if metadata.get("status") == "deleted":
                    save(run_dir / "janitor-result.json", {"status": "normal_cleanup_observed"})
                    return
                alive = process_identity(lease["controller_pid"]) == lease["controller_identity"]
            except (OSError, ValueError, subprocess.TimeoutExpired):
                # A transient read/ps failure is not evidence of controller death.
                # The absolute lease still bounds cleanup if liveness stays unknown.
                alive = True
            if not alive or time.time() >= lease["expires_at"]:
                break
            time.sleep(2)
        cleanup(run_dir, lease)
    except Exception as error:
        save(run_dir / "janitor-result.json", {"status": "failed", "error_type": type(error).__name__})
        raise


if __name__ == "__main__":
    main(Path(sys.argv[1]))
