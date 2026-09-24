# Continuous service ownership: next implementation milestone

This is the next phase after the bounded experiments in [the findings](FINDINGS.md).
The objective is to keep one real service within an explicit operating contract
while its operator stops, restarts and faces recurring incidents. Continuous
operation and learned improvement remain proposed, not demonstrated capabilities.

## First claim and implementation boundary

First close the evaluator's [mixed-state termination gate](MIXED_STATE_RECOVERY_EXPERIMENT.md).
Then implement a separate campaign entry point; do not reuse trial resets as a
claim of continuous operation or merely disable experiment cleanup.

Use three distinct lifecycles:

- A campaign owner provisions one Quote/Inventory/PostgreSQL workload, holds a
  bounded cleanup lease and records the original resource identities. Only that
  owner may end the campaign and delete the workload.
- A restartable operator observes and proposes today's typed routing repair
  through the existing broker. Its restart cannot recreate the workload, reset
  the measurement window, rewind the campaign budget or abandon uncertain work.
- An independent observer samples real requests and protected state throughout
  operator downtime. It records scheduled intervals, timestamps, failed requests,
  latency and unavailable measurements. Missing samples are unknown, never healthy.

Start with one operator and one broker per campaign, protected by an exclusive
process lock. A second operator invocation must refuse ownership. Broker operation
IDs, outcomes and spent budget live outside operator checkpoints; restart first
reconciles outstanding operations. Existing conditional UID/resource-version
checks protect against stale external changes. Unresolved effects stop new writes
and escalate; restart is never permission to repeat an uncertain mutation.

Freeze a machine-readable operating contract before running: workload and protected
invariants, sampling cadence and timeouts, repair deadline, campaign duration,
maximum restart downtime, total dispatch budget and escalation policy. The initial
action scope remains Inventory Service routing. Releases, capacity management,
multiple operators and procedure updates need separate contracts and gates.

## Evaluation gates for the implementation

1. Establish the workload and observer, stop only the operator, and prove workload
   resource UIDs and protected rows persist. Observe real customer requests during
   the interruption. Restart the operator within the declared downtime bound.
2. Inject a routing fault; require a broker-attributed repair and sustained
   independent verification. On recurrence, require a new incident identity and
   continued cumulative budget/accounting, with no workload reset.
3. Interrupt after dispatch but before the operator receives its result. Resume
   through durable lookup and verification without duplicate effects. Change the
   Service independently during downtime and reject stale writes.
4. Refuse concurrent operator ownership, preserve escalation/uncertainty during
   telemetry failure, and fail closed when the campaign budget is exhausted.
5. Terminate the campaign owner and prove bounded cleanup separately from operator
   restart. Export the entire declared timeline with interruptions, unknowns,
   customer impact and action/audit records; reproduce the export byte for byte.

Implement and challenge the scorecard before attributing an improvement to an
operator. Unit tests can validate accounting and state transitions; only real
workload observations can pass these gates. Predeclare fault schedules and stopping
rules. Preserve every failed run and record the source/policy/checker hashes.

## Subsequent milestones

After persistent ownership passes, introduce proposed procedure versions with
provenance, sealed counterexamples, regression gates, shadow/canary rollout,
explicit promotion authority, withdrawal and handling of in-flight work. The
proposer cannot alter authority, the verifier or the pass criteria.

Only then preregister a sustained comparison of competent conventional automation,
a frozen model-assisted operator and an evolving operator. Match effective
authority, starting conditions and schedules. Measure customer impact, actual
human active time and full operating/evaluation cost. Missing human-time records
remain unknown. Begin with a bounded integration campaign, then repeat across
conditions; a single day is not evidence of production reliability or ROI.
