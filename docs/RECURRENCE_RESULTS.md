# Recurring faults without renewed authority

On 24 September 2026, the [preregistered recurrence gate](RECURRENCE_EXPERIMENT.md)
passed on the GCP lab VM and in GitHub Actions using the same reviewed candidate,
`c245d3914ec213f8d63a058d9cab272b7e3ae0d0`. One real Quote/Inventory/PostgreSQL workload
survived three operator replacements. Two routing faults were repaired; the third
was refused after the campaign's two-dispatch budget was spent.

The independent observer kept measuring the failed service after escalation.
This proves a bounded separation between operator lifecycle, cumulative authority
and measured service outcomes. It does not demonstrate learning or uninterrupted
service health. The operator is the existing deterministic runbook; no model
generation was used to operate the service in these campaigns.

## Declared contract and observed outcomes

The 300-second calendar contains 30 slots ten seconds apart. The controller stops
the operator before each injection, establishes real client-path failure through
the independent observer, then starts a fresh operator at the frozen offset.
Each response has a 70-second deadline from the fault dispatch request. Every
sample must be assessed; missing, late or indeterminate measurements cannot pass.

| Reviewed candidate | GCP VM | GitHub Actions |
|---|---:|---:|
| Scheduled slots assessed | 30/30 | 30/30 |
| Healthy / failed / unknown slots | 15 / 15 / 0 | 15 / 15 / 0 |
| First independent recovery measurement, incident 1 | 26.177 s | 26.093 s |
| First independent recovery measurement, incident 2 | 26.182 s | 26.107 s |
| Broker repairs / cumulative reserved dispatches | 2 / 2 | 2 / 2 |
| Third incident | Budget rejection and escalation | Budget rejection and escalation |
| Unchanged workload resource UIDs | 11/11 | 11/11 |
| Successful Service writes | 3 injections + 2 repairs | 3 injections + 2 repairs |
| Quote corpus responses / HTTP 503s | 360 / 150 | 360 / 150 |
| Normal cleanup and identical exports | Passed | Passed |

Recovery times end at completion of the first fully healthy independent sample,
not the precise instant routing recovered. They include about 20 seconds of
intentional downtime between injection and restart and the sampling delay. Each
repair is followed by five more healthy measured slots before the next fault.
The third incident has four failed slots after its 70-second response deadline;
correct escalation did not restore the application.

Each run recorded 120 HTTP 200s, 30 expected 404s, 60 expected 422s and 150 HTTP
503s in the quote corpus. Expected negative corpus cases are not correctness
failures. The 15 failed slots remain failed in the published calendar. These
counts describe deliberately scheduled incidents, not a production availability
percentage or representative customer traffic.

Independent checks found no protected database-row or other Service-field damage
at the measurement points. Namespace, three Services, three Deployments, three
Pods and the database PVC kept their original UIDs. API-server audit records
correlated exactly two conditional broker repairs with distinct operation IDs;
all successful Service writes, including controller writes, were accounted for.
Restart neither deleted the operation journal nor replenished its budget.

## Evidence and review

The [results ledger](validation/recurrence-results.json) retains both source
versions: the initial `d2bb758` candidate and reviewed `c245d39` candidate each ran
once on GCP and once in CI. All four recurrence runs passed. They are development
and confirmation runs, not independent experimental arms or a statistical study.
The [final GCP scorecard](validation/recurrence-scorecard.json) preserves the entire
calendar, operation accounting, worker episodes and raw sample hashes; the
[gate evaluation](validation/recurrence-evaluation.json) separates contract success
from service failure.

All 255 final candidate source-file hashes matched before and after GCP
execution. Its source archive SHA-256 is
`e28c6404df3eb9af0909cade21993a036ca2444fd541ef1530b7aee7c24528dc`.
All 30 raw sample hashes per GCP run were verified after transfer. Reconstructing
the scorecards and evaluations locally from retained evidence produced identical
bytes, using the final scorer; the ledger discloses that scorer version for the
earlier run too. CI and GCP runtime/fixture hashes match. Raw CI samples were not
uploaded, so their hashes were not independently rechecked after transfer.

The private GCP evidence archive has matching cloud/local SHA-256:
`7eb970dd7959caf5bbde78c4ea8ddb6106cfdc01c4d84b61dfec28ff2846b0b0`.
Cluster credentials and detailed raw artifacts remain private. These receipts
are author-controlled provenance, not authentication against a malicious host.
No Docker workloads remained before shutdown; the VM was confirmed terminated.

Fable's [source reviews and dispositions](validation/recurrence-reviews.json)
led to explicit missing-worker rejection and consistent audit boundary timestamp
formatting. The original broad review exhausted its output budget without findings;
two focused reviews completed. The two small follow-up predicates were self-reviewed
and tested after those snapshots. The final candidate passed **876 tests and lint**,
and all four [CI jobs](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36061713129) passed, including the existing healthy
restart and real Kubernetes acceptance/handoff regressions.

## What this changes

A replacement operator can repair a recurring incident while inheriting the
campaign's spent authority. The evidence is carried by the persistent broker
journal and independent measurements. A fresh process is not a fresh permission
to mutate. A useful controller must preserve three different outcomes: repair,
measured recovery and correct escalation with an unresolved service failure.

This closes the declared recurrence-and-budget slice of the
[continuous ownership plan](CONTINUOUS_OWNERSHIP_PLAN.md). Next, interrupt a real
write before its acknowledgement, introduce an external change during downtime,
and require reconciliation without duplicate effects. Observer gaps and supervised
owner termination remain separate gates. Then test one versioned procedure through
independent regressions, sealed counterexamples, limited rollout and withdrawal
before comparing evolving operation against a capable fixed baseline.

The workload runs in kind on a GCP VM, not managed GKE or production. Operators
and controller are trusted host code. This gate does not test spontaneous faults
arriving while the operator is already active, new diagnoses, new action families,
untrusted-host isolation or long-term reliability. Model advantage, autonomous
learning, human-work savings and ROI remain unproven.
