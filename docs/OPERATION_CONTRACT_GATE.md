# Operation-contract feasibility gate

Frozen design, 25 September 2026. This is a prerequisite API experiment, not an
admitted broker policy or a customer-benefit result. The existing broker remains
unchanged. It follows the failed contention-information development gate.

## Question and boundary

Can one conditional routing patch tolerate a declared bookkeeping annotation
changing after observation, while rejecting every other observed Service spec or
metadata change? A list of tests on selector and ports alone is insufficient:
new annotations, owner references, finalizers and labels must remain relevant.

The fixed action changes only the named `http` port from integer 9999 to 8080 on
one observed `v1/Service` in `autonomy-lab`, named `inventory`. UID, name,
namespace, complete spec, status, and complete metadata are protected. The only
permitted differences before application are resourceVersion, API-managed
managedFields, and the **value** of the pre-existing annotation
`autonomy-lab/contract-heartbeat`. Removal of that annotation is refused.
The annotation is owned by this experiment and has no application, diagnosis or
authorization consumer. This declaration does not generalize that property to
annotations in other environments. managedFields is API field-management
bookkeeping, not RBAC or ownerReferences; allowing it is part of this explicit
contract change. Its current value is preserved for API processing.

A candidate JSON Patch temporarily copies the current metadata to a scratch
member, normalizes only the three declared exceptions, tests the full metadata
against the observed normalized metadata, then restores the current metadata.
It also tests apiVersion, kind, the full spec and status before replacing the
single targetPort. Scratch state must be removed before completion. This is one
atomic PATCH; a failed intermediate test must persist none of its operations.
Actual API behavior, rather than a test-double interpretation, is the gate.

The comparator is the existing broker's exact UID/resourceVersion/port patch.
Both arms receive the same initial fixture semantics and one dispatch, with an
external intervention completed **after patch construction**. There is no
refresh, retry, model call, or use of the intervention label by the patch builder.
Fresh Service UIDs per arm prevent one arm's writes benefiting another.

## Frozen matrix and acceptance rule

Both arms run each case once, in listed order:

1. No intervening change: both acknowledge.
2. Declared heartbeat value change: candidate acknowledges, comparator refuses.
3. Heartbeat removal: both refuse.
4. Unknown annotation added: both refuse.
5. Existing authority annotation changed: both refuse.
6. Existing authority annotation removed: both refuse.
7. Label added: both refuse.
8. Owner reference added: both refuse.
9. Finalizer added: both refuse.
10. Selector changed: both refuse.
11. Port protocol changed: both refuse.
12. Service port number changed: both refuse.
13. Additional port added: both refuse.
14. Another actor already repaired the targetPort: both refuse.
15. Resource deleted and recreated under the same name: both refuse.

A valid execution requires all 30 actual API responses to match the rule, the
candidate to preserve the intervention's latest heartbeat value on acceptance,
no persisted scratch member, exact preservation of all other client-visible
fields (except API resourceVersion/managedFields), and no partial write on
refusal. The independent API-server audit must attribute exactly one request to
each arm/case, with matching request body, response and scoped broker identity.
Every attempt and cleanup failure is retained; missing/unknown evidence fails.
An offline replay must reproduce the assessment. No subset selection or tuning
of this rule after viewing results is allowed.

## What a pass would and would not establish

A pass establishes feasibility for this patch and pinned Kubernetes version.
It permits designing a trusted broker integration; it does not promote the
candidate. The snapshot must ultimately be bound to durable operation identity
and contract version so restart cannot silently change its conditions.

Before admission, require real tests of lost acknowledgement, restart without
blind replay, pre-dispatch withdrawal, exhausted budgets and unresolved effects;
independent customer verification under contention; backend changes outside the
Service; and fresh confirmation cases. A Service patch cannot atomically guard
another resource. A successful API response never establishes customer recovery.
Then test one qualified improvement through recurrence, restart and withdrawal
on the same persistent workload under common budgets. Neither a successful
feasibility gate nor a new contract constitutes a model-improvement result.

References: [Kubernetes conditional updates](https://kubernetes.io/docs/reference/using-api/api-concepts/#updates-to-existing-resources),
[RFC 6902 operations and atomic failure](https://www.rfc-editor.org/rfc/rfc6902.html).
