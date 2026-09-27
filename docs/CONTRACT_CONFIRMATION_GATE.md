# Fresh confirmation of customer benefit

26 September 2026. Prospective protocol, committed before implementation or
execution. This is one bounded confirmation cohort of the exact PR23 candidate;
it is not admission, deployment, model discovery or production reliability.

## Fixed candidate and evidence boundary

The selected source is 9f57082617f286dcfec6587e507b77902eb50096, whose tree equals
the PR23 merge fa5223b19851ea689a25f6e90789eb5849d43706. The exact program/runtime
pin and both combined contract identities are retained in
`experiments/contract_confirmation/runtime-pin.json`. Every runtime dependency
and program byte must match before provisioning and again during replay. New
controller/evaluator code lives outside the runtime and is separately hashed.
Do not weaken the dependency manifest or modify the selected runtime.

The common workload, observation semantics, budgets and schedule are those of
[PR23](CUSTOMER_BENEFIT_GATE.md): 210 seconds, 21 sampled customer windows,
three operator starts, two cumulative dispatch slots, no model requests.
Initial fixture at t15, stop initial operator t20, routing fault t25, first
response starts t45, stop it t115, second fault t125 only after healthy complete
t90/t100/t110 observations, and second response starts t140. Missing recovery
withholds eligibility; it does not authorize external repair or a reset.
First response completion deadlines remain 20 seconds and schedule lateness
remains at most three seconds. Preserve all failed and unrealized attempts.

## New causal combinations

Run each context for both legacy and precise, exactly once. Use seed 2026092602
to shuffle the eight named cases, then four shards with every fourth case.
Freeze the complete plan and source hashes before any case executes. The arms
differ only in the execution contract. All writes are real Kubernetes requests.

1. `heartbeat_burst`: hold the first prepared-dispatch barrier, change heartbeat
   from `initial` to `tick-1`, then to `tick-2` using two separately audited
   conditional requests. Release only after observing the second response.
2. `heartbeat_annotation`: at the same barrier change heartbeat to `tick-1`,
   then add `autonomy-lab/confirmation-protected=changed` as a separate annotation
   request. The heartbeat exception cannot conceal that protected map change.
3. `heartbeat_return`: at the same barrier change heartbeat to `tick-1`, then
   back to `initial` in a separate request. This tests current-value semantics,
   not the absence of authority ABA or restoration of withdrawn permission.
4. `heartbeat_post_ack`: no prepared-barrier intervention. At t85, after an
   acknowledged first repair and before recurrence, change heartbeat to
   `tick-1`. Bind the action to the retained acknowledgement and require no
   unresolved operation at intervention. An acknowledgement need not retain
   the current resourceVersion indefinitely.

Novelty audit: PR21 covered individual heartbeat/unknown-annotation changes;
PR22 covered heartbeat plus authority change in one request and authority ABA;
PR23 covered one late heartbeat, one protected label, quiet recurrence, and an
early single-incident heartbeat. These four combinations have not been executed
in those corpora. They are authored prospective cases, not a production sample
or evidence of independence from the experiment designer. PR23 remains separate
regression evidence; no existing case is relabeled unseen.

## Measurements, adversarial checks and acceptance

Retain each controller mutation, scoped API request/response and full-resource
effect in its actual order. Verify every proposal against its episode and pin,
durable conditions, journal/budget, prior observations and actual API effects.
Check all scheduled customer windows, including complete database/corpus/control
evidence when the customer outcome is failure. Audit the complete Service-write
inventory and replay exports byte for byte. Never collapse multiple controller
requests into one synthetic record to satisfy an older checker.

Challenge copied evidence for omitted, reordered and altered intermediate
mutations; wrong barrier/ack timing; missing identity, conditions, request or
measurement evidence; extra requests; protected effect corruption; and incomplete
case inventory. Require the specific intended rejection, not an arbitrary crash.
These negative controls are evaluator tests, never additional live trials.

Require complete, eligible, authority-conformant evidence for both arms in all
four contexts. Precise must have no fewer healthy samples and no more actual
dispatches in any context, and strictly more healthy samples in heartbeat_burst.
Ties or a measured regression retain legacy. Missing evidence or an unrealized
required opportunity withholds selection. Selection grants no authority.

One attempt per case, eight campaigns total, zero model calls, at most two
dispatches per campaign and 25 minutes per shard. No retry or favorable subset.
Stop this confirmation attempt after that cohort. A runtime or evaluator change
in response to results converts the cohort to development evidence and requires
a separately declared fresh confirmation; preserve the original failure.

Report healthy/failed/unknown samples, actual requests, spent/remaining capacity,
completed verification work, interrupted verification episodes, and elapsed
evaluation cost. In-flight verification and diagnosis requests remain incompletely
accounted by the frozen runtime: no full request-cost, billing, human-time or ROI
claim. Observation samples are not continuous availability.

## Decision after the cohort

A passing comparison earns consideration for separately evaluated admission bound
to program/runtime plus execution-contract identity. Existing program approval
cannot inherit precise semantics. Old approvals, stale revisions, restart,
withdrawal and non-replay must pass their own gate before sustained reuse.
Then measure multiple explicitly budgeted cycles on one persistent workload.
Candidate generation remains a later separate treatment against maintained
automation, including its search and evaluation costs.
