# One generated operating-policy improvement

Prospective study after the failed retained-experience gates in PR29. No outcomes
are asserted here. The decision is whether one automatically generated policy can
beat fixed concurrency 4 and the unchanged online learner on fresh sequences.
This is a bounded admission-concurrency policy, not new cloud-operation authority.

## Retained preflight and successor declaration

The original input preflight returned 57,149 tokens and was refused by its frozen
50,000-token ceiling. It made zero generation calls and zero live study attempts.
The original declaration, exact request and rejected record remain in
`docs/validation/generated-policy/` at commit `7b64399`. They are not overwritten.
Version 2 changes only the lossless input representation and binding paths. It
keeps the same hidden schedules, thresholds, budgets, comparators and source
semantics; there has been no candidate or evaluation feedback to tune against.
Freeze the successor in `docs/validation/generated-policy-v2/` before its separate
count/generation attempt. Both preflight records belong in the final accounting.

## Freeze and generation

Freeze all runner, evaluator, loader, input, source, workflow, schedule, budget and
criterion hashes before the model call. Preserve all 1,280 original PR29 batches as
development data. Independently audit them, then provide all batch-level actions,
timely-correct counts, server errors, dispatched counts and p90 durations, with
source hashes and the unchanged learner source. The proposer receives no fresh
schedules, evaluator implementation, future capacities, or other evaluation arms.
The successor packet groups repeated block/phase/capacity headers and indexes arm
labels; its round-trip check preserves every original row, order and floating-point
value. Hash inventories remain in the development packet and are omitted from model input.
This tests a fresh sequence distribution of the same authored workload, not unseen
applications or failure families.

Use Gemini 3.8 Flash directly through the existing Google transport: one candidate,
low thinking, temperature 1, at most 50,000 counted input tokens and 8,192 output
(including thinking) tokens. One count and one generation request; no retries,
continuations, fallback, alternate proposal or manual source repair. Freeze the
exact provider final text, decoded source bytes, returned model, usage and cost
estimate. Preserve incomplete responses privately; do not publish provider thinking.
The token reservation is not an invoice guarantee. Standard prices checked on
2026-09-28: $0.75/M input and $3.75/M output, including thinking, through 2026-12-31
([Google pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-flash)).

The proposal is new Python source implementing `step(observation)`, not selection
from the existing routing catalogue. Only `{action: integer 1..16, memory: object}`
is accepted. Source and memory each cap at 16 KiB; output caps at 32 KiB. Inputs are
an external spent-step counter, prior returned memory, and that arm's previous
action/feedback. Memory starts empty. Candidate code sees no phase, capacity,
workload credentials, hidden inputs or other-arm history. A new nonroot read-only
network-denied Docker container executes every decision, with no mounts, dropped
capabilities, no new privileges, 16 PIDs, 256 MiB cgroup memory, 128 MiB address
space, one CPU-second and 10-second wall limit. Docker shares the host kernel;
this is bounded lab isolation, not a claim of protection against kernel exploits.
The credentialed controller never imports or executes generated source. It validates
output outside the container. Cleanup is required on errors and limits.

## Real comparison

Four independently provisioned kind blocks. Each runs four arms, in balanced Latin
rotation: candidate, same candidate with one memory erasure, fixed4, unchanged PR29
learner. Recreate the application namespace between arms and require disjoint pod
and service UIDs, identical data and images, then keep each workload persistent
within its arm. Arms execute sequentially on the same runner, so balanced order
reduces but cannot remove time/hardware effects. Readiness probes remain active;
per-request DB connection and service behavior remain the actual existing code.

Capacity profiles are [2,2,16,2] for blocks 0/2 and [16,16,2,16] for 1/3. Phase
lengths (acquire, retention, changed, return) are respectively [11,7,13,9],
[9,13,7,11], [13,9,11,7], [7,11,9,13]. Erase candidate memory and prior feedback
only once at retention start, retaining step count and all spent work. It can then
relearn normally. This ablation measures retained runtime memory, not the necessity
of prior development traces or Gemini reasoning.

Each arm offers 40 batches of 128 arrivals: 640 batches and 81,920 requests total.
The six existing request cases cycle within every batch. The one-second deadline
includes queueing; late, wrong and undispatched arrivals remain in the denominator.
Await started requests and require DB reader drain before the next batch. Transport
uncertainty, service duration >=2.5 seconds, changed workload, source drift, invalid
candidate, incomplete accounting or failed cleanup invalidates the original block.
Keep the failure; no replacement or benefit decision. The controller wall budget is
40 minutes/block including provisioning and reset; CI has a 55-minute outer bound.

All arms use the same per-decision container boundary. Separately retain actual
policy wall time (including startup/cleanup), batch wall time, full block and CI
cost, acquisition requests and the one model call. A request SLO starts after the
policy decision; this is a discrete batch study, not an always-arriving production
queue. Include decision time in lifetime timely responses per measured service
second. Setup, resets, drains, model generation and evaluation costs are reported
separately; this metric is not a dollar ROI or production throughput claim.

## Frozen decisions

The generated-improvement gate requires, against BOTH fixed4 and legacy:

- At least 3 percentage points pooled timely-correct gain in evaluation (all phases
  after acquisition) AND lifetime (including acquisition).
- Nonnegative gain in each of the four blocks in both windows.
- No lifetime capacity-pooled regression greater than 1 percentage point.
- Lifetime timely responses per measured batch plus decision second at least as
  high as both baselines.

A separate memory gate requires >=3pp pooled retention gain over the erased
candidate, positive retention gain in all blocks, nonnegative retention gain after
round 4 in every block, and nonnegative pooled full-evaluation gain. A pass of one
gate cannot stand in for the other. There are four blocks, not 81,920 independent
replicates; no significance or broad generalization claim follows.

Reconstruct exact semantic responses independently and deterministically replay all
640 decisions in fresh isolated containers. Reject altered output or state, wrong
model/proposal lineage, incomplete populations and any nondeterminism. Corrupt
copies of original evidence and refresh hashes to test rejection of semantic errors,
omitted requests, action/state changes, capacity mismatch, overlap, missing batches
and failed originals. Authored boundary/unit tests are separate from live outcomes.

The one-use PR workflow refuses reruns and additional study executions. Its freeze
job verifies the already frozen declaration and proposal; it does not manufacture
a new pre-generation freeze. The candidate need not pass to merge an honest study.
A qualified result only supports planning a scoped persistent canary. Durable
admission, grants, withdrawal, rollback, unattended recurrence and independent
replication remain necessary before a continuously improving deployment claim.
