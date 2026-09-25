# Procedure withdrawal during persistent work

This protocol tests whether evaluated admission actually controls the persistent
operator. The candidates remain known deterministic runbooks. It does not test
generated improvements, model advantage or production reliability.

## Freeze and admission

Run `PYTHONPATH=src .venv/bin/python scripts/check_withdrawal.py --execute`.
The gate first executes all 24 trials in the [calibration protocol](PROCEDURE_ADMISSION.md)
on the integration source. A source change invalidates earlier evidence. Then
freeze both canary declarations, checker/scorer hashes and campaign contracts
before either workload is provisioned. Both independent cases run once; retain
failed cases and unrun cases if calibration fails. Do not retry a failed identity.

An opt-in contract names `admitted_procedure`; its owner must receive a complete
calibration directory. Before provisioning, the owner reproduces the evidence
and promotes that procedure in a new campaign-local SQLite registry. The fixed
runbook mode remains available for the earlier lifecycle experiments.

Each operator first reconciles unresolved broker work. It then uses
`Registry.start_episode` to select a procedure once for a new episode. The
transaction checks active admission and current source, pins the activating
revision, and returns the executable variant. The operator records this before
constructing its tools and dispatches that variant. Reusing any pinned episode
identity for execution is refused, including after withdrawal or restart.
`Registry.pin` reserves or reads a diagnostic binding without starting execution;
such an identity cannot subsequently be passed to `start_episode`. Live operators
use only `start_episode` for fresh work. Additional diagnostic pins would fail
the canary's exact ledger-to-executed-episode comparison.

Before every real API write, the operator durably records the original operation
ID and episode/version/revision binding. Broker conditional-write checks,
cumulative budget and uncertainty remain authoritative. Withdrawal atomically
closes fresh episode starts. It deliberately lets an already running bounded
episode finish; it does not cancel an in-flight request. A restart can reconcile
that request, but cannot execute the old pin again or replay the write.

## Case 1: healthy episode withdrawal

One workload, observer and operator remain under a 120-second owner window with
12 scheduled measurements. A trusted hook holds the first episode after its
observations, before recording its terminal claim. By 15 seconds it must have a
durable procedure pin and reach the barrier. At 20 seconds, withdraw its version
and release that exact episode. It must finish healthy under its original pin.
Within 15 seconds of release the next episode must be refused specifically for
missing admission, without using tools. Require a durable refusal, zero broker
operations, zero Service mutation attempts, unchanged resource UIDs, all 12 raw
measurements reproduced as healthy, a completed owner window and cleanup.

This case isolates withdrawal from the unresolved-operation guard: there is no
pending mutation that could independently explain the stop.

## Case 2: withdrawal after a real effect, before acknowledgement

Use the existing [ambiguity protocol](AMBIGUITY_EXPERIMENT.md)'s unchanged-state
case: one 150-second workload, 15 scheduled measurements, a routing fault at
25 seconds, repair worker at 45 seconds, and a barrier after a successful real
API write but before durable acknowledgement. Withdraw the pinned version at
that barrier, then terminate only the operator within the original 3-second
barrier deadline. Restart 30 seconds after termination. Preserve the original
operation ID, episode pin, spent budget and uncertain outcome. Require one
independently attributed broker write, remaining budget, reconciliation followed
by escalation within 15 seconds, no new episode or replay, unchanged UIDs,
independent measurements during downtime and after restart, and cleanup.

The initial healthy worker, repair worker and restarted worker share one broker
journal and admission ledger. The final worker stops for unresolved work before
attempting admission. This case demonstrates compatibility with uncertainty;
the healthy case separately establishes withdrawal's causal effect.

## Evidence and limits

The offline evaluator rechecks calibration receipts, final admission decisions,
all pins, operation bindings, raw verifier probes and independent API evidence.
It reproduces scorecards and evaluations twice byte for byte. Retain credential-free
raw measurements, episode observations, both SQLite journals, declarations,
source hashes, lifecycle receipts and scoped API audit evidence. CI uploads an
explicit allowlist; credentials and general worker logs are excluded.

Authored unit counterexamples are validation of the gate, not live results.
Controller, process account, evaluator storage and clock remain trusted. Hashes
detect source drift, not malicious evidence forgery. Current-state reconciliation
cannot establish actor attribution; the independent API audit supplies that
separate evidence. Sampled health does not imply continuous availability.

After this boundary passes, the next experiment needs a genuinely new candidate,
separately sealed counterexamples, and a maintained automation baseline. Success
here proves that evaluation can govern execution, not that the system learns.
