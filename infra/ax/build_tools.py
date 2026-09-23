"""Bounded local compilation only; no cluster, image push, or credential access."""
import datetime
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
for name in ("cache/go-build", "cache/go-mod", "cache/gopath", "tmp", "tools/bin"):
    (root / name).mkdir(parents=True, exist_ok=True)
env = {
    "PATH": f"{root / 'tools/go/bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
    "TMPDIR": str(root / "tmp"),
    "GOENV": "off",
    "GOTOOLCHAIN": "local",
    "GOCACHE": str(root / "cache/go-build"),
    "GOMODCACHE": str(root / "cache/go-mod"),
    "GOPATH": str(root / "cache/gopath"),
    "GOPROXY": "https://proxy.golang.org",
    "GOSUMDB": "sum.golang.org",
    "GOMAXPROCS": "2",
    "CGO_ENABLED": "0",
    "GOARCH": "arm64",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
targets = [
    ("ax", "ax", "darwin", "./cmd/ax"),
    ("ax-task-runner-linux-arm64", "ax", "linux", "./cmd/ax-task-runner"),
    ("kubectl-ate", "substrate", "darwin", "./cmd/kubectl-ate"),
]
record_name = "build-records.json"
if sys.argv[1:] == ["--runtime"]:
    targets = [
        ("ax-controller-linux-arm64", "ax", "linux", "./cmd/ax-controller"),
        ("ax-server-linux-arm64", "ax", "linux", "./cmd/ax-server"),
        ("ateom-gvisor-linux-arm64", "substrate", "linux", "./cmd/ateom-gvisor"),
        ("counter-linux-arm64", "substrate", "linux", "./demos/counter"),
    ]
    record_name = "runtime-build-records.json"
elif sys.argv[1:]:
    raise SystemExit("usage: build_tools.py [--runtime]")
records = []
for name, repo, goos, package in targets:
    command = [str(root / "tools/go/bin/go"), "build", "-mod=readonly", "-p=2", "-o", str(root / "tools/bin" / name), package]
    record = {"name": name, "command": command, "cwd": str(root / "sources" / repo), "goos": goos, "goarch": "arm64", "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    records.append(record)
    (root / "logs" / record_name).write_text(json.dumps(records, indent=2) + "\n")
    with (root / "logs" / f"build-{name}.log").open("w") as output:
        try:
            result = subprocess.run(command, cwd=record["cwd"], env={**env, "GOOS": goos}, stdout=output, stderr=subprocess.STDOUT, timeout=360)
            record["returncode"] = result.returncode
        except subprocess.TimeoutExpired:
            record["returncode"] = "timeout_after_360_seconds"
    record["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (root / "logs" / record_name).write_text(json.dumps(records, indent=2) + "\n")
    print(f"{name}: {record['returncode']}", flush=True)
    if record["returncode"] != 0:
        raise SystemExit(1)
