"""A real broker subprocess stopped only by the acceptance controller's SIGKILL."""

from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

from autonomy_lab.broker import ActionBroker, BrokerPolicy, Proposal
from autonomy_lab.kubernetes import Kubernetes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    settings = json.loads(args.input.read_text())
    stage = settings["stage"]
    if stage not in {"after_intent", "after_dispatch"}:
        raise ValueError("Unsupported process-kill barrier")
    proposal = Proposal.model_validate(settings["proposal"])
    policy = BrokerPolicy(
        proposal.run_id,
        proposal.namespace,
        proposal.service_name,
        proposal.service_uid,
        max_dispatches=1,
    )
    adapter = Kubernetes(Path(settings["kubeconfig"]), settings["cluster_name"], proposal.namespace)

    def barrier(point: str) -> None:
        if point == stage:
            print(
                json.dumps(
                    {
                        "stage": point,
                        "operation_id": proposal.operation_id,
                        "pid": os.getpid(),
                    }
                ),
                flush=True,
            )
            while True:
                signal.pause()

    broker = ActionBroker(settings["journal_path"], policy, adapter, hook=barrier)
    result = broker.propose(proposal)
    raise RuntimeError(f"Broker completed without reaching {stage}: {result['status']}")


if __name__ == "__main__":
    main()
