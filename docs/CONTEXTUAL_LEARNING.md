# Prospective test of useful autonomous parameter learning

PR29's estimator failed its memory and operating-value gates. PR30's single
Gemini proposal improved average timely success by 1.61 percentage points versus
fixed4, below its 3-point requirement, and showed no useful retained-memory benefit.
Its state remembered the last action, not an empirical model. Those cohorts are
development evidence. Neither study proved autonomous learning or justified adoption.

The next uncertainty is whether durable, context-specific action/outcome estimates
improve later recurrences. This protocol is frozen before any new service traffic.
No favorable result is assumed. No previous candidate or outcome is replaced.

The first declaration was published before execution. A final self-review then
identified that the database probe could mistake the container image's temporary
Unix-only initialization server for its final server. Version 2 requires TCP
readiness and preserves the entire first declaration. It changes no schedule,
policy, threshold, comparator or budget. No study workflow or service batch ran
under version 1. This is a pre-execution correction, not a retry after outcomes.
The current freeze is `docs/validation/contextual-learning-v2/declaration.json`.

## What learning means here

An authored, frozen update algorithm starts without reward estimates. It updates
bounded empirical histories from its own real HTTP outcomes and chooses concurrency
without human intervention. Context labels have no built-in action mapping. This
tests autonomous parameter learning, not an LLM inventing the update rule, source
evolution, new cloud authority, model necessity or production value.

Two visible, opaque operating-mode labels are the new observation. The harness
associates them with hidden DB capacity limits 2 and 16, counterbalanced across
blocks. During a declared change interval the association reverses, then returns.
The labels are authored context signals: they are not discovered by the learner,
nor do they represent separately deployed tenants or production telemetry. The
same real Quote, Inventory and Postgres service handles every batch. A disposable
database view introduces a declared 50 ms delay into product reads. Original data
and response semantics stay unchanged. This models a capacity-constrained downstream
read path; it is explicitly an authored workload condition, not production telemetry. This deliberate
context/capacity association creates a test of reusable knowledge; it does not
establish transfer to an unseen workload. Absolute rates from earlier cohorts are
not before/after measurements for this changed observation and schedule.

Historical fixed-arm data provided only 1.22 points of descriptive context-selection
headroom over fixed4 when weighting capacities equally. This motivated the delay
condition before any new traffic; it is not a true causal bound. Fixed2 and fixed8
are therefore included alongside fixed4 in the new comparison. The delay and gates
will not be tuned using this cohort. A separate real Postgres engineering probe
checks the view, permissions, product semantics and actual delayed query execution
before service blocks start. That probe is not a learning sample.

## Frozen algorithm and comparators

The learner maintains up to four observed timely-correct fractions for each of
actions 4, 2 and 8 in each context. These actions cover the choices made by PR30's
generated policy; the environment still enforces integer concurrency 1..16.
Acquire two observations per action, then choose the highest empirical mean, with
lower concurrency breaking ties. Every sixth observed visit probes the least
recently sampled action. A reward drop exceeding 12 points below at least two
stored observations resets only that context and includes the triggering outcome
in reacquisition. These authored choices are hypotheses, not fitted to new results.
Reward is timely, semantically correct responses divided by all 128 offered calls.

Eight arms receive identical authority and the same service schedule:

- **Retained:** the contextual learner and its accumulated state.
- **Erased:** identical code, with all reward state and previous feedback cleared
  once at retention start. Spent work is preserved; it can relearn normally.
- **Blind:** identical code and state limits, with one pooled context key. This
  tests whether the contextual content of memory matters beyond a warm start.
- **Fixed2, fixed4 and fixed8:** all actions in the learner's search space; fixed4
  was the strongest fixed comparator in the prior development study.
- **AIMD:** PR29's unchanged conventional feedback update, with independent state
  per visible context. It receives the same new context information.
- **Generated:** PR30's exact, unrepaired Gemini source; no new model call.

