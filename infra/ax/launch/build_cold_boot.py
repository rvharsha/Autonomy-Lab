import datetime
import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = {
    "PATH": f"{root}/tools/go/bin:/usr/bin:/bin:/usr/sbin:/sbin",
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
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
out = root / "logs" / f"cold-boot-build-{stamp}"
out.mkdir()
records = []
commands = [
    (
        "test",
        "darwin",
        ["test", "-mod=readonly", "-p=2", "./internal/controller", "./internal/substrate"],
    ),
    (
        "build",
        "linux",
        [
            "build",
            "-mod=readonly",
            "-p=2",
            "-o",
            str(root / "tools/bin/ax-controller-cold-boot-linux-arm64"),
            "./cmd/ax-controller",
        ],
    ),
]
for name, goos, args in commands:
    with (out / f"{name}.log").open("w") as log:
        result = subprocess.run(
            [str(root / "tools/go/bin/go"), *args],
            env={**env, "GOOS": goos},
            cwd=root / "sources/ax",
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
    records.append({"step": name, "goos": goos, "arguments": args, "returncode": result.returncode})
    (out / "result.json").write_text(json.dumps(records, indent=2) + "\n")
    print(name, result.returncode, flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
(root / "logs/cold-boot-binary.json").write_text(
    json.dumps(
        {
            "path": "tools/bin/ax-controller-cold-boot-linux-arm64",
            "sha256": hashlib.sha256(
                (root / "tools/bin/ax-controller-cold-boot-linux-arm64").read_bytes()
            ).hexdigest(),
            "source_sha256": hashlib.sha256(
                (root / "sources/ax/internal/substrate/client.go").read_bytes()
            ).hexdigest(),
            "build_record": str(out.relative_to(root)),
        },
        indent=2,
    )
    + "\n"
)
