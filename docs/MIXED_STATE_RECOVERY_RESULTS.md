# Recovery after a completed result and a later interruption

Executed 24 September 2026 UTC, under the separate
[prospective declaration](MIXED_STATE_RECOVERY_EXPERIMENT.md). All three real GCP
termination gates passed. They preserve a successful controller-committed result
while keeping a subsequent interrupted attempt unassessed and later work unrun.
This closes the experiment report's missing mixed-state lifecycle case.

## Observed outcomes

Each mode ran its own four-trial plan: healthy, routing, healthy, routing. The
healthy trial committed before the gate interrupted trial 2 after a real routing
repair acknowledgement. The interrupted worker's original `trial.json` still
says `running`; the recovery sidecar accounts for that interruption without
rewriting the worker record or inventing completion.

| Termination mode | Planned | Committed | Interrupted/unassessed | Unrun | Cleanup |
|---|---:|---:|---:|---:|---|
| Ordinary stop | 4 | 1 | 1 | 2 | Passed |
| Service restart | 4 | 1 | 1 | 2 | Passed; replay refused |
| SIGKILL entire original service group | 4 | 1 | 1 | 2 | Passed |

The committed healthy result retained its success and assessed audit. The
interrupted and unrun rows retained null task-success and audit assessments.
Pre-stop hashes of the committed result files, all post-stop evidence hashes
and the launch claim were unchanged. The original controller and janitor shared
the verified control group; the original janitor was no longer alive after
termination. The supervised post-stop phase finished with no owned resources
remaining. No Docker containers remained on the host after the three gates.

The acknowledged routing change is evidence of a dispatched repair, not a
completed second trial or a measured final recovery window. These are three
lifecycle passes, not three new successful agent-repair trials. There was one
execution per declared mode; no failed gate was discarded or replaced.

## Source, validation and review

The evaluated source was [`f905412`](https://github.com/rvharsha/Autonomy-Lab/commit/f905412fa09f4c26e04bad6e4d153579274c4d0b).
Its archive hash is `c8cd1b5cf3db29bf9bfe45aaab3b130fbce919871f015f27306e76112b92a2eb`.
All 234 staged source-file hashes matched before and after execution. All 32
runtime source files (the `src/autonomy_lab` tree and service wrapper) remain
byte-identical to the preceding merged implementation, `74f2520`. This change
adds gate assertions and a manifest; it changes no actor, broker, authority,
verifier, scoring or orchestration behavior.

[Exact-source CI](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36049892892)
passed **824 tests, lint, 17 real Kubernetes acceptance checks and four model-free
handoff trials**, with byte-identical duplicate exports. The downloaded artifacts
were checked locally. The same 824 tests and lint passed on GCP before execution.
The gates used no model generation calls and supplied no provider credential.

Two additional [Fable source reviews](validation/mixed-state-reviews.json)
completed through direct Anthropic. The initial broader token preflight stopped
without a generation request; the narrower reviews retained the existing cost
ceiling. A confirmed finding about privileged evidence-path reads was corrected
with descriptor-relative, symlink-rejecting reads and authored regression tests.
A proposal to accept a different interruption-accounting shape was rejected
after checking the unchanged controller's signal behavior. The declared criteria
were not relaxed. The follow-up found no remaining actionable defect within its
source scope. Review is not execution or independent authentication.

## Retained evidence and limits

- [Selected gate receipts](validation/mixed-state-recovery.json) contain the
  per-mode accounting, process/cleanup checks, timestamps and evidence hashes.
- [CI receipt](validation/mixed-state-ci.json) binds the verified checks and
  downloaded artifact hashes to the source candidate.
- The private evidence archive includes original gate results, service journals,
  job and trial records, source provenance and logs. Its SHA-256 is
  `17bfffbe854713d0a46aa6a2c0a4e5a17054e26a0b6b58eec24d5d4a0f707fc1`.
  The cloud and local copies match; result-file and pre-stop committed hashes
  were also rechecked directly in the local archive. Raw runtime credentials and
  kubeconfigs remain private. Hashes establish integrity, not independent
  authentication of the observations.

The VM was confirmed `TERMINATED` after the archive was copied and checked. Its
installed v0.1.1 release was not replaced.

The earlier 48-, 80- and 32-trial cohorts retain their original outcomes and
denominators. The original interrupted Study B trial remains unknown. The current
gate still resets the application between trials and deletes it after termination.
It assumes the host, storage, Docker and systemd remain available; it does not
test host/power loss or prove production reliability.

The next claim is [continuous service ownership](CONTINUOUS_OWNERSHIP_PLAN.md):
separate the operator from the workload's lifecycle and keep an independent
service scorecard running across operator downtime. Persistent operation and
procedure evolution remain unproven.

### Subsequent source review

A Fable review of the published source/results found that privileged gate receipts
were written beneath a lab-user-writable checkout. New gates now write under
`/var/lib/autonomy-lab/service-gates`, with root-owned, non-user-writable ancestors
and no symlink traversal. The original executed candidate and evidence hashes
above remain unchanged; these historical receipts do not prove authenticity
against a malicious lab user. The separate suggestion that restart overwrites
the first recovery receipt was checked against `finalize`: its exclusive lock
and existing-receipt early return preserve the first receipt. Review and
dispositions are in [the review record](validation/mixed-state-reviews.json).
