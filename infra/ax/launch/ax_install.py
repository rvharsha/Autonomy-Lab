"""Install the pinned AX binaries with a model-free ARM64 task image."""

import datetime
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import yaml

root = Path(os.environ["SPIKE_ROOT"])
project = root.parents[1]
assert os.environ["KUBECTL_CONTEXT"] == "kind-autonomy-ax-spike"
out = (
    root
    / "logs"
    / ("ax-install-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
)
out.mkdir()
records = []


def call(name, args, timeout=180):
    with (out / f"{name}.stdout").open("w") as stdout, (out / f"{name}.stderr").open("w") as stderr:
        result = subprocess.run(args, stdout=stdout, stderr=stderr, timeout=timeout)
    records.append({"name": name, "command": args, "returncode": result.returncode})
    (out / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
    if result.returncode:
        raise RuntimeError(f"{name} failed")
    return (out / f"{name}.stdout").read_text()


context = root / "runtime/ax-images"
context.mkdir(exist_ok=True)
base = json.loads((project / "infra/toolchain.json").read_text())["python_image"]
images = {}
for binary in ["ax-task-runner", "ax-controller", "ax-server"]:
    source_name = (
        "ax-controller-cold-boot-linux-arm64"
        if binary == "ax-controller"
        else f"{binary}-linux-arm64"
    )
    shutil.copyfile(root / "tools/bin" / source_name, context / binary)
    (context / binary).chmod(0o755)
    shutil.copyfile(root / "launch/ax_probe_task.py", context / "ax_probe_task.py")
    dockerfile = context / f"Dockerfile.{binary}"
    extra = ""
    if binary == "ax-task-runner":
        shutil.copyfile(project / "requirements.lock", context / "requirements.lock")
        package = context / "autonomy_lab"
        package.mkdir(exist_ok=True)
        for name in ["__init__.py", "agent.py", "context.py", "rpc.py", "isolated_agent.py", "mailbox.py"]:
            shutil.copyfile(project / "src/autonomy_lab" / name, package / name)
        extra = "COPY requirements.lock /app/requirements.lock\nRUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock\nCOPY autonomy_lab /app/autonomy_lab\nRUN chmod -R 0555 /app/autonomy_lab\nENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\n"
    dockerfile.write_text(
        f'FROM {base}\nCOPY {binary} /usr/local/bin/{binary}\nCOPY ax_probe_task.py /usr/local/bin/ax_probe_task.py\n{extra}ENTRYPOINT ["/usr/local/bin/{binary}"]\n'
    )
    tag = f"localhost:5007/{binary}:ax-spike"
    call(
        f"build-{binary}",
        [
            "docker",
            "build",
            "--platform",
            "linux/arm64",
            "-f",
            str(dockerfile),
            "-t",
            tag,
            str(context),
        ],
        240,
    )
    call(f"push-{binary}", ["docker", "push", tag])
    digests = json.loads(
        call(
            f"digest-{binary}",
            ["docker", "image", "inspect", tag, "--format", "{{json .RepoDigests}}"],
        )
    )
    images[binary] = next(d for d in digests if d.startswith(f"localhost:5007/{binary}@sha256:"))
redis = json.loads((root / "logs/redis-image.json").read_text())
assert redis["architecture"] == "arm64"
objects = []
for filename in ["redis.yaml", "ax-controller.yaml", "ax-server.yaml"]:
    objects.extend(yaml.safe_load_all((root / "sources/ax/deploy" / filename).read_text()))
for obj in objects:
    if obj["kind"] != "Deployment":
        continue
    name = obj["metadata"]["name"]
    container = obj["spec"]["template"]["spec"]["containers"][0]
    container["image"] = redis["digest"] if name == "ax-redis" else images[name]
    if name == "ax-controller":
        container.setdefault("env", []).append(
            {"name": "AX_SNAPSHOTS_BUCKET", "value": "gs://ate-snapshots/ax-probe/"}
        )
manifest = out / "deployment.yaml"
manifest.write_text(yaml.safe_dump_all(objects))
kubectl = [
    str(project / ".tools/kubectl"),
    "--kubeconfig",
    os.environ["KUBECONFIG"],
    "--context",
    os.environ["KUBECTL_CONTEXT"],
    "--cache-dir",
    str(root / "runtime/kube-cache"),
    "--request-timeout=20s",
]
call("apply", kubectl + ["apply", "-f", str(manifest)])
for name in ["ax-redis", "ax-controller", "ax-server"]:
    call(
        f"ready-{name}",
        kubectl + ["-n", "ax-system", "rollout", "status", f"deployment/{name}", "--timeout=120s"],
        150,
    )
# Kubernetes Running does not prove the stream consumer has subscribed.
# AX creates new groups at '$'; publishing a task first can leave it Pending.
deadline = time.monotonic() + 120
attempt = 0
while True:
    attempt += 1
    raw = call(
        f"controller-consumer-{attempt}",
        kubectl
        + [
            "-n",
            "ax-system",
            "exec",
            "deployment/ax-redis",
            "--",
            "redis-cli",
            "--json",
            "XINFO",
            "GROUPS",
            "ax:stream:tasks",
        ],
        30,
    )
    try:
        groups = json.loads(raw)
    except ValueError:
        groups = []
    if isinstance(groups, list):
        groups = [dict(zip(g[::2], g[1::2])) if isinstance(g, list) else g for g in groups]
        if any(isinstance(g, dict) and g.get("name") == "ax-controllers" for g in groups):
            break
    if time.monotonic() >= deadline:
        raise TimeoutError("AX controller consumer group did not become ready")
    time.sleep(1)
(root / "runtime/ax-images.json").write_text(json.dumps(images, indent=2) + "\n")
(out / "result.json").write_text(
    json.dumps(
        {
            "status": "passed",
            "images": images,
            "redis": redis,
            "consumer_group_ready": True,
            "consumer_group_checks": attempt,
        },
        indent=2,
    )
    + "\n"
)
print(out, flush=True)
