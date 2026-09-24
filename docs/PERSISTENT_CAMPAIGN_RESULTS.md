# A workload that outlives its operator

On 2026-09-24, the first persistent-service restart gate passed on GCP and in
GitHub Actions using the same frozen candidate,
`42cdd9dd74222a0d95afcc9c99d1d264cc6bad55`. One real Quote/Inventory/PostgreSQL
workload stayed running while its deterministic operator was killed and replaced.
The independent observer continued measuring throughout that interruption.

This closes the first lifecycle gate in the [continuous-ownership plan](CONTINUOUS_OWNERSHIP_PLAN.md).
It establishes a bounded foundation for continuous evaluation. Repeated incident
recovery, owner control-group failure, procedure evolution and production readiness
remain unproven.

## Declared gate and observed results

The [contract and checker](PERSISTENT_CAMPAIGN.md) were fixed before each run:
120 seconds; 12 scheduled measurement slots; stop the operator at offset 30 seconds;
start its replacement at offset 60; maximum observed downtime 45 seconds; at least
two complete observation windows wholly inside the absence; unchanged workload
UIDs; no repair on the healthy workload; concurrent-operator refusal; cleanup;
byte-identical exports. Missing, late and indeterminate samples fail this gate.

| Final candidate result | GCP lab VM | GitHub Actions |
|---|---:|---:|
| Successful scheduled slots | 12/12 | 12/12 |
| Failed / unknown slots | 0 / 0 | 0 / 0 |
| Operator downtime | 30.436 s | 30.532 s |
| Complete observation windows during downtime | 2 | 2 |
| Unchanged workload resource UIDs | 11/11 | 11/11 |
| Quote corpus responses | 144 | 144 |
| Measured maximum request latency | 41.295 ms | 30.986 ms |
| Broker repairs / budget spent | 0 / 0 | 0 / 0 |
| Concurrent operator refused | Yes | Yes |
| Owned cluster cleanup | Passed | Passed |
| Repeated scorecard export | Identical | Identical |

Each verifier window checks real HTTP correctness, independently expected protected
PostgreSQL rows and Inventory Service configuration. The 144 responses include
96 expected HTTP 200s, 24 expected 404s and 24 expected 422s. These negative corpus
cases are correct responses. The two GCP downtime windows contain 24 actual quote
requests. No model generation or provider credentials were used by the campaigns.

The UIDs cover the Namespace, three Services, three Deployments, three Pods and
one database PVC. The campaign does not call the trial reset function. Both operator
generations completed healthy runbook episodes; a separate rejected invocation
never acquired ownership. Operator outcome records remain claims; campaign
measurements come from the observer.

## Evidence and review

[Machine-readable results](validation/persistent-campaign-results.json) retain the
GCP and CI receipts, their source versions and the earlier development executions.
The [final GCP scorecard](validation/persistent-campaign-scorecard.json) includes
the full scheduled timeline, worker attempts, operation accounting, cleanup and
sample hashes. On GCP, all 245 staged source-file hashes matched before and after
execution; the archived source checksum is
`c744e4cf969040a3a9e8be479d096af368cbf908eb5574171028c884c81ec6d5`.
The 12 raw sample hashes and duplicate exports were checked again after transfer.
CI and GCP runtime/fixture hashes match. Raw CI samples were not uploaded.

The private archive contains both real GCP executions, including the earlier
`5b3c986` development candidate; neither has been overwritten or pooled into a
comparison. Its cloud and local SHA-256 matched:
`d40f24e84a94bb32e6390bf344dd3b2bd3d1d02096f76cc6f893cc3e233e5bf3`.
Cluster credentials remain private. No Docker workloads remained before VM shutdown. The VM was confirmed
`TERMINATED` at 20:55 UTC.
These author-produced receipts are not authentication against a malicious host.

Fable's [reviews and dispositions](validation/persistent-campaign-reviews.json)
led to failure-receipt preservation, explicit operator readiness, accounting for
incomplete episode directories, and separation of window completion from successful
owner finalization. The final small report predicate was self-checked after the
model review. Authored tests cover these failure boundaries; they are not substituted
for the real gates. The final GCP source passed **858 tests and lint**. All three
[CI jobs on the same source](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36057264716)
passed, including the existing real Kubernetes acceptance and handoff regressions. The new
persistent-campaign CI job runs the real gate on future PRs.

## Technical and strategic implication

A continuous operator needs a measurement and ownership boundary that survives
its own restart. This experiment now demonstrates that boundary on a real service:
operator absence does not automatically imply a customer outage, and restarting
an operator does not erase the measurement calendar. Correct restraint is also
observable: a healthy service required no repair.

Next, inject recurring routing faults into this same persistent workload, require
recovery within a declared deadline, and prove the dispatch budget remains cumulative
across operator restarts. Then test uncertain effects without duplicate writes,
external changes, observer gaps, exhausted authority and whole-group owner cleanup.
Only after those gates should versioned procedures, holdouts, canary promotion and
rollback become the basis for a sustained comparison of fixed and evolving operators.

This is a two-minute healthy-workload integration test, with one restart per run.
Requests use local port forwards and a small fixed corpus. Latency is descriptive,
not a production SLO. Health between probes, sustained availability, learning gains,
model advantage, human-effort savings and ROI are not established.
