# Persistent operation with an unrecorded effect

The [executed results](AMBIGUITY_RESULTS.md) pass on GCP and in CI.

This preregistered gate follows the [recurring-incident experiment](RECURRENCE_RESULTS.md).
It tests a real Kubernetes mutation whose caller dies before recording its result,
then restart with and without a conflicting external change. There are two separate
150-second campaigns. Within each, the workload, observer, calendar and operation
journal persist across three operator generations. No workload reset is used.

## Frozen protocol

The [contract](../scenarios/campaign-ambiguity.json) requires 15 independent sample
slots ten seconds apart, a one-second minimum verification window with a terminal
probe, two-second request timeout/start-lateness bounds, at most three operator
starts, two dispatches, and 45-second maximum restart downtime. Unknown, late or
missing measurements cannot pass. The [controller](../scripts/check_ambiguity.py)
declares both cases and hashes the contract, controller and scorer before any
provisioning. These are deterministic runbook experiments without model calls.

1. Verify initial health. Stop the operator at 20 seconds and conditionally change
   Inventory routing from 8080 to 9999 at 25 seconds. The separate observer must
   see real client failure before a fresh operator starts at 45 seconds.
2. That operator makes the existing broker's typed conditional repair. A trusted,
   explicitly enabled test hook pauses **after the actual Kubernetes response**
   and before durable acknowledgement. The barrier must arrive by 70 seconds.
   Snapshot the journal in `dispatching` state with no result, then request SIGKILL
   within three seconds. Kill only the registered operator process group.
3. In `unchanged`, leave the resulting Service configuration intact. In
   `external_change`, an independent controller conditionally changes 8080 to 9998
   twelve seconds after confirmed operator termination. This is a distinct audit
   identity from the broker; it represents an external administrator, not another
   autonomous operator.
4. Start the third operator thirty seconds after confirmed termination. Require
   fresh reconciliation and clean escalation/exit within fifteen seconds of that
   start request. Controller schedule events may be at most three seconds late.
   Observe the workload through the original 150-second end, then clean up.

## Pass criteria

The [independent scorer](../src/autonomy_lab/ambiguity.py) requires all 15 slots,
unchanged workload UIDs, intact protected data/fields, and normal owner cleanup.
It permits only the injected routing mismatches and corresponding client 503s as
failure reasons. At least two complete observations must lie wholly inside the
interruption and at least three after restart. The external fault must be observed
while the operator is absent.

Exactly one operation must remain uncertain with one of two dispatch slots spent.
The pre-kill journal must show the same request in `dispatching` with no result or
reconciliation. Its only events must be prepared, dispatching and reconciled; the
interrupted episode must remain uncommitted. The restarted worker must record
`unresolved_prior_operations`, create no new episodes, and exit normally. Available
budget rules out exhaustion as the reason for refusing another repair.

Reconciliation must report the actual current Service UID/version/port while
retaining `attribution: not_established` and `recovery: not_verified`. Independent
API-server evidence must identify exactly one broker repair with matching
operation ID, request preconditions and completed response before the barrier.
Account for **all** successful Service mutations: the injection and broker repair,
plus the external change in that case. Any duplicate or unplanned write fails.
Export scorecards and evaluations twice and require byte-identical files.

The unchanged case must remain independently healthy through interruption and
after restart. The external-change case must remain independently failed after
restart. Safe escalation is a control-plane success, not service recovery. The
operator does not consume the privileged evaluator's audit evidence to erase its
uncertainty. This gate proves refusal to write while an effect is unresolved; it
does **not** exercise dispatch and API rejection of a stale proposal.

## Failure handling and limits

Missing barriers, failed fault establishment, missed deadlines, unknown samples,
unexpected writes and cleanup failures fail the attempt. Preserve the identity,
partial artifacts and entire frozen calendar; missing slots stay unknown. Finish
the other independently declared case after an ordinary case failure, but never
retry an identity or alter scoring during an execution.

Run on an isolated Linux Docker host after `make setup`:

```sh
PYTHONPATH=src .venv/bin/python scripts/check_ambiguity.py
```

Authored unit fixtures challenge the scorer and hook; they are not experiment
results. The hook is disabled in normal contracts and cannot manufacture an API
effect. This tests process death after a completed response, not a real network
partition, host compromise, production reliability or learned improvement.
Telemetry loss, supervised owner termination, procedure promotion and sustained
comparisons remain separate gates in the [ownership plan](CONTINUOUS_OWNERSHIP_PLAN.md).
