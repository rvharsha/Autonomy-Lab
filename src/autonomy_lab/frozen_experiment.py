"""Execute a copied, read-only release independently of the editable checkout."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from autonomy_lab.kubernetes import ROOT


def freeze(config, *, env_file=None, keep=False):
    from autonomy_lab.experiments import release_manifest

    release = release_manifest(config)
    directory = ROOT / ".state/releases"
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix=release["release_id"][:12] + "-", dir=directory))
    for name in [*release["files"], ".dockerignore"]:
        source, target = ROOT / name, snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o444)
    (snapshot / ".tools").mkdir()
    for name in ["kind", "kubectl"]:
        shutil.copyfile(ROOT / ".tools" / name, snapshot / ".tools" / name)
        (snapshot / ".tools" / name).chmod(0o555)
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (snapshot / "artifacts").symlink_to(ROOT / "artifacts", target_is_directory=True)
    (snapshot / ".frozen-release").write_text(json.dumps(release, sort_keys=True))
    for path in sorted(snapshot.rglob("*"), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o555)
    snapshot.chmod(0o555)
    request = directory / (snapshot.name + "-request.json")
    output = directory / (snapshot.name + "-result.json")
    request.write_text(json.dumps({"config": config, "env_file": str(env_file.expanduser().resolve()) if env_file else None,
                                   "keep": keep, "output": str(output)}))
    process = subprocess.run([sys.executable, "-m", "autonomy_lab.frozen_experiment", str(request)],
                             cwd=snapshot, env={**os.environ, "PYTHONPATH": str(snapshot / "src"),
                                               "PYTHONDONTWRITEBYTECODE": "1"})
    if process.returncode:
        raise RuntimeError("Frozen experiment failed; retained artifacts include its failure")
    return Path(json.loads(output.read_text())["run_dir"])


def main():
    from autonomy_lab.experiments import run_experiment

    if not (ROOT / ".frozen-release").is_file():
        raise ValueError("Frozen execution requires a copied release")
    request = json.loads(Path(sys.argv[1]).read_text())
    path = run_experiment(request["config"], env_file=Path(request["env_file"]) if request["env_file"] else None,
                          keep=request["keep"])
    Path(request["output"]).write_text(json.dumps({"run_dir": str(path.resolve())}))


if __name__ == "__main__":
    main()
