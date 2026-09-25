# Missing evidence stays missing after restart and termination

The [declared lifecycle protocol](LIFECYCLE_EXPERIMENT.md) now passes its telemetry
case on GCP and CI, and both campaign-owner termination cases on GCP. Two original
owner attempts failed before the intended termination boundary; their evidence
remains failed and retained. A minimal audit-log ownership fix passed new owner
attempts without changing the protocol, deadlines or pass criteria.

These deterministic campaigns use real Kubernetes, HTTP/database observations,
OS signals and API-server audit. No model operates these cases. Gate success is
separate from service health, certainty about an operation and measurement coverage.

## Missing collection and unavailable reconciliation

Executable source `6d09d1542c34781f36239d1c5956ce9a85c8d58a` ran the same declared
210-second case on GCP (`telemetry-gate-0b7a9cbe`) and GitHub Actions
(`telemetry-gate-07a1fda7`). The original observer was actually stopped at 25 seconds
and resumed at 65. Missing slots 3-6 remained absent and unknown. Healthy operator
claims did not replace independent evidence.

| Measurement | GCP | CI |
|---|---:|---:|
| Healthy / failed / unknown slots | 15 / 2 / 4 | 15 / 2 / 4 |
| Healthy operator claims during the collection gap | 6 | 7 |
| Quote corpus responses / HTTP 503s | 204 / 20 | 204 / 20 |
| Healthy independent slots after final operator restart | 8 | 8 |
| Unchanged workload UIDs | 11 | 11 |
| Broker repairs / reserved dispatches / limit | 1 / 1 / 2 | 1 / 1 / 2 |

The corpus includes intentional negative requests; expected 404/422 responses are
not classified as injected service failures. The 20 HTTP 503s accompany the real
routing fault. After a real broker repair completed, the repair operator was
killed before acknowledgement. The controller revoked only broker Service `get`
permission, retaining scoped `patch`. A later real GET received API-server 403.

The replacement recorded reconciliation as unavailable, attribution not established
and recovery not verified. It escalated without a new episode or write. Independent
measurement still observed a healthy service. All three successful Service/Role
mutations were accounted for: fault, repair and permission change. Dependent
controller updates are outside these resource counts. Both normal cleanup and
byte-identical export checks passed.

## Retained failures exposed an audit ownership defect

At the same original source, both owner attempts missed the required post-response,
pre-acknowledgement barrier. The privileged injector created `api-mutations.jsonl`
first, owned by root with mode 0600. The unprivileged operator could not append its
dispatch audit record. No broker repair reached the API server; the broker retained
an uncertain operation and escalated. Opening the file for append as the actual
operator user reproduced `PermissionError` without writing bytes.

| Original failed attempt | Root receipt | Healthy / failed / unknown slots |
|---|---|---:|
| Restart protocol | `service-gate-cc28a6cd` | 3 / 4 / 5 |
| SIGKILL protocol | `service-gate-06c11d3c` | 3 / 4 / 5 |

These attempts did not execute the intended termination challenge. The controller's
final stop invoked post-stop cleanup and removed the owned resources, but that does
not convert either attempt to a pass. Both original journals and timelines remain
unchanged, including their unavailable future measurements.

Source `8d61d7c3ac3e09d7dba4dec9dcaf93cc856a6684` precreates the empty private log
as the campaign owner before provisioning or external writes. The adapter appends
without replacing it. There is no permission broadening, deadline change or
relaxed assertion. The fixed source uses a separate study checkout and new job
identities. Its ownership regression and existing suite pass 985 tests and lint.

## Recovery after the original cleanup processes die

Both corrected owner cases passed. Before termination, the owner, operator,
observer and original janitor were four live processes in the same systemd control
group. A real conditional broker repair reached the declared interruption barrier.
All four original process identities were absent after unit restart or whole-group
SIGKILL. A fresh supervisor post-stop process performed accounting and cleanup.

| Corrected case | Root receipt | Healthy / failed / unknown slots | Cleanup from stop request |
|---|---|---:|---:|
| Restart | `service-gate-d775edf5` | 3 / 1 / 8 | 2.07 seconds |
| SIGKILL | `service-gate-b17ae41b` | 3 / 1 / 8 | 2.09 seconds |

Restart refused another invocation through the exclusive launch claim. Both
immutable post-stop receipts retain the original systemd invocation. Each case
preserved its four committed sample hashes and all twelve scheduled slots; future
slots 4-11 remain unknown. The owner remains unfinished. The real repair remains
`dispatching`, without acknowledgement or reconciliation, and the interrupted
episode remains uncommitted. Cleanup did not invent completion.

