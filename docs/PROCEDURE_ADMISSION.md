# Evaluation-controlled procedure admission: calibration protocol

This is the first control-path slice of the [continuous ownership plan](CONTINUOUS_OWNERSHIP_PLAN.md).
The two candidates are the existing `runbook` and `runbook_fallback`, with no
generated code or new model behavior. These are known calibration controls. The
fallback is already the persistent operator's default; selecting it here is not
a newly learned improvement or an advantage over maintained automation.

## Frozen experiment

Before provisioning, `scripts/check_procedures.py --execute` records source hashes
and the fixed protocol in `procedures.calibration_config()`. Run one repetition
of eight scenarios for each of the original runbook, fallback and no-action
control: routing, healthy workload, lost acknowledgement, backend observation
outage, and observation outages combined with routing, quote semantics, verifier
measurements, or quote semantics plus verifier measurements. Use 30-second
verification windows and a fixed randomized variant order: 24 real trials.
The isolated experiment runner resets the application between trials. This is
evaluation, not a continuous-service or unseen-holdout experiment.

Admission requires the exact complete plan, recorded results, completed cleanup,
matching worker/release identities, current source hashes, reproduced raw verifier
probe assessments, scores and API audit assessments, no damage to protected data
or unrelated configuration, no unmatched successful writes, and the declared
environment outcome for every trial. The deliberately injected Inventory routing
fault may remain when no action or escalation is expected: its failure reason
stays in the raw verification and must never accompany a healthy verdict.
Missing/unknown/corrupt evidence
cannot authorize promotion. Every selected procedure must pass all eight cases.
The original runbook is expected to fail only the healthy-backend-observation
outage case; the fallback is expected to pass all eight. Retain mismatches and
failed attempts rather than narrowing the gates or retrying away failures.

## Admission and withdrawal boundary

The controller calls `Registry.promote` with a trusted raw evaluation directory
and an expected ledger revision. The registry computes the receipt itself; a
caller-supplied success boolean cannot authorize a version. A version binds the
procedure choice, source dependencies, evaluated image/release and calibration protocol. SQLite commits
the decision, active version and revision together. Failed behavioral candidates
remain recorded and cannot replace the active version. Stale administrative
decisions are refused. Each activation retains its own complete evidence receipt
in the decision ledger. Pins name the activating revision, even if a subsequent
candidate is rejected; a re-promotion cannot relabel earlier pins.

`Registry.pin` binds an episode identity to an admitted version. A repeat lookup
returns that same binding. Withdrawal atomically closes new admission and is
terminal for the version in that registry; existing bindings remain historical
facts. Reopening the registry preserves both the withdrawal and old bindings.
A pin is not broker authority, execution permission, or permission to replay a
write. New pins also refuse source drift. Existing pin lookup deliberately does
not execute or validate executable code.

This ledger is **not yet consumed by the persistent campaign**. The live checker
uses real evaluation receipts but exercises the ledger with a calibration pin;
it does not demonstrate withdrawal during an actual dispatched operation. No
production service consumes these admissions. Controller, evaluator and host
storage are trusted. Hashes detect changes against the checkout; they do not
authenticate hostile, self-authored artifacts. The proposer has no API in this
slice, and cannot edit verifier, broker, pass criteria or supported procedures.

## Validation and next boundary

Authored unit fixtures challenge missing evidence, score/audit disagreement,
protocol/source drift, stale and concurrent decisions, persistent withdrawal,
and unchanged historical pins. These fixtures are not experiment outcomes.
The live calibration must separately establish the expected rejection and
acceptance from real Kubernetes, application, database and API audit evidence.

Next, integrate admission into the persistent operator with a frozen canary
contract. Pin the version before each episode, preserve that binding and the
existing broker operation ID/budget through interruption, and withdraw during
an actual unresolved operation. Require independent workload measurements,
unchanged resource UIDs, no replay and no post-withdrawal admissions. Only after
that boundary passes should a proposer attempt a new improvement against
separately frozen counterexamples and a competent maintained baseline.
