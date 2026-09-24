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

The credential loader reads only its accepted key assignments and never evaluates shell expressions. It treats unquoted `#` as a comment: quote the entire value if it contains `#`. It is a restricted data parser, not a complete shell or dotenv interpreter. The default `~/Dev/.env` path is expanded by the existing credential/runtime helpers.

## Ten-minute discussion walkthrough

Use a completed demo's report if provisioning would consume the discussion time. Spend two minutes on the reasoning/authority/verification boundary, four minutes on the [three trajectories](TRAJECTORIES.md), two minutes on the [findings and null results](FINDINGS.md), and two minutes on what evidence would justify a new scope of authority. The source, manifest, report and original failure should be available together. This is a research demonstration, not an assertion that every agent incident completes.

## Reproduce the agent-value comparison

The later [48-trial comparison](AGENT_VALUE_RESULTS.md) is available on the repository's main branch after PR #4, not in the v0.1.1 tag used above. Its runtime was frozen at `5c14303ef54bc46a0fb56616bbaa5e46868d0296`; its reviewed exporter is from `17472e2d2f6b327998a55ababfec1722d74df923`. Neither the installed v0.1.1 release nor earlier study results were replaced.

From a checkout containing the completed comparison, regenerate its measurement table offline using only the committed selected evidence:

```sh
python3 - <<'PY'
import json
import sys
from pathlib import Path
sys.path.insert(0, "scripts")
from report_agent_value import render
report = json.loads(Path("docs/validation/agent-value-comparison.json").read_text())
assert render(report) == Path("docs/AGENT_VALUE_MEASUREMENTS.md").read_text()
print("Published measurements reproduce exactly from selected evidence.")
PY
```

Expect runbook **10/12**, basic **12/12**, structured **12/12**, and 12 unscored controls. All 48 trials have assessed scoped audits. This verifies table regeneration; it does not rerun or independently authenticate the original experiment. The [receipt](validation/agent-value-comparison-receipt.json) includes original evidence hashes, source hashes, provider accounting, pre-run CI/review references and cleanup status.

An operator with the retained private raw evidence can regenerate the selected JSON and Markdown using the reviewed exporter:

```sh
python3 scripts/report_agent_value.py --run /path/to/experiment-f3cd10f4 --output artifacts/agent-value-report
```

Replace the example input path with the actual retained experiment directory; the output must be new. The local archive is under ignored `.state/value-comparison/`, and the second copy is on the stopped GCP host disk at the location in the receipt. Do not publish whole raw directories: they contain private provider content and runtime credentials/configuration. The selected exporter excludes those fields.

A fresh live repetition requires the exact runtime commit, `scenarios/agent-value.yaml`, the [declared gates, budgets and outer timeout](AGENT_VALUE_EXPERIMENT.md), and a deliberately authorized model credential. Plan it with `PYTHONPATH=src .venv/bin/python scripts/run_evaluation.py scenarios/agent-value.yaml` before adding execution flags. Retain it under a new run identifier and denominator. Provider responses are nondeterministic; it cannot replace the recorded 48 trials or validate an altered baseline without a new declaration.

## Reproduce the interrupted fallback comparison

The [80-trial follow-up](RUNBOOK_FALLBACK_RESULTS.md) used runtime `cbddb2503191da285bcfc7c88496ef712ce046a0`. A service stop interrupted trial 80 before final accounting. Its raw archive has 79 finalized results and one unfinished worker record; it is not a controller-finalized 80-trial success. The recovery exporter was added afterward and does not change the frozen runtime or scoring.

Regenerate the committed table from selected evidence:

```sh
python3 - <<'PY'
import json
import sys
from pathlib import Path
sys.path.insert(0, "scripts")
from report_agent_value import render
report = json.loads(Path("docs/validation/runbook-fallback-comparison.json").read_text())
assert report["planned"] == report["recorded"] == 80
assert report["recovery"]["controller_finalized_trials"] == 79
assert report["trials"][-1]["status"] == "interrupted"
assert report["trials"][-1]["task_success"] is None
assert render(report) == Path("docs/RUNBOOK_FALLBACK_MEASUREMENTS.md").read_text()
print("Recovered measurements reproduce, including the interrupted unknown.")
PY
```

Expect original runbook **14/16**, fallback **15/16 with one unassessed**, basic **15/16**, structured **16/16**, and 16 unscored controls. There are 79 assessed audits; the last trial's outcome, duration, final verification and audit remain unknown. The fallback's promotion gate is unmet. Known model usage is 529,412 tokens across 144 requests and retained responses.

An operator with the private archive should first verify its SHA-256 against the [execution receipt](validation/runbook-fallback-comparison-receipt.json), then extract it into a private directory. Use the recovery exporter instead of supplying invented final accounting to the ordinary exporter:

```sh
python3 scripts/recover_interrupted_report.py \
  --run /private-evidence/checkout/artifacts/experiment-04cabcfa \
  --service-journal /private-evidence/interruption-service-journal.jsonl \
  --cleanup-receipt docs/validation/runbook-fallback-cleanup.json \
  --unit autolab-fallback-cbddb25.service \
  --output artifacts/fallback-recovered-report
```

Replace the example private paths with the actual extraction location; the output must be new. Run twice into separate directories and compare `report.json` and `REPORT.md` byte-for-byte with each other and the committed selected artifacts. Original raw `trial.json` files stay untouched, including trial 80's `running` status. The report explicitly separates operator-classified interruption, original evidence hashes, derived accounting hashes and manual cleanup. Worker records normally lack repetition; the report identifies the ordered manifest position as its source and rejects any conflicting supplied repetition.

The source review and [recovery-review ledger](validation/runbook-fallback-recovery-review.json) cover the exporter, not independent authentication of supplied logs or cleanup receipts. Raw archives contain private model content and runtime configuration and must not be published wholesale. The separate 16 model-free gates do not complete the interrupted comparison. Before another live study, validate maintenance-safe termination, final accounting and independently surviving cleanup; any new study requires its own declaration and denominator, with no replacement of trial 80.