The learner never receives capacity, phase, future schedule, evaluator code or
another arm's feedback. The controller supplies current context, external spent
step, prior returned memory and previous action/context/HTTP feedback. Each decision
runs in PR30's unchanged restricted container. Every arm crosses the same boundary.
The algorithm ignores the external step and learns only from its own outcomes.

## Real-service design

Six independently provisioned kind blocks each run all eight arms in three
rotated orders and their reversals. Every arm has the same average execution
position; this does not balance every pairwise ordering or every individual position. Each arm gets a fresh application namespace
and remains on that workload for its complete run. Workload identities, images,
data and cleanup are checked. Sequential arms share a runner; balanced order does
not eliminate time/hardware effects. These six blocks are the replicates, not the
individual requests.

Each arm has 16 acquisition, 16 retention, 16 changed and 16 return batches. Each
phase contains eight visits to each context, shuffled in two-batch runs using
declared seeds. Erasure occurs once before step 16. Labels switch without reset
elsewhere; stored estimates must survive fresh policy processes and context changes.
There are **3,072 batches and 393,216 offered requests** in total.

The existing six authored HTTP cases, independent semantic classifier and one-second
queue-inclusive SLO remain unchanged. Policy selection precedes arrivals; measured
batch-plus-decision throughput accounts for decision time separately. This is a
discrete-batch experiment, not a continuously arriving queue. Stop admissions at
one second, await all started requests, verify DB readers drain, and retain all
late, wrong and undispatched calls in the denominator. Transport uncertainty,
any dispatched request duration >=2.5 seconds, failure to confirm zero DB readers
within 5 seconds, incomplete accounting or unconfirmed cleanup invalidates
the original block. There is one attempt, no replacement. Controller budget is
45 minutes per block, with a 60-minute CI outer bound. No GCP deployment occurs.

## Prospective decisions

The thresholds remain material, not merely a positive pooled average:

1. **Retained-memory gate:** retention gain over erasure >=3 percentage points
   pooled and positive in all six blocks; after six visits per context, retention
   gain is nonnegative in every block; full evaluation gain is nonnegative.
2. **Context gate:** evaluation gain over the context-blind copy >=3 points pooled,
   with no regression in any block or either context pooled. Evaluation includes
   retention, changed and return phases. Both gates are required for the bounded
   autonomous parameter-learning claim. The late-retention slice contains only
   two visits per context per block, so it is a regression check, not a strong
   stand-alone statistical estimate.
3. **Operating-value gate:** both learning gates, plus >=3 points over fixed2, fixed4, fixed8,
   contextual AIMD and the unchanged generated controller in both evaluation and
   lifetime, including acquisition. No block/window regression; changed-phase
   regression <=1 point pooled versus each baseline; lifetime timely responses
   per measured batch-plus-decision second >= every baseline.

No p-value or generalization guarantee is inferred from these small block counts.
A memory pass without a value pass demonstrates bounded learning with insufficient
service value for adoption. A failed memory/content gate leaves autonomous learning
unproved. Even all passes would require independent fresh confirmation and broader
conditions before persistent canary admission or a continuous-improvement claim.

## Reproduction and failure accounting

Freeze source, policies, schedule, workflow, tests and these criteria to
the versioned declaration before traffic. A one-use
workflow refuses repeated attempts. Wholly skipped runs from unrelated labels do not consume the attempt;
any earlier executed or uncertain freeze does. The pinned PR30 base intentionally
refuses a moved base; it requires a new prospective declaration, not a bypass.
Retain partial originals and the complete request
population, decision input/output/state and timestamps. A separate job reconstructs
every HTTP score, replays all decisions in isolated containers, verifies observation
handoffs, intervention schedule and state erasure, and recomputes the gates.
The unmodified original must first be accepted; ten altered copies of actual evidence
must then be rejected for their specific expected reasons, including wrong context
and forged learned state. Authored unit and boundary tests are engineering checks,
not experimental observations. Report all failed/cancelled jobs and review costs.

The next decision after this experiment is whether to seek independent confirmation
of a useful learner, or revise the learning hypothesis using these data as development
evidence. Do not retry or tune this frozen cohort until it passes.
