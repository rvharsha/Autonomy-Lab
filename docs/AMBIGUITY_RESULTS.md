# An uncertain operation survives its operator

On 24 September 2026, both cases of the [preregistered ambiguity gate](AMBIGUITY_EXPERIMENT.md)
passed on GCP and in GitHub Actions using executable candidate
`4a252d0097ec43a6cc026f31f5df4eeecd7648ae`. A real broker repair completed, then the
operator was killed before recording acknowledgement. Its replacement reconciled
current state and escalated without dispatching again, despite remaining budget.

In the second case, an external administrator changed routing during operator
downtime. The replacement recorded the changed version and port and left that
change intact. Independent measurements continued to report the resulting service
failure. This distinguishes a safe control decision from successful recovery.

## What actually ran

Each case owns a separate 150-second workload and 15-slot observation calendar.
Within a case, one Quote/Inventory/PostgreSQL workload, one observer and one journal
persist across three operator generations. The initial operator stops before a
declared routing injection. A second operator repairs it and is killed at the
post-response/pre-acknowledgement barrier. A third reconciles and escalates.
These are deterministic runbook campaigns, with no model calls during operation.

| Measurement, on both GCP and CI | Routing unchanged | External routing change |
|---|---:|---:|
| Assessed observation slots | 15/15 | 15/15 |
| Healthy / failed / unknown slots | 13 / 2 / 0 | 4 / 11 / 0 |
| Quote corpus responses / HTTP 503s | 180 / 20 | 180 / 110 |
| Broker repairs / reserved dispatches | 1 / 1 | 1 / 1 |
| Campaign dispatch limit | 2 | 2 |
| Successful Service writes | Injection + repair | Injection + repair + external change |
| Unchanged workload resource UIDs | 11/11 | 11/11 |
| Complete samples during killed operator's absence | 3 | 3 |
| Reconciliation observation | Desired state observed | Desired state not observed |
| Operator's final action | Escalate, no new write | Escalate, no new write |
| Independent service state after restart | Healthy in all later slots | Failed in all later slots |

Both cases retain the one operation as `uncertain`, with one reserved dispatch
and no acknowledged result. Its journal events are prepared, dispatching and
reconciled. The killed episode remains uncommitted. The replacement creates no
new episode and exits normally after recording `unresolved_prior_operations`.

The independent API-server audit establishes the actual effect; the operator
does not read that privileged evidence and does not infer causation from current
state. It retains `attribution: not_established` and `recovery: not_verified`.
The external controller uses its own audit identity and a conditional patch.
Every successful Service mutation is accounted for, with no duplicate repair.
Protected rows and other Service fields pass their independent checks at all
measurement points. Normal cleanup and duplicate-export checks pass for each case.

## Evidence, review and reproduction

The [results ledger](validation/ambiguity-results.json) records all four original
case executions, source and protocol hashes, measured timelines, audit counts and
cleanup receipts. These are integration confirmations, not independent comparison
arms or a statistical reliability study. Published GCP artifacts include:

- Unchanged routing: [scorecard](validation/ambiguity-unchanged-scorecard.json)
  and [evaluation](validation/ambiguity-unchanged-evaluation.json).
- External change: [scorecard](validation/ambiguity-external_change-scorecard.json)
  and [evaluation](validation/ambiguity-external_change-evaluation.json).

All 265 tracked GCP source files matched before and after execution. The source
archive SHA-256 is
`dbdfd7a2c685592855640d3d6eb05e9785649d7d69b8e3305c28bd669433f36a`.
All 30 transferred raw GCP sample hashes match. Both scorecards and evaluations
reconstruct byte for byte from the retained evidence. CI and GCP runtime, fixture
and protocol hashes match; CI's raw samples were not uploaded, so those hashes
were not independently rechecked after transfer.

The private evidence archive's matching cloud/local SHA-256 is
`21b85089c15afeac4d662c25a3ce3f4c9c762f4a200f55730069ebc95daf88df`.
Credentials and detailed raw cluster artifacts remain private. These are
author-controlled provenance receipts, not protection against a malicious host.
No containers remained before shutdown; the GCP VM was confirmed terminated.
The installed v0.1.1 release was not replaced by this isolated study.

Fable's two focused [source reviews](validation/ambiguity-reviews.json) led to
fixes for missing-barrier and incomplete-controller failure assessments. Other
findings have source-grounded dispositions. The follow-up fixes were self-reviewed
and tested, not represented as provider approval. Candidate `4a252d0` passed
**920 tests and lint** on GCP and all five
[CI jobs](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36066104338), including
the existing healthy restart, recurrence and Kubernetes acceptance regressions.

A post-execution self-review corrected one summary field for failed attempts:
`service_recovered` now comes from independent post-restart observations, with
unknown coverage reported as null, rather than from the expected case outcome.
Two authored regressions cover this reporting correction. It changes no pass
criteria or operator behavior. Both completed GCP exports remain byte-identical
under the corrected scorer; the ledger records both scorer hashes. Subsequent PR
checks validate the final source separately from this frozen execution cohort.

## What this changes and what remains

Restart is now tested against a real unrecorded effect on a persistent workload.
It does not grant new authority or turn a later healthy observation into a
confirmed action outcome. When another actor changes the resource, this operator
preserves the unresolved operation and asks for intervention rather than
overwriting that change. The failed service remains visible in the evidence.

This closes the ambiguous-effect and external-change refusal slice of the
[continuous ownership plan](CONTINUOUS_OWNERSHIP_PLAN.md). It does not test an
actual stale proposal being dispatched and rejected by Kubernetes. The trusted
hook pauses after a completed response; it does not create a real network
partition. The environment is kind on a GCP VM, not production GKE, and the
operator/controller share a trusted host.

Next, test missing telemetry and supervised campaign-owner termination. Then
demonstrate one versioned procedure passing independent regression and sealed
counterexample gates, limited rollout and withdrawal. Compare any improvement
against competent fixed automation before claiming model value or evolving
operation. Production reliability, learning, human-work savings and ROI remain
unproven.