Each case accounted for exactly two successful Service mutations: fault injection
and broker repair. All eleven workload UIDs persisted through the interruption
boundary. Protected rows and fields passed at observed points. No owned containers
remained after cleanup. These gates require the host, storage, Docker and systemd
to survive; they do not establish host/power-loss recovery.

## Evidence and review

The [results ledger](validation/lifecycle-results.json) retains all five GCP
attempts and the original CI telemetry case, including source identities and
separate outcomes. Published GCP artifacts are:

- Telemetry: [scorecard](validation/lifecycle-telemetry-scorecard.json) and
  [evaluation](validation/lifecycle-telemetry-evaluation.json).
- Corrected restart: [scorecard](validation/lifecycle-restart-scorecard.json) and
  [evaluation](validation/lifecycle-restart-evaluation.json).
- Corrected SIGKILL: [scorecard](validation/lifecycle-kill-scorecard.json) and
  [evaluation](validation/lifecycle-kill-evaluation.json).
- Original failed [restart scorecard](validation/lifecycle-original-restart-scorecard.json)
  and [SIGKILL scorecard](validation/lifecycle-original-kill-scorecard.json).
  Their termination evaluations were never reached; the ledger retains that absence.

All 281 tracked files matched before and after each frozen GCP cohort. All 39
transferred raw sample hashes match. Every GCP scorecard reconstructs byte for byte;
all three completed gate evaluations also reconstruct byte for byte. The original
failed owner attempts have reproducible post-stop accounting, not completed gate
evaluations. CI's downloaded scorecards and export hashes match, but raw CI samples
were not uploaded and were not independently rechecked after transfer.

The matching private archive SHA-256 is
`7fb7ba76010ae9929fce2ad95750b6978a019b780821b1dfc64e57264e62c512`.
Raw artifacts and credentials remain private. These author-controlled hashes check
integrity and provenance, not a malicious host. The isolated study did not replace
the installed v0.1.1 release. No containers remained before shutdown; the VM was
confirmed terminated.

Fable completed four focused [source reviews](validation/lifecycle-reviews.json).
The first three produced audit-shape and receipt-capture fixes before execution.
The ownership-fix review raised path/test-scope questions; actual source paths,
append behavior and the real privileged/unprivileged reruns resolve them. Review
snapshots and dispositions distinguish reviewed source from later fixes. Fable
review is additional engineering input, not evidence authentication. A separate
[claims review and evidence followup](validation/lifecycle-report-reviews.json)
reconciled reported counts and reconstruction statements. Its provenance question
led to explicit per-artifact identity fields in the ledger; no outcome changed.

The original source passed 984 tests/lint and all six
[CI jobs](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36072604868).
The ownership correction passed 985 tests/lint locally and on GCP; its separate
[CI run](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36073757275) passed all six jobs,
including the real telemetry case and prior integration gates. Its separately
retained telemetry confirmation again recorded 15 healthy, 2 failed and 4 unknown
slots. It is not pooled into the original matched-source GCP/CI table.

## Decision and remaining proof

Missing collection, denied reconciliation and supervised owner cleanup now have
real bounded gates. Service health, action certainty and observation coverage
remain separate. This closes those slices of the
[continuous ownership plan](CONTINUOUS_OWNERSHIP_PLAN.md), not the complete
continuously evolving operator objective.

Next demonstrate a versioned procedure with independent regression and sealed
lookalike gates, explicit promotion, limited rollout and withdrawal with work in
flight. Then compare competent maintained automation, a frozen model-assisted
operator and gated evolving procedures under matched authority and schedules.
Measure customer impact, actual human active time and full operating/evaluation
cost. Actual stale-proposal API rejection, production reliability, learned benefit,
human-work savings and ROI remain unproven by these persistent campaigns.

## Pre-merge cleanup followup

A subsequent self-review found that reading the operation database or hashing
samples could fail before the accounting handler and skip cleanup. The correction
keeps ownership validation first, moves these fallible reads into accounting, and
still attempts scoped cleanup if they fail. An unavailable baseline remains
unassessed and is distinguished from a detected integrity mismatch. Two authored
regressions use real malformed SQLite bytes and an unreadable sample path, with
cleanup mocked; the suite passes 987 tests and lint. This new failure branch was
not run against a live cluster. Prior GCP attempts retain their original source
identities and outcomes. [Fable review and dispositions](validation/lifecycle-cleanup-read-review.json)
record the additional check.
