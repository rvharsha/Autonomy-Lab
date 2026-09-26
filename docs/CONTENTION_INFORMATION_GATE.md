# Does observing contention earn its delay?

Development protocol, frozen before execution. This is a conventional timing
comparison, not a result, learning study or promotion. The previous
[finite comparison](FINITE_POLICY_COMPARISON.md) retains its original decision.

## Question and calendar

Can ordinary Service reads improve when a routing repair starts, compared with
both immediate response and fixed delay? Past version stability cannot promise
that another controller will remain quiet. Resumed activity challenges that assumption.

Twelve fresh Kubernetes campaigns compare three rules in four authored contexts.
Each runs for 90 seconds with one persistent workload, eighteen independent
one-second customer windows every five seconds, and two total broker dispatches.
Actual API rejections spend slots. Every arm runs the same maintained refresh
program. No new action, renewal, model call, admission or procedure replacement.

Stop the initial healthy operator at second 8; inject the existing 8080-to-9999
routing fault at second 12, between customer windows. Decisions start at second
30. A launched worker must be ready within ten seconds; its earliest episode must
finish by second 65. End the workload and clean up at second 90.

| Arm | Launch rule |
|---|---|
| immediate | Second 30, no selector reads |
| fixed_wait | Second 45, no selector reads |
| observe_quiet | Read once per second from second 30; launch after four identical versions on one UID spanning at least 2.5 seconds, with gaps at most 1.5 seconds; otherwise decline at the 15-second deadline |

Read responses must finish within one second and precede the decision; sixteen
reads maximum. Only elapsed time and completed UID/version/time projections enter
the selector. No annotations, context, future schedule, post-decision evidence or
other arm's outcomes. Fixed comparators have the same access but do not pay for
unused reads. Count additional observations and waiting explicitly. The trusted
experimental launch gate is conventional automation, not a learned procedure or
a new security sandbox. Malformed, stale or changed-identity signal cannot launch;
missing measurement invalidates the cohort rather than becoming healthy data.

| Context | Independent metadata writes, seconds from start |
|---|---|
| quiet | None |
| transient | Every second 24 through 40 inclusive |
| persistent | Every second 24 through 66 inclusive |
| resumes | Every second 24 through 28, then 35 through 66 inclusive |

A separate controller follows this calendar without reading decisions, worker
readiness or dispatch barriers. It changes only a declared annotation under a UID
condition. Each attempt begins within one second of schedule and finishes within
1.5 seconds. Independent API records attribute all controller and broker writes.

**All arms have an artificial two-second pause after every prepared broker request
and before dispatch**, including refreshed attempts. Release must occur between
two and three seconds after its barrier. This uses existing experimental hooks to
expose the conditional-write race with modest traffic. It is a declared stress
condition, not measured production transport latency. The pause never depends on
context. Existing fresh diagnosis, conditional writes and independent customer
verification remain mandatory. An API acknowledgement is not a success label.

## Frozen development decision

This new objective allows limited waiting cost; it differs from PR19's zero-
regression rule. Weight each authored context equally, without claiming a measured
production distribution. Require valid complete evidence and eligible fixed
comparators in every context. Advance observation-based timing **only to fresh
confirmation** if it is eligible everywhere, gains at least two healthy windows
in the four-context sum against each comparator, loses at most one window in any
context against either, and spends no more total dispatches than either.

Otherwise close this information hypothesis and keep the maintained operator.
Measurement failure blocks the decision and is distinct from a valid negative
result. Show all individual outcomes and observation costs. A positive screen
confers no authority or claim of statistical superiority, generalization, learning,
human-work savings or ROI. Confirmation and persistent reuse need separate frozen
protocols with relevant safety/regression cases.

## Evidence and cost

Pin source, program, calendar, rule, seeded order and three disjoint shards before
provisioning. Attempt each case once; retain failures and unrun cases. No automatic
retry or favorable-subset selection. Corrections need separately retained cohorts.
Offline reproduction reconstructs raw customer verdicts, all selector choices,
operation/program bindings, namespace mutations, controller timing, the common
dispatch delay, cumulative budget, unchanged workload identities and cleanup.
Repeat exports must agree before whole-cohort selection.

The twelve calendars total eighteen workload-minutes before setup, teardown,
regressions and review. Three shards have thirty-minute caps. Zero proposer calls.
Retain failed qualification cost; report reads, waiting and CI duration. Missing
invoices and human active time stay unknown. This is one routing fault with authored
metadata interference on a trusted host, not production availability or indefinite
ownership. The [workflow](../.github/workflows/information-gate.yml) uses freeze,
run and reproduce commands and uploads only allowlisted credential-free evidence.

## Implementation correction after the first cohort

Source `e0b38b5` attempted all twelve cases; six passed and six failed, so no
selection occurred. Two completed cases exposed an evaluator assumption that
every journal entry is a dispatch: the broker had correctly refused a changed
resource version before sending a request and released that unsent reservation.
The corrected checker separates those refusals, requires their original
prepared/rejected/budget-released history and unique episode evidence, and still
attributes every actual API request. A dispatched rejection remains spent.

Four other cases retained complete customer calendars but lacked normal owner
completion and final identity inventory after a response-monitor RuntimeError.
The source permits time to cross the window end between the loop condition and
`active()`; the finalizer then interrupts the owner's normal completion. A
deterministic clock-crossing test reproduces this race. The monitor now ends at
the already-declared response deadline (65 seconds), leaving the observer and
owner to complete the unchanged 90-second calendar. Failures also retain their
stage. All original clusters were cleaned up, four through emergency cleanup;
missing final inventories are not reclassified as unchanged resources.

The original source, records and incomplete decision remain retained. A separate
cohort qualifies the correction. Policies, authority, interventions, measurement
calendar and advancement thresholds are unchanged.
