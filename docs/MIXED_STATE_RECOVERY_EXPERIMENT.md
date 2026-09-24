# Mixed-state service recovery gate

Prospective declaration, 24 September 2026 UTC. This is a follow-up to the
[service-recovery experiment](SERVICE_RECOVERY_EXPERIMENT.md), not a replacement
for any historical result. It closes the report's missing real termination case
with both committed and uncommitted work. It does not establish persistent
workload ownership or host/power-loss recovery.

## Frozen procedure and pass criteria

Run `scripts/check_service_stop.py MODE --committed-prefix` separately for
`stop`, `restart` and `kill` on the existing authorized GCP lab host. Freeze the
reviewed source commit, archive hash, manifest and checker before execution.
The model-free manifest declares four ordered trials: healthy, routing, healthy,
routing; one fallback actor, two repetitions, unchanged 30-second verification
windows and 900-second trial timeouts. No model credential or generation call
is used. Trial resets remain in effect: this is an evaluator lifecycle gate.

1. Require the controller to commit trial 1 as successful with an assessed audit,
   zero unmatched successful mutations and no protected-state damage.
2. Wait for a real acknowledged repair in still-running trial 2. Before stopping,
   hash the committed `results.json` and trial-1 result files; capture controller
   and janitor identities and their shared service control group.
3. Trigger the named lifecycle action. `kill` sends SIGKILL to the entire original
   control group. `restart` must refuse a new experiment under its existing claim.
4. Require supervised post-stop cleanup with no remaining owned resources and
   termination of the original janitor. Sidecar accounting must contain exactly
   **four planned, one committed, two attempted, one unassessed and two unrun**.
   Preserve the committed trial's success and audit; interrupted and unrun trials
   must have null success and audit assessments, even if a worker wrote success.
5. Require the pre-stop committed-result hashes, post-stop original-evidence
   hashes and durable launch claim to remain unchanged. Any missing receipt,
   unexpected result, missed trigger, incomplete cleanup or hash mismatch fails
   the gate. A lifecycle pass is not a completed repair trial.

Each service has a 30-minute runtime bound, a 15-minute readiness deadline, and
separate 5-minute process-stop and post-stop limits. If the harness observes the
boundary too late, keep the failed attempt; do not relabel or silently replace it.
The gate's finalizer stops its own service even on assertion failure. Retain each
gate receipt and journal, copy private evidence back with matching hashes, check
owned-resource cleanup and stop the VM after the campaign.

Before cloud execution require source tests/lint, additional Fable source review
with checked dispositions, and real Kubernetes acceptance plus model-free handoff
checks on the source candidate. No runtime, policy, agent, broker, verifier or
scoring changes are proposed here. The original zero-committed gates remain
available through the command without `--committed-prefix`.

## Interpretation

All three gates must pass before claiming that real service termination preserves
a completed result prefix while retaining subsequent uncertainty. One run per
termination mode tests these specific boundaries; it is not a reliability rate.
The host, systemd, Docker and storage remain trusted and available. These results
must remain separate from the original 48-, 80- and 32-trial cohorts.
