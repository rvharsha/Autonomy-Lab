# Frozen-runtime confirmation

**This corpus is retired from confirmation.** The original eight-case cohort
completed, but a corruption builder crashed on an optional missing labels map.
The original gate withheld selection. The corrected builder is validated only
post hoc; see [the results](../../docs/CONTRACT_CONFIRMATION_RESULTS.md).
Current commands are manual development regressions. No automatic PR rerun or
confirmation claim is permitted for these now-exposed cases.

This controller and evaluator are outside `src/autonomy_lab` because changing
that directory changes the already-selected procedure/runtime identity. The
measurement and audit checks derive from PR23, with explicit intermediate-write
and post-acknowledgement checks for the new protocol. The duplication preserves
the selected runtime; it is not a second agent implementation.

Read [the prospective protocol](../../docs/CONTRACT_CONFIRMATION_GATE.md) before
execution. The workflow freezes the plan once, executes all eight cases once in
four shards, retains failed attempts, and reproduces the complete inventory before
selection. Do not rerun the workflow as fresh confirmation after seeing results.

From the repository root, with the pinned dependencies installed:

```sh
PYTHONPATH=src:scripts:. .venv/bin/python -m experiments.contract_confirmation.run freeze artifacts/confirmation-plan.json
PYTHONPATH=src:scripts:. .venv/bin/python -m experiments.contract_confirmation.run run artifacts/confirmation-plan.json 0 artifacts/contract-confirmation-shard-0
PYTHONPATH=src:scripts:. .venv/bin/python -m experiments.contract_confirmation.run reproduce artifacts/confirmation-plan.json artifacts/downloaded-shards artifacts/confirmation-replay
```

The middle command is one of four regression shards, not the whole cohort. Live
execution requires the pinned Kubernetes/Docker tools installed by `make setup`.
Replay requires the exact experiment source **and** the pinned runtime, including
its dependency manifests. Archive the qualification commit and raw artifacts;
later runtime changes must not be substituted during replay. Hashes detect drift
on the trusted host, not malicious-host tampering.

The artifact allowlist excludes Kubernetes credentials and environment files.
Keep tests of deliberately corrupted evidence separate from real observations.
Full request cost remains unknown for interrupted verification/diagnosis work.
