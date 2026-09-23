"""Prepare the pinned ARM64 AX variant on macOS; execute only with --execute.

Requires the repository's normal Python/Kubernetes tool setup and Docker. All
sources, tools, caches, and runtime evidence stay in .state/ax-spike. Downloads
are checksum verified; unexpected source edits are rejected, never overwritten.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
PACKAGE = PROJECT / "infra/ax"
ROOT = PROJECT / ".state/ax-spike"
SOURCES = {
    "ax": ("https://github.com/google/ax.git", "d8ed0fe38bceb7842d3c47817d53d16ccdfcb601"),
    "substrate": ("https://github.com/agent-substrate/substrate.git", "672533541dbfcd29084e4de2475267088bda3651"),
}
ARCHIVES = [
    ("https://go.dev/dl/go1.27.1.darwin-arm64.tar.gz", "ee215d57e0ec269c60cc9ceca68e6bda321ba9ee5afe24f4b0988703c2d87d12", "tools"),
    ("https://github.com/ko-build/ko/releases/download/v0.19.1/ko_0.19.1_Darwin_arm64.tar.gz", "a1338c4140c8c94e789733e21b161a3de177b467cd3c388b634fe1a869574509", "tools/ko"),
]
REDIS = "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499"


def call(args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=600, **kwargs)


def patch(source, filename):
    path = PACKAGE / filename
    if subprocess.run(["git", "apply", "--reverse", "--check", str(path)], cwd=source, capture_output=True).returncode == 0:
        return
    call(["git", "apply", "--check", str(path)], cwd=source)
    call(["git", "apply", str(path)], cwd=source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--env-file", type=Path, help="Also run the bounded live Gemini AX integration")
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise RuntimeError("This validated launcher currently supports macOS ARM64 only")
    os.umask(0o077)
    for directory in ["logs", "launch", "sources", "source-review", "tools", "tmp", "runtime"]:
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    if (ROOT / "runtime/kubeconfig").exists():
        raise RuntimeError("Existing runtime kubeconfig; refusing preparation during an active run")
    for name, (url, revision) in SOURCES.items():
        source = ROOT / "sources" / name
        if not source.exists():
            call(["git", "clone", "--no-checkout", url, str(source)])
            call(["git", "checkout", "--detach", revision], cwd=source)
        if call(["git", "rev-parse", "HEAD"], cwd=source).strip() != revision:
            raise RuntimeError("Unexpected source revision")
    for url, expected, destination in ARCHIVES:
        archive = ROOT / "tmp" / url.rsplit("/", 1)[1]
        if not archive.exists():
            call(["curl", "--fail", "--location", "--proto", "=https", "--tlsv1.2", "--output", str(archive), url])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Tool archive checksum mismatch")
        directory = ROOT / destination
        directory.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as stream:
            stream.extractall(directory, filter="data")
    for path in (PACKAGE / "launch").iterdir():
        if path.is_file():
            shutil.copyfile(path, ROOT / "launch" / path.name)
    shutil.copyfile(PACKAGE / "build_tools.py", ROOT / "build_tools.py")
    # Source preparation is itself pinned in the committed patch, not inferred
    # from an arbitrary local script or a previously generated success file.
    patch(ROOT / "sources/substrate", "substrate-local.patch")
    patch(ROOT / "sources/ax", "cold-boot.patch")
    patch(ROOT / "sources/ax", "recovery.patch")
    shutil.copyfile(PACKAGE / "runtime_config_test.go", ROOT / "sources/ax/internal/controller/runtime_config_test.go")
    manifest = json.loads((PACKAGE / "source-manifest.json").read_text())
    for name, record in manifest.items():
        source = ROOT / "sources" / name
        actual = set(call(["git", "diff", "--name-only"], cwd=source).splitlines())
        actual.update(call(["git", "ls-files", "--others", "--exclude-standard"], cwd=source).splitlines())
        # kubectl's generated discovery cache is data, never compiled source.
        actual = {name for name in actual if not name.startswith(".kube/cache/")}
        if actual != set(record["changed_files"]):
            raise RuntimeError("Unexpected source changes")
        for relative, expected in record["changed_files"].items():
            if hashlib.sha256((source / relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError("Source patch hash mismatch")
    call(["docker", "pull", REDIS])
    architecture = call(["docker", "image", "inspect", "--format", "{{.Architecture}}", REDIS]).strip()
    if architecture != "arm64":
        raise RuntimeError("Redis architecture mismatch")
    (ROOT / "logs/redis-image.json").write_text(json.dumps({"digest": REDIS, "architecture": architecture}) + "\n")
    for suffix in [[], ["--runtime"]]:
        subprocess.run([sys.executable, str(ROOT / "build_tools.py"), *suffix], check=True)
    subprocess.run([sys.executable, str(ROOT / "launch/build_cold_boot.py")], check=True)
    if args.execute:
        subprocess.run([sys.executable, str(ROOT / "launch/execute_ax.py")],
                       env={**os.environ, "PYTHONPATH": str(PROJECT / "src"),
                            **({"AX_LAB_INTEGRATION_ENV_FILE": str(args.env_file.expanduser().resolve())} if args.env_file else {})}, check=True)


if __name__ == "__main__":
    main()
