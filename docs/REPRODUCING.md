# Reproduce and demonstrate the research handoff

Start from a fresh checkout of the corrected `v0.1.1` research release. Requirements are Git, Python 3.12, uv and a working Docker daemon; initial setup needs internet access. GCP operators use the [existing host and access instructions](../infra/gcp/README.md). The package version is 0.1.1; the release tag identifies the complete repository, not a claim that historical experiments used this version.

```sh
git clone --branch v0.1.1 https://github.com/rvharsha/Autonomy-Lab- autonomy-lab
cd autonomy-lab
make setup
make test lint
make demo
```

The acceptance demo uses no model credential. It creates real Kubernetes and PostgreSQL workloads, tests the verifier and execution boundary, records results under `artifacts/demo-*/`, and removes its cluster. Provisioning time depends on image caches and network access.

## Regenerate the published comparison tables offline

These commands read committed selected evidence and need only Python's standard library. They make no model or cloud requests. Each output directory must be new.

```sh
python3 scripts/export_report.py --published docs/validation/reliability-validation.json --output artifacts/reliability-report
python3 scripts/export_report.py --published docs/validation/reconciliation-validation.json --output artifacts/reconciliation-report
```

Expect reliability phases **12/12, 8/8, 16/18** and reconciliation phases **6/6, 17/18**. Generated JSON retains per-trial outcomes and a digest of the selected source evidence. Regenerating a table is an accounting check; it is not a fresh execution or independent authentication of the retained observations. Historical selected reports and original denominators are unchanged.

## Execute the declared model-free handoff experiment

```sh
PYTHONPATH=src .venv/bin/python scripts/run_evaluation.py scenarios/handoff-acceptance.yaml
PYTHONPATH=src .venv/bin/python scripts/run_evaluation.py scenarios/handoff-acceptance.yaml --execute
```

The first command prints a plan without provisioning. The second runs exactly four real trials: routing and healthy, each with a deterministic runbook and a no-agent control. Routing must recover with the runbook and remain failed with no agent; both healthy cases must remain healthy. **The no-agent routing case is an intended negative control, not an expected task completion.** Do not use four supported completions as the acceptance criterion. Require all four recorded, these environment outcomes, assessed clean scoped audits, no protected damage and cluster deletion.

The command prints an `artifacts/evaluation-*/evaluation.json` ledger. Its phases identify the actual `run_dir` values. The ledger preserves stopped and unrun phases; after an exception, raw interrupted artifacts also remain under `artifacts/experiment-*`. There is no automatic resume or retry. Use the actual experiment path printed in the ledger:

```sh
python3 scripts/export_report.py --run artifacts/experiment-RUN_ID --output artifacts/handoff-report
```

Replace `RUN_ID`; it is not a literal directory name. Export only after the run has stopped and final accounting/cleanup exist. Running the exporter again into a second new directory must produce byte-identical `report.json` and `REPORT.md`. Report generation never changes scores. Missing model accounting remains unknown, not zero. The selected exporter copies only validated categories, booleans, nonnegative counters and hashes; it excludes raw provider content, tool arguments, credentials and free-text errors. Publish only reviewed selected reports, never whole raw artifact directories.

## Repeat agent experiments deliberately

The suite runner accepts one or more explicit manifests, validates them all before execution, records source hashes, and stops if executable source changes between phases. Existing per-experiment immutable snapshots and trial accounting remain in force.

```sh
PYTHONPATH=src .venv/bin/python scripts/run_evaluation.py \
  scenarios/reliability-development.yaml scenarios/reliability-regressions.yaml \
  scenarios/reliability-validation.yaml
```

This plans 38 trials. Add `--execute --env-file ~/Dev/.env` only when deliberately starting a new paid experiment. Gemini uses `gemini-3.8-flash`. Reconciliation conditions are similarly specified by its development and validation manifests (24 trials). **Running an old manifest on the current release tests the current code under those conditions.** It does not reproduce the old candidate's source or turn known cases into unseen data. Historical source commits and limitations are in each experiment report; checkout that exact commit for historical source reproduction. Provider outputs and availability are not deterministic.

## Ten-minute discussion walkthrough

Use a completed demo's report if provisioning would consume the discussion time. Spend two minutes on the reasoning/authority/verification boundary, four minutes on the [three trajectories](TRAJECTORIES.md), two minutes on the [findings and null results](FINDINGS.md), and two minutes on what evidence would justify a new scope of authority. The source, manifest, report and original failure should be available together. This is a research demonstration, not an assertion that every agent incident completes.
