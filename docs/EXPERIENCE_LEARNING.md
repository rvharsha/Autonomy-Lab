# Does retained operating experience help?

Prospective development protocol. No result is asserted by this document.

The routing studies established useful conventional recovery and bounded execution,
but did not establish learning. PR28 closed the observer-loss routing opportunity
with ordinary desired-state reconciliation. Adding a model to that known finite
choice would not create evidence of learning. This experiment instead asks whether
retaining measured experience improves a bounded operating decision whose reward
must be learned from a real service. Precise-contract admission and persistent
promotion remain separate deployment work; neither is needed to run this disposable
learning test.

## Claim and decision

An online reward estimator chooses how many quote requests to admit concurrently.
The code is authored; its action-value estimates change automatically after each
batch. This is bounded parameter learning, not generated procedures, model training,
novel repair discovery or a claim that an LLM is necessary. There are zero provider
calls in the experiment. The workload and capacity interventions are authored; all
response bodies, errors, timings and rewards come from actual execution. No injected
sleep or simulated reward makes a policy look successful.

Primary contrast: the learner retaining acquisition history versus the **same
learner with that history erased once** at the evaluation boundary. The erased arm
keeps its spent requests, step counter, code and budget and can immediately learn
again. Each arm runs its own acquisition requests and receives only its own past
feedback. A second contrast measures usefulness against conventional automation.

Advance to fresh confirmation only if the retained-minus-erased timely-correct
fraction in the retention phase is positive in all four blocks, averages at least
5 percentage points, is nonnegative during retention rounds 5–9 in every block,
and is nonnegative over the full evaluation in aggregate. Report retention rounds
0–4 (the erased arm's forced re-sampling cost) separately from rounds 5–9 (after
relearning). The primary includes the value of avoiding reacquisition; it does not
by itself establish more accurate estimates or a lasting advantage after relearning.
This is a declared engineering threshold, not statistical significance. Comparative
value additionally requires retained performance at least as good as AIMD and
every fixed arm **in each block**, both during evaluation and including acquisition.
The best fixed comparator is identified retrospectively and is never an oracle
available to the learner. Any missing evidence withholds both decisions. A null
result closes this particular candidate and workload; do not tune the threshold,
policy or workload after seeing outcomes and rerun under the same declaration.

## Arms, workload and capacity

Eight arms: retained and erased learners, AIMD, and fixed concurrency 1, 2, 4, 8,
and 16. The learner samples unseen levels, periodically explores every fifth step,
and otherwise uses the best mean of the latest three rewards per level (ties prefer
less concurrency). Reward is timely, semantically correct responses divided by
**all offered requests**. AIMD starts at 1 and calibrates its reference from the p90
dispatched-request latency of its own first error-free concurrency-1 batch. It halves
on a server error or p90 above twice that reference, otherwise adds 1 up to 16.
Its calibration is retained in state and replayed; it receives no extra oracle or
uncounted probes. Dispatched-request latency includes transport overhead and excludes
admission queue time, so queueing at a small limit does not prevent growth.
These are declared simple controls, not universally optimal controllers.

Each batch offers 128 simultaneous arrivals using the existing six-case quote
corpus in cyclic order, with a one-second experimental deadline from arrival to
completion. Queue time is included. Undispatched, incorrect, late and failed
requests remain in the denominator. Normal 404 and 422 cases count only against
their independent expected statuses; successful quotes require exact typed bodies.
This is a burst-response objective, not sustained production requests/second or an
existing customer SLO. Count every acquisition and exploration batch.

Four independent disposable kind environments run one block each. Within a block,
the same Quote → Inventory → Postgres workload persists across all arms and phases.
The controller sets the real inventory database role's connection limit to 2 or 16,
verifies it with PostgreSQL, and records service/pod identities, restarts and product
rows. The learner cannot see capacity labels, future schedules, other-arm rewards,
the controller connection string or evaluator internals. This is an input boundary
in trusted, frozen Python code; it is not adversarial process isolation.

Each arm runs ten batches in each of four phases: acquisition, unchanged capacity,
changed capacity, and a return to the initial capacity. Blocks 0 and 2 start at 2;
blocks 1 and 3 at 16. All have 40 batches/arm, 320 batches/block: **1,280 batches and
163,840 offered requests** overall. No per-request independence is assumed. Report
all four block contrasts, both shift directions, and each phase, including stale
memory regressions. These are development cases; the future intervention schedule
is withheld from policy inputs, not an unseen benchmark corpus.

Within each round, arm order is deterministically randomized before execution.
Batches never overlap. Every dispatched response is awaited, even when late.
Transport uncertainty or service time reaching 2.5s (near the upstream 3s timeout)
stops qualification of the entire block; the controller also observes zero inventory
database sessions before the next batch. This conservative drain check reduces
cross-arm interference; shared caches, scheduler jitter and readiness probes remain
limitations of this small development study. No failed block is replaced.
The controller's 35-minute block budget includes provisioning and stops admission
of new batches 20 seconds before expiry, preserving a clean partial failure. CI's
45-minute execution step is a backstop. A batch stops dispatching at one second;
it never serially executes all 128 requests after that deadline.

## Evidence and boundaries

Freeze exact source hashes, protocol, schedule, budgets and thresholds before any
live request. Retain per-batch intent, original bodies/statuses/timings, state before
and after, action, online feedback, drain evidence, intervention readbacks, cleanup
and a complete SHA-256 inventory. State is loaded from the prior saved batch for
every decision, so persistence is used rather than merely logged. This does not
claim crash tolerance or long-term deployment.

The offline evaluator independently classifies responses, includes queued and late
work, reconstructs every action and update from original history, checks the one-time
erasure, capacity controls, identities, population and concurrency. It refuses
changed source, missing batches and uncertain cleanup. Corrupt copied evidence to
test that wrong bodies, omitted requests, altered actions/state, bad capacity and
overlapping intervals cannot qualify. Never edit original evidence to fix a result.

The learner can only choose a local request limit between 1 and 16; it gets no cloud
credentials or mutation API. The controller alone changes capacity in disposable
test environments. No production or GCP deployment changes. Upload only allowlisted
credential-free experiment evidence. Retain failed and partial attempts. CI permits
one declared execution; a future study requires its own declaration and rationale.

If experience helps but does not beat maintained automation, report both facts.
If it passes both gates, confirm on new workload/capacity sequences before proposing
a narrow durable deployment. If it does not help, use the raw failure to decide
whether stale estimates, an inadequate action space or lack of adaptive headroom
explains the result. A more complex model is not the default response to a null.
