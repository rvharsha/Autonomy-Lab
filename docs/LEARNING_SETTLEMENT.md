# Reliable evidence before another learning claim

The long-term goal is improved future cloud outcomes through autonomously accumulated
experience, with evaluation and bounded authority governing adoption. PR31 did not
prove this: both contextual-learning cohorts were incomplete, and partial development
data exposed a stale-estimate mechanism and little descriptive room above fixed8.
Repeating those cohorts or lowering their thresholds would not resolve either issue.
Their declarations and outcomes remain unchanged.

This change implements an experimental prerequisite, not a new learning algorithm
or a production deployment. It wraps the existing Quote and Inventory handlers with
bounded request admission and terminal accounting. The original services and earlier
experiments continue to use their existing entry points.

## Settlement contract

Every experimental service process generates a fresh instance identity. An authorized
controller opens monotonically increasing batch epochs; every data request must name
the expected instance, epoch and operation number (0..127). Quote propagates the same
operation and epoch to its expected Inventory instance. A duplicate identity never
executes twice. The control API requires a per-run random token unavailable to policies.

Closing an epoch and admitting an operation share one lock. A close therefore fences
requests that have not yet entered the handler, including delayed network arrivals and
requests queued for an Inventory worker. Old epochs cannot reopen. The next epoch
requires the current epoch to be closed with every admitted operation finished. Delayed
old requests remain refused after a new epoch opens.

Inventory records terminal state in the actual synchronous SQL worker, after the
original handler returns or raises and the connection context has closed. A caller's
HTTP timeout does not finish that worker. Quote may finish earlier; settlement requires
both services' closed fences and terminal ledgers. Before the calibration advances,
the same bounded wait also observes zero Inventory database sessions through the
independent admin connection. Closing admission precedes this observation so a
queued old request cannot begin SQL afterward. All downstream operations must
correlate with an admitted Quote operation; known client-observed admissions cannot
disappear. Timeouts and errors remain unfavorable offered outcomes in any future study.

A changed instance, missing evidence or unfinished operation refuses settlement.
State is intentionally in memory, bounded to the current epoch and 128 operations.
Restart is evidence loss, never inferred success. This contract assumes these wrappers,
a trusted controller, one process per service and a dedicated read-only lab workload.
It is not a general distributed transaction protocol, durable recovery guarantee or
proof about uninstrumented background work. Control receipts are trusted observations
of this reviewed boundary, not cryptographic attestations against a compromised service.

## Engineering validation

The real-service probe uses the existing application logic, fixture data and actual
PostgreSQL queries. A declared four-second database read causes the existing three-
second upstream timeout. It requires a client-visible 503 while Inventory is still
active, rejects early settlement, then accepts only after the actual worker finishes.
A separate client-timeout case checks that canceling the wait does not manufacture
completion. Further cases cover a delayed old request after a new epoch opens, duplicate
admission, healthy response semantics and process restart with lost evidence.

An accepted original receipt is then copied and corrupted: open fence, missing terminal
entry, unissued operation, duplicate completion, forged empty ledgers and a missing
Inventory receipt for a successful downstream response. Each must fail
for its specific expected reason. Authored unit cases cover race and schema behavior;
they are not measured service outcomes or evidence of autonomous learning.

## The next scientific decision

Before proposing another learner, measure the action-dependent opportunity over the
strongest fixed controller. Any new development calibration must declare its workload
conditions, actions, full request population, budget and stop rules before execution,
retain unsuccessful conditions and charge settlement overhead. It cannot be called a
learning result. Use its observations only for development; any selected learner and
benefit gates require fresh untouched evaluation sequences.

If the opportunity is too small after exploration and decision costs, prefer a simple
policy or select a defensible cloud decision that actually benefits from experience.
If there is room, test a small learner that detects stale context knowledge, with
memory erasure, context blindness and strong conventional controls. Useful learning,
operating value, production admission and continuous self-improvement remain separate
claims. No favorable result is assumed or manufactured.

## Declared development calibration

The next calibration comprises two separately provisioned process/database blocks.
Each tests all five fixed concurrency choices (1, 2, 4, 8, 16) under all six declared
conditions: connection limits 1, 2 or 16 crossed with product-read delays 50 or 100 ms.
These model restricted downstream connection quotas and service times. They are
explicitly authored lab conditions, not observed production demand. We include all
conditions rather than claiming a favorable selected cell is representative.

Each context/action cell receives three batches per block, with all 30 cells shuffled
within each repeat by frozen seeds. That is 180 batches and 23,040 offered requests
across both blocks. Every batch offers the same 128 fixture requests, uses the existing
one-second queue-inclusive SLO, stops new dispatches at that deadline, and awaits
responses and both admission fences. All late, undispatched, server-error and settled
transport-error requests remain in the denominator. Settlement overhead is measured.
Each block has a 600-second controller budget and one attempt. Unknown settlement,
missing evidence, changed instances or failed cleanup withhold the opportunity decision.

The descriptive selector chooses the best measured fixed action separately per
condition after observing development data; this deliberately optimistic diagnostic
is neither an achieved learning result nor an uncertainty-adjusted causal bound. A
pooled gain of at least 5 percentage points over the strongest fixed action, with at
least 3 points in each block, permits considering a fresh learning test. Smaller gains
stop this candidate direction. Even a pass leaves acquisition, decision costs, drift
and out-of-sample performance to be proved. No benefit threshold or condition will be
changed using this calibration's outcomes. The one-use workflow and source declaration
are frozen before any calibration requests; failures and negative results are retained.
