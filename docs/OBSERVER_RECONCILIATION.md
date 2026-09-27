# Observer outage: test the conventional reconciler first

This prospective development comparison follows the actual unrecovered
`observer_routing` trace. It asks whether a fixed desired-state reconciler closes
the gap before investing in an experience-conditioned proposer. Both procedures
are engineered. There is no model, learned policy, admission or deployment claim.

## Contract and comparators

The disposable trial's controller binds a fixed intent: Inventory Service, one
http port, targetPort 8080, exact run and Service UID, single-trial lifetime. The
same contract is declared for both arms. Current resourceVersion is an observation,
not an intent revision. Dynamic intent, deliberate release changes and freshness
of an external configuration source are outside this contract. They require a
new shared observation/authority contract, not inference from an error message.

`program` is the maintained p111 procedure: verify on backend-observer outage,
repair diagnosed routing, refresh a received conditional rejection. `desired_state`
is a conventional fixed-intent reconciler. It observes the same public Service,
backend and application probes. An in-scope mismatch permits one conditional
restoration attempt; neither a configured probe port nor a failed probe establishes
backend health. An acknowledged write is followed by independent semantic checks.
An unresolved write is inspected once and never retried. No successful completion
is claimed without fresh successful verification after any possible mutation.

Both use existing broker authority, two-dispatch maximum, legacy UID/resourceVersion
conditions, existing protected invariants, independent verifier and API audit.
The reconciler itself attempts at most one dispatch. This source extension changes
runtime hashes; prior admission evidence and precise-contract approval do not carry
forward. Existing eight-policy and recent-quietness negative studies remain closed.

## Frozen development cases

Eight contexts, two independent reset trials per arm/context: 32 total trials.
Each of four shards has two contexts, two repetitions and both arms; seeded ordering
is fixed before execution. A 30-second final semantic verification window applies
to every trial. These are final-state observations, not continuous availability
calendars, service-hours or independent statistical reliability estimates.

| Context | Faults deliberately established | Question |
|---|---|---|
| observer_routing | routing mismatch and closed backend-observer connection | Does conventional restoration recover the known missed case? |
| observer_outage | closed backend-observer connection only | Is healthy service left unchanged? |
| observer_quote | wrong HTTP-200 quote arithmetic and observer outage | Is semantic failure preserved? |
| observer_routing_quote | arithmetic failure established before routing mismatch; observer outage | Does routing repair avoid claiming full recovery? |
| observer_backend | revoked Inventory database read privilege and observer outage | Does real backend failure remain a failure? |
| observer_routing_backend | the same backend failure plus routing mismatch and observer outage | Does a successful routing write remain insufficient for recovery? |
| observer_routing_verifier | routing mismatch plus separate actor backend/verifier observation outages | Can final customer recovery coexist with correct withholding of a completion claim? |
| observer_verifier | backend/verifier observation outages only | Is unknown actor verification kept unknown despite later healthy ground truth? |

The controller supplies faults, never desired-state conclusions to either actor.
Actor-facing verification loss uses a closed real forwarding endpoint. After the
actor finishes, a separate live measurement path assesses the environment; that
result is unavailable to the actor's decision. Backend permission readback, actual
wrong quote bodies and raw control observations substantiate the relevant faults.

## Evaluation and decision

Freeze the complete configuration, source hashes and seeded order before opening
the single live workflow. Retain every attempt; no automatic retry or replacement.
The workflow serializes this study and checks its run history, including executions
opened from another PR on the same study branch. A failed or missing execution
prevents a benefit decision. A separate always-run retention step snapshots
partial original files after the live wrapper exits; it cannot qualify or replace
a failed attempt. Partial snapshots retain SQLite rollback/WAL sidecars when
present and make no claim of an atomic database snapshot. Reproduce raw final and
actor verifier probes, original scores, journal operations, API audits, intent and
program bindings, full accounting and cleanup. Preserve rejected and uncertain
requests and all failed or unknown customer outcomes. Corruption controls operate
on copies of actual evidence and must fail for their declared reasons.

The historical task scorer requires a successful direct backend observation for
repair evidence. Its score is retained unchanged and is not this study's acceptance
metric: it would reject the deliberately different fixed-intent justification.
A separate auditor binds that intent to the actual observed resource and API request.
This does not relax the broker, semantic verifier or historical admission rules.

An observed conventional benefit requires both repetitions to recover the primary
observer_routing case where maintained automation fails, no lower final recovery
count in any other context, no false or unsupported completion, no mutation on a
matching target, preserved protected state, and complete authority/cleanup evidence.
Partial routing recovery with semantic/backend failure must remain escalated. Actor
verification outage must never support a completion claim, even if final ground
truth is healthy. The decision is withheld on unsafe or incomplete evidence; a
complete comparison without the specified gain reports no qualifying benefit.

If the conventional reconciler closes the observed gap, close that opportunity as
an engineering improvement. It supplies no evidence of model value. If a residual
observable decision tradeoff survives, define an experience/no-experience ablation
and strong maintained/exhaustive comparators before adding a proposer. Previously
inspected cases cannot become hidden tests. This study does not implement continuous
same-service updates, intent changes or durable grant renewal.
