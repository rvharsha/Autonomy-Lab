"""One real, scoped runtime attempt; retain logs and clean up owned resources."""

import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

from autonomy_lab.harness import save as save_json
from autonomy_lab.janitor import start as start_janitor
from autonomy_lab.supervisor import supervise

root = Path(__file__).resolve().parents[1]
project = root.parents[1]
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
out = root / "logs" / f"execution-{stamp}"
out.mkdir(mode=0o700)
os.umask(0o077)
env = {
    "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    "DOCKER_HOST": os.environ.get("DOCKER_HOST") or subprocess.check_output(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True).strip(),
    "DOCKER_CONFIG": str(root / "runtime/docker-config"),
}
cluster = "autonomy-ax-spike"
registry = "autonomy-ax-spike-registry"
kubeconfig = root / "runtime/kubeconfig"
status = {
    "started_at": stamp,
    "status": "preflight",
    "phases": [],
    "cleanup": [],
    "limits": {
        "node_memory_bytes": 5 * 1024**3,
        "node_cpus": 5,
        "registry_memory_bytes": 256 * 1024**2,
    },
    "source_hashes": {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "launch").glob("*"))
        if p.is_file()
    },
    "substrate_revision": "672533541dbfcd29084e4de2475267088bda3651",
    "ax_revision": "d8ed0fe38bceb7842d3c47817d53d16ccdfcb601",
    "ax_compatibility_patch": json.loads((project / "infra/ax/patch-manifest.json").read_text()),
    "recovery_patch_sha256": hashlib.sha256((project / "infra/ax/recovery.patch").read_bytes()).hexdigest(),
    "privilege_drop_patch_sha256": hashlib.sha256((project / "infra/ax/privilege-drop.patch").read_bytes()).hexdigest(),
    "durable_cleanup_patch_sha256": hashlib.sha256((project / "infra/ax/durable-cleanup.patch").read_bytes()).hexdigest(),
    "source_manifest": json.loads((project / "infra/ax/source-manifest.json").read_text()),
    "ax_controller_binary": json.loads((root / "logs/cold-boot-binary.json").read_text()),
}


def save():
    (out / "result.json").write_text(json.dumps(status, indent=2) + "\n")


def command(name, args, timeout=60, required=True):
    result = subprocess.run(args, env=env, text=True, capture_output=True, timeout=timeout)
    (out / f"{name}.stdout").write_text(result.stdout)
    (out / f"{name}.stderr").write_text(result.stderr)
    if required and result.returncode:
        raise RuntimeError(f"{name} failed with exit {result.returncode}")
    return result


save()
# Preflight failures do not authorize cleanup of pre-existing resources.
names = command(
    "existing-containers", ["docker", "ps", "-a", "--format", "{{.Names}}"]
).stdout.splitlines()
if (
    any(name.startswith("autolab-") or name.startswith(cluster) for name in names)
    or registry in names
    or kubeconfig.exists()
):
    status.update(status="blocked", reason="existing_lab_resources_or_kubeconfig")
    save()
    raise SystemExit(1)
try:
    save_json(out / "environment.json", {"cluster": cluster, "status": "creating"})
    start_janitor(out, lifetime_seconds=4500)
    status["status"] = "running"
    save()
    phases = [
        ("create", 600),
        ("install", 1200),
        ("counter", 600),
        ("ax_install", 600),
        ("ax_check", 600),
    ]
    if os.environ.get("AX_LAB_INTEGRATION_ENV_FILE"):
        phases.append(("ax_integration", 900))
    for phase, timeout in phases:
        print(f"Runtime phase {phase}: deadline {timeout}s", flush=True)
        record = {"phase": phase, "timeout_seconds": timeout}
        status["phases"].append(record)
        save()
        result = supervise(
            ["/bin/bash", str(root / "launch/run_ax.sh"), phase],
            timeout=timeout,
            log_path=out / f"{phase}.log",
        )
        record.update(result)
        save()
        if result["timed_out"] or result["exit_code"]:
            raise RuntimeError(f"{phase} failed")
        if phase == "create":
            node = f"{cluster}-control-plane"
            label = command(
                "node-owner",
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "io.x-k8s.kind.cluster"}}',
                    node,
                ],
            ).stdout.strip()
            if label != cluster:
                raise RuntimeError("node ownership mismatch")
            command(
                "cap-node",
                ["docker", "update", "--memory", "5g", "--memory-swap", "5g", "--cpus", "5", node],
            )
            command(
                "cap-registry",
                ["docker", "update", "--memory", "256m", "--memory-swap", "256m", registry],
            )
    status["status"] = "passed"
except BaseException as error:
    status.update(status="failed", error_type=type(error).__name__)
    if isinstance(error, RuntimeError):
        status["reason"] = str(error)
    raise
finally:
    save()
    if kubeconfig.exists():
        args = [
            str(project / ".tools/kubectl"),
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            f"kind-{cluster}",
            "--cache-dir",
            str(root / "runtime/kube-cache"),
            "--request-timeout=15s",
        ]
        for name, suffix in [
            ("pods", ["get", "pods", "-A", "-o", "wide"]),
            ("events", ["get", "events", "-A", "--sort-by=.lastTimestamp"]),
            ("workerpools", ["get", "workerpools", "-A", "-o", "yaml"]),
            ("api", ["-n", "ate-system", "logs", "deployment/ate-api-server", "--all-containers", "--tail=1000"]),
            ("ate-controller", ["-n", "ate-system", "logs", "deployment/ate-controller", "--all-containers", "--tail=500"]),
            (
                "ax-controller",
                ["-n", "ax-system", "logs", "deployment/ax-controller", "--tail=200"],
            ),
            (
                "worker",
                [
                    "-n",
                    "ate-demo-counter",
                    "logs",
                    "-l",
                    "ate.dev/worker-pool=counter",
                    "--all-containers",
                    "--tail=200",
                ],
            ),
        ]:
            try:
                command(name, args + suffix, required=False, timeout=30)
            except Exception:
                pass
    try:
        command(
            "delete-cluster",
            [
                str(project / ".tools/kind"),
                "delete",
                "cluster",
                "--name",
                cluster,
                "--kubeconfig",
                str(kubeconfig),
            ],
            timeout=120,
        )
        status["cleanup"].append({"resource": cluster, "status": "deleted"})
    except Exception as error:
        status["cleanup"].append(
            {"resource": cluster, "status": "failed", "error_type": type(error).__name__}
        )
    try:
        names = command(
            "containers-after-cluster", ["docker", "ps", "-a", "--format", "{{.Names}}"]
        ).stdout.splitlines()
        if registry in names:
            owner = command(
                "registry-owner",
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "created-by"}}',
                    registry,
                ],
            ).stdout.strip()
            if owner != "autonomy-lab-ax-spike":
                raise RuntimeError("registry ownership mismatch")
            command("delete-registry", ["docker", "rm", "-f", "-v", registry])
        status["cleanup"].append({"resource": registry, "status": "deleted_or_absent"})
    except Exception as error:
        status["cleanup"].append(
            {"resource": registry, "status": "failed", "error_type": type(error).__name__}
        )
    if all(item["status"] != "failed" for item in status["cleanup"]):
        kubeconfig.unlink(missing_ok=True)
        save_json(out / "environment.json", {"cluster": cluster, "status": "deleted"})
    status["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(out, flush=True)
