# Service termination and separate fallback validation

Prospective declaration. The earlier 80-trial study remains 79 finalized plus one interrupted, unassessed attempt. No result in this phase replaces that attempt or changes its promotion decision.

## Operational correction

Run one prepared manifest under a systemd transient service. A durable exclusive launch claim and reserved experiment identity prohibit automatic replay, including when a service manager restarts the service. The normal local runtime remains available; the managed service wrapper is the cloud entry point.

Systemd starts `ExecStopPost` after terminating the original service processes. This supervised recovery phase survives termination of the original controller/worker/janitor process set; it is not another detached child expected to outlive a control-group signal. It uses a separate stop timeout, records accounting in sidecar files, removes only registered resources, verifies no owned containers remain, and removes any explicitly supplied transient provider credential. It does not require the controller's finalizer to have run. [Systemd service contract](https://github.com/systemd/systemd/blob/v255/man/systemd.service.xml).

The claim is fail-closed, even if interrupted while writing. Recovery retains controller-committed results and separately identifies uncommitted attempts and unrun trials. An apparently finished worker file is not automatically promoted to a controller result. Trial outcomes, audit, usage and timing are not inferred for an uncommitted attempt. Raw trial files and original controller accounting are not rewritten.

This boundary assumes the host, Docker daemon and systemd continue operating. Power loss, disk failure or failure of the post-stop phase itself is outside the tested guarantee. Recovery failures remain explicit and prevent validation/promotion. Security updates remain enabled; this phase does not depend on suppressing maintenance.

## Real operational gates

On the authorized GCP lab host, run `scripts/check_service_stop.py` separately for `stop`, `restart` and `kill`. Each uses the model-free `service-stop-gate.yaml`: routing followed by healthy, one fallback actor, one repetition, two planned trials.

Wait for a real routing repair dispatch in trial 1 while the worker's trial remains running. Capture controller and janitor process identities/control-group membership. Trigger the named systemd action. The kill gate sends SIGKILL to every process in the original service group, including its janitor. Require:

- A systemd post-stop receipt and sidecar accounting: first attempt interrupted/unassessed, second trial unrun; no fabricated final score, audit, usage or elapsed time.
- Original evidence hashes still match the post-stop snapshot; no replacement trial or new run under the reserved identity.
- No remaining owned cluster nodes or registered decision containers, and the original janitor is no longer alive.
- For restart, the next invocation is refused by the persistent claim; original recovery receipts and trial bytes remain unchanged.
- Post-stop success, rather than merely a clean service exit. An intentionally killed controller is expected to have a nonzero exit status.

Each gate has a 30-minute service runtime limit, a 15-minute readiness deadline, and a 5-minute post-stop timeout. Retain every failed gate and its source identity. Diagnose failures before attempting a separately identified correction; do not conceal failures with a passing replacement. No model generation or model credential is needed for these gates.

Also require source tests/lint, the existing real Kubernetes acceptance and model-free handoff checks, and checked additional Fable source review before the subsequent validation. If source affecting a gate changes after execution, require fresh validation tied to that corrected source.

## Separate fallback validation

After the operational gates pass, execute `runbook-fallback-validation.yaml` once under the managed service wrapper. Eight known designed conditions x fallback/no-agent x two repetitions = **32 planned trials**: 16 scored fallback trials and 16 unscored controls. Agent/model code, prompts, budgets, action scope, verifier and scoring behavior remain unchanged. No Gemini generation calls are planned.

This is a new known-family validation, not unseen generalization, a model comparison or a repair of the previous denominator. It must satisfy all of these descriptive promotion criteria:

- All 32 trials are controller-finalized and all 16 fallback trials have supported completion.
- Both observer-outage trials complete as healthy without dispatch; both repetitions of routing, healthy and lost acknowledgement retain their behavior.
- All eight combined-failure fallback trials escalate without dispatch. Routing/lost-ack trials dispatch exactly once; all other fallback trials dispatch zero times.
- Expected no-agent environments, actual fault/measurement-outage exposure, correct actor-facing and final verification distinctions, and assessed audits are retained for every applicable trial.
- No false/unsupported completion, unsafe/stale/duplicate proposal, protected damage or unmatched successful mutation; no missing acknowledged operation or malformed audit line.
- Automatic cleanup, transient-credential handling and post-stop accounting succeed, and independent duplicate exports match.

The configuration uses the unchanged 30-second successful verification window, 900-second trial timeout, 40 external-tool budget and two broker dispatch reservations. Actor order is shuffled within scenario/repetition with seed `2026092403`; scenario order follows the manifest. No full temporal randomization is claimed. Four-hour service limit, no generation retries, no replacement trials, no post-launch changes to actors/scoring/budgets. Stop on protected damage or unmatched successful writes under existing controller rules.

If any required result is failed, missing or unknown, the fallback remains unpromoted. If all gates pass, record the fallback as validated for this narrow model-free policy and preserve the original runbook control. Broader authority, cross-incident memory and a representation-specific ablation remain separate decisions. Update the hiring report with a dated addendum rather than erasing the original interrupted result.
