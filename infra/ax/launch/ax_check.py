"""Three actual AX data-snapshot reconstructions; no model or bootstrap goal."""

import datetime
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import yaml

root = Path(os.environ["SPIKE_ROOT"])
project = root.parents[1]
context = "kind-autonomy-ax-spike"
assert os.environ["KUBECTL_CONTEXT"] == context
out = (
    root
    / "logs"
    / ("ax-lifecycle-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
)
out.mkdir()
run_id = uuid.uuid4().hex
task_name = "lifecycle-" + run_id[:12]
atespace = "ax-probe"
kube = [
    str(project / ".tools/kubectl"),
    "--kubeconfig",
    os.environ["KUBECONFIG"],
    "--context",
    context,
    "--cache-dir",
    str(root / "runtime/kube-cache"),
    "--request-timeout=20s",
]
ate = [
    str(root / "tools/bin/kubectl-ate"),
    "--context",
    context,
    "--kubeconfig",
    os.environ["KUBECONFIG"],
    "-o",
    "json",
]
records = []
status = {
    "status": "running",
    "run_id": run_id,
    "task": task_name,
    "cycles_planned": 3,
    "cycles_completed": 0,
    "reads": [],
    "suspended_actors": [],
}
forward = None


def save():
    (out / "result.json").write_text(json.dumps(status, indent=2) + "\n")


def call(name, args, timeout=40, required=True):
    index = len(records)
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    (out / f"{index:03}-{name}.stdout").write_text(result.stdout)
    (out / f"{index:03}-{name}.stderr").write_text(result.stderr)
    records.append(
        {"name": name, "command": args, "started_at": start, "returncode": result.returncode}
    )
    (out / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
    if required and result.returncode:
        raise RuntimeError(f"{name} failed")
    return result


try:
    save()
    image = json.loads((root / "runtime/ax-images.json").read_text())["ax-task-runner"]
    manifests = [
        {
            "apiVersion": "ax.io/v1alpha1",
            "kind": "Workspace",
            "metadata": {"name": "state", "atespace": atespace},
            "spec": {},
        },
        {
            "apiVersion": "ax.io/v1alpha1",
            "kind": "Gateway",
            "metadata": {"name": "closed", "atespace": atespace},
            "spec": {"egress": {"allowlist": {"hosts": []}}},
        },
        {
            "apiVersion": "ax.io/v1alpha1",
            "kind": "Task",
            "metadata": {"name": task_name, "atespace": atespace},
            "spec": {
                "image": image,
                "command": ["python3", "/usr/local/bin/ax_probe_task.py"],
                "env": [{"name": "AX_PROBE_RUN_ID", "value": run_id}],
                "workspaces": [{"name": "state", "path": "/workspace"}],
                "gateway": {"name": "closed"},
                "debug": True,
            },
        },
    ]
    task_file = out / "task.yaml"
    task_file.write_text(yaml.safe_dump_all(manifests))
    with (out / "server-forward.log").open("w") as log:
        forward = subprocess.Popen(
            kube
            + [
                "-n",
                "ax-system",
                "port-forward",
                "--address",
                "127.0.0.1",
                "svc/ax-server",
                ":8080",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    deadline = time.monotonic() + 30
    while True:
        match = re.search(
            r"Forwarding from 127\.0\.0\.1:(\d+) ->", (out / "server-forward.log").read_text()
        )
        if match:
            break
        if forward.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("AX server forward failed")
        time.sleep(0.2)
    ax = [
        str(root / "tools/bin/ax"),
        "--server",
        f"http://127.0.0.1:{match[1]}",
        "--context",
        context,
        "--atespace",
        atespace,
    ]
    call("apply", ax + ["apply", "-f", str(task_file)])

    def wait_phase(phase):
        deadline = time.monotonic() + 120
        while True:
            response = call("get-task", ax + ["get", "task", task_name])
            task = yaml.safe_load(response.stdout)
            state = task.get("status") or {}
            ready = any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in state.get("conditions", [])
            )
            if state.get("phase") == phase and (phase != "Running" or ready):
                return task
            if time.monotonic() > deadline:
                raise TimeoutError(f"AX task did not reach {phase}")
            time.sleep(2)

    read_code = "import json,os;from pathlib import Path;p=Path('/workspace/ax-lifecycle.json');d=json.loads(p.read_text());pid=d['startups'][-1]['pid'];assert b'ax_probe_task.py' in Path(f'/proc/{pid}/cmdline').read_bytes();assert not any(os.environ.get(k) for k in ('GEMINI_API_KEY','GOOGLE_API_KEY','ANTHROPIC_API_KEY'));print(json.dumps(d))"

    def read_state(previous=None):
        deadline = time.monotonic() + 30
        while True:
            r = call(
                "read-startup",
                ax + ["ssh", task_name, "--", "python3", "-c", read_code],
                required=False,
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                assert data["run_id"] == run_id
                if previous is None or len(data["startups"]) > len(previous["startups"]):
                    return data
            if time.monotonic() > deadline:
                raise TimeoutError("fresh task command did not start")
            time.sleep(1)

    wait_phase("Running")
    previous = read_state()
    assert previous["startups"]
    status["reads"].append(previous)
    save()
    for cycle in range(3):
        call("suspend", ax + ["suspend", "task", task_name])
        wait_phase("Suspended")
        actor = json.loads(
            call("get-suspended-actor", ate + ["get", "actor", task_name, "-a", atespace]).stdout
        )["actors"][0]
        assert actor["status"]["state"] == "ACTOR_STATE_SUSPENDED"
        assert actor["status"]["externalSnapshot"]["snapshotUri"]
        status["suspended_actors"].append(
            {
                "state": actor["status"]["state"],
                "snapshot_present": True,
                "uid": actor["metadata"]["uid"],
            }
        )
        save()
        call("resume", ax + ["resume", "task", task_name])
        wait_phase("Running")
        current = read_state(previous)
        assert len(current["startups"]) == len(previous["startups"]) + 1
        assert current["startups"][:-1] == previous["startups"]
        assert current["startups"][-1]["boot_id"] not in {
            s["boot_id"] for s in previous["startups"]
        }
        status["reads"].append(current)
        status["cycles_completed"] = cycle + 1
        save()
        previous = current
    # Exercise actual capacity loss after the original three-cycle gate.
    call("capacity-suspend", ax + ["suspend", "task", task_name])
    wait_phase("Suspended")
    call("capacity-zero", kube + ["-n", "ate-demo-counter", "patch", "workerpool", "counter", "--type=merge", "-p", '{"spec":{"replicas":0}}'])
    call("capacity-workers-gone", kube + ["-n", "ate-demo-counter", "wait", "--for=delete", "pod", "-l", "ate.dev/worker-pool=counter", "--timeout=60s"], timeout=70)
    # Pod deletion and the scheduler's registry converge separately. This gate
    # tests pre-assignment capacity rejection, not loss during an assigned restore.
    deadline = time.monotonic() + 60
    while True:
        workers = json.loads(call("capacity-worker-registry", ate + ["get", "workers"]).stdout)
        active = [worker for worker in workers.get("workers", [])
                  if worker.get("status", {}).get("state") == "WORKER_STATE_ACTIVE"]
        if not active:
            status["capacity_empty_registry"] = workers
            save()
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("worker registry did not drain")
        time.sleep(1)
    call("capacity-resume", ax + ["resume", "task", task_name])
    deadline = time.monotonic() + 20
    while True:
        logs = call("capacity-controller-log", kube + ["-n", "ax-system", "logs", "deployment/ax-controller", "--tail=100"]).stdout
        if 'waiting for actor capacity' in logs:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("did not observe real capacity rejection")
        time.sleep(1)
    call("capacity-restore", kube + ["-n", "ate-demo-counter", "patch", "workerpool", "counter", "--type=merge", "-p", '{"spec":{"replicas":1}}'])
    wait_phase("Running")
    current = read_state(previous)
    assert len(current["startups"]) == len(previous["startups"]) + 1
    assert current["startups"][:-1] == previous["startups"]
    status["capacity_recovery"] = {"status": "passed", "manual_resume_requests": 1, "state": current}
    templates = json.loads(call("final-templates", ate + ["get", "actor-templates", "-a", atespace]).stdout)
    status["templates"] = templates
    assert len(templates["actorTemplates"]) == 1, "lifecycle must not proliferate templates"
    call("delete-probe-task", ax + ["delete", "task", task_name])
    deadline = time.monotonic() + 60
    while call("await-probe-deletion", ax + ["get", "task", task_name], required=False).returncode == 0:
        if time.monotonic() >= deadline:
            raise TimeoutError("probe task cleanup did not finish")
        time.sleep(1)
    status["task_cleanup"] = "deleted"
    status["status"] = "passed"
except BaseException as error:
    status.update(status="failed", error_type=type(error).__name__)
    if isinstance(error, (RuntimeError, TimeoutError)):
        status["reason"] = str(error)
    raise
finally:
    if forward is not None and forward.poll() is None:
        forward.terminate()
        try:
            forward.wait(timeout=5)
        except subprocess.TimeoutExpired:
            forward.kill()
            forward.wait(timeout=5)
    status["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(out, flush=True)
