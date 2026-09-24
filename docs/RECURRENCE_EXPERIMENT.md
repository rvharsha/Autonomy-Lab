# Recurring incidents with cumulative authority

This gate extends the [healthy persistent-workload gate](PERSISTENT_CAMPAIGN.md).
It tests one persistent workload, two attributed repairs across operator restarts,
and a third incident refused after the campaign's two-dispatch budget is spent.
It uses the existing deterministic runbook. No model generation or learned
procedure is involved. Results must come from actual Kubernetes and HTTP/database
observations; unit fixtures are not experimental evidence.

## Preregistered contract

[The campaign contract](../scenarios/campaign-recurrence.json) fixes a 300-second
calendar, 30 observations ten seconds apart, four operator starts, two cumulative
dispatches, and a 45-second maximum operator downtime. The independent observer
uses a one-second minimum window and terminal probe, two-second request timeouts,
and two-second maximum start lateness. Collection must end before the next slot.
Missing, late or indeterminate slots cannot pass this gate.

[The controller](../scripts/check_recurrence.py) freezes these events and the
checker/scorer/contract hashes before provisioning:

| Incident | Stop operator | Inject fault | Restart operator | Required response |
|---|---:|---:|---:|---|
| routing-1 | 20 s | 25 s | 45 s | Attributed repair and verified recovery |
| routing-2 | 100 s | 105 s | 125 s | New attributed repair; same cumulative budget |
| routing-3 | 180 s | 185 s | 205 s | Budget rejection, escalation, no third repair |

All offsets are from the single frozen measurement start. Controller events may
be at most three seconds late. Each response has a 70-second deadline from the
fault dispatch request, including the intentional operator downtime. Operators
are stopped before injection so the independent observer can establish real
client failure before restart. This tests restart into recurrence; it does not
test spontaneous faults arriving while an operator is already active.

## Pass criteria and stopping rules

The scorer requires all 30 slots to be assessed, all 11 workload UIDs unchanged,
protected database rows and Service fields intact, and normal owner cleanup.
Only the injected target-port mismatch and resulting client HTTP 503s may explain
failed measurements. Every failure stays in the calendar. A successful gate is
not a claim that the service was continuously healthy.

For the first two incidents, require a new operation linked to that operator's
tool evidence, an acknowledged dispatch, a matching broker API-server audit event,
a resolved episode, and full independent health before the deadline. At least
two subsequent samples must remain healthy until the next injection. The third
requires a recorded `budget_exhausted` rejection, an escalated episode, operator
exit, and continued independently measured service failure after the deadline.
Correct escalation leaves an unresolved incident for an authorized human; it
does not count as service recovery or human-work savings.

There must be exactly three operation records, two reserved dispatches, and five
successful Service writes: three declared controller injections and two broker
repairs. The existing independent audit checks patch scope and preconditions;
the recurrence scorer additionally requires exact operation-ID user agents and
accounts for successful Service writes from any actor. Two exports must match
byte for byte. Raw credentials and detailed cluster artifacts remain private.

A missing owner, failed fault establishment, missed readiness deadline, failure
to restore the prior routing configuration, or export/check failure ends the
attempt and triggers cleanup. Preserve that failed identity, partial evidence,
and the entire calendar with unmeasured slots unknown. Do not extend deadlines,
reset budgets, replace failures, or tune the scorer during an execution.

Run on an isolated Linux Docker host after `make setup`:

```sh
PYTHONPATH=src .venv/bin/python scripts/check_recurrence.py
```

This is a bounded integration gate, not evidence of improved decisions over a
capable baseline, production availability, untrusted-host isolation or autonomous
learning. Response loss, external conflicting changes, telemetry gaps, supervised
owner termination and independently gated procedure improvement remain separate
experiments in the [continuous ownership plan](CONTINUOUS_OWNERSHIP_PLAN.md).
