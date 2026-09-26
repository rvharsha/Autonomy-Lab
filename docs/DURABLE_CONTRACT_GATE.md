# Durable operation-contract gate

Frozen development gate, 26 September 2026. This connects the PR21 API contract
to durable broker intent. It does not admit a policy, deploy to GCP, establish
model advantage, or measure aggregate customer benefit.

## Contract and trust boundary

The existing resource-version contract remains the default. Only trusted
controller policy may select `service-routing-heartbeat-v1`; the agent proposal
schema must not change. Persist the contract identity in the same transaction as
intent. Migrate existing intents to the legacy contract, never the experimental
one. A missing binding in a current journal must fail closed.

Before the first experimental dispatch, require the trusted API observation to
match the proposal's UID, resourceVersion, namespace, name, named port and action.
The precise contract retains PR21's single-port, 9999-to-8080 scope. Persist that
complete snapshot, bound to operation identity, proposal digest and contract
version, before any dispatch claim. Concurrent resumes must use the first stored
snapshot. Restart cannot refresh, replace or reinterpret it. Recheck the binding,
current contract selection, withdrawal and cumulative budget at the atomic claim.
An unsent refusal releases its reservation; a sent or uncertain request retains
its spent slot. An uncertain operation remains reconciliation-only.

The current-value contract deliberately does not prove absence of intervening
events. An authority value changed away and back may satisfy its final predicate.
Withdrawal is a separate, durable decision and cannot be reversed by that change.
Storage, controller and evaluation code are trusted; hashes detect accidental
drift, not malicious journal replacement.

## Frozen real-cluster matrix

Run each case once with each contract, in this order, on fresh Service identities
within one owned disposable Kubernetes cluster. There is one dispatch slot per
case, no model, and no retry of a sent operation. Retain failures and cleanup.

| Case | Intervention / required result |
|---|---|
| unchanged | Both acknowledge one routing repair. |
| heartbeat | After prepared conditions, change only heartbeat value: precise acknowledges and preserves it; legacy API rejects. |
| restart_snapshot | SIGKILL before dispatch, change heartbeat, reopen: precise uses the identical stored conditions and acknowledges; legacy refuses stale preflight without sending. |
| contract_change_intent | SIGKILL after intent; select the other contract on restart: reject without sending. |
| contract_change_snapshot | SIGKILL before dispatch; select the other contract on restart: reject without sending. |
| lost_ack | Real adapter applies and receives API response, then deliberately drops it: uncertain across reopen, duplicate, resume and reconciliation; exactly one API write. |
| kill_after_dispatch | SIGKILL after the real API effect before durable acknowledgement: same no-replay requirement as lost_ack. |
| withdrawn_aba | At the dispatch barrier, durably withdraw, change authority away and back: authorization refuses, including after reopen; no broker API request. |
| budget_exhausted | Zero-slot policy: reject intent, no broker API request. |
| budget_revoked | Reduce limit to zero at the dispatch barrier: refuse and release the unsent reservation. |
| annotations_removed | Remove the whole map after conditions: both API-refuse with no partial write. |
| mixed_change | Change heartbeat and authority together: both API-refuse with no partial write. |
| port_layout_changed | Add a metrics port before the original named port: both API-refuse; initial multiple-port snapshots remain outside the precise contract. |
| deleting | Add a finalizer and issue deletion after conditions: both API-refuse; preserve the terminating Service without partial repair. |
| authority_aba | Change authority away and back without withdrawal: precise acknowledges; legacy API-refuses. Report the explicit history boundary. |
| backend_changed | Change PostgreSQL Service routing independently after conditions: both inventory repairs acknowledge, but independent customer verification must fail; report unresolved recovery. |

The matrix tests durable composition and fresh counterexamples, not independent
confirmation of a candidate selected on these cases. SIGKILL must terminate an
actual broker subprocess, with exit status retained. Lost acknowledgement is an
explicit transport fault wrapper around a real API write, not a simulated write.
The withdrawal case uses a trusted, durable test permit consumed through the
existing authorization callback; it does not manufacture program admission.

## Evidence and acceptance

All 32 cases must meet their declared outcomes. Server audit must attribute the
exact request, resource and response to the scoped broker identity, match the
versioned guard in the retained journal, and show no duplicate or extra mutation.
Before/intervention/after API reads must correspond to retained snapshots. Require
exact persisted effects, no scratch field or partial mutation on refusal, fresh
identities, durable binding identity/digest, budget accounting, restart receipts,
and deletion of the owned cluster. Missing evidence fails the gate.

For every case retain independent HTTP corpus, read-only database and Service
verification over a complete three-second window (at least two probes). Retain
routing-convergence observations before that window; allow only ordinary HTTP
503 convergence while all protected data and measurement controls remain valid.
Unrepaired cases must show failed customer requests with healthy controls.
The backend case must demonstrate acknowledged routing without verified recovery.
API acknowledgement and safe refusal are not customer-recovery counts.

Offline reproduction must rebuild the same assessment from exact source, journal,
raw audit and verification evidence. Unit tests additionally cover legacy migration,
concurrent resume, binding corruption, missing binding, action mismatch, stale
initial preflight and contract changes at the dispatch claim. Never relax the
existing audit recognizer to accept arbitrary patches containing expected pieces.

## Next customer-value study

After this gate, separately freeze a persistent-workload comparison against the
strongest maintained refresh procedure under common incident/dispatch budgets,
fault schedules, observations and independent verification. Test whether avoiding
a bookkeeping conflict preserves capacity for a later incident. Include quiet,
forbidden-change and before-preflight-conflict controls. Retain all failed windows
and evaluation costs. Fresh independent confirmation and sustained reuse/withdrawal
remain prerequisites for admission; this gate alone cannot earn them.
