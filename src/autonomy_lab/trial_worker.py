"""Private entry point for a supervised trial; no credentials in its request file."""

import json
import sys
from pathlib import Path

from autonomy_lab.experiments import release_manifest, run_trial, validate_config
from autonomy_lab.kubernetes import Kubernetes


def main(path: Path) -> int:
    try:
        request = json.loads(path.read_text())
        config = request["config"]
        validate_config(config)
        if release_manifest(config)["release_id"] != request["release_id"]:
            raise ValueError("Worker source does not match the declared release")
        kube = Kubernetes(Path(request["kubeconfig"]), request["cluster_name"], request["namespace"])
        run_trial(kube, path.parent, request["scenario"], request["variant"], config,
                  env_file=Path(request["env_file"]) if request["env_file"] else None)
        return 0
    except Exception as error:
        # Exception messages and tracebacks may contain credentials.
        print(json.dumps({"worker_error_type": type(error).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
