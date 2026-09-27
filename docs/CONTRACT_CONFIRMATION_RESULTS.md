# Fresh cohort: customer benefit observed, confirmation withheld

26 September 2026. Eight real campaigns; no retries or model calls.

The [prospective protocol](CONTRACT_CONFIRMATION_GATE.md) was committed at
4ed0226 before implementation. The original cohort ran source
bd63ed30269ac85e6aec5a80d0fbb1d56591f437. Its 62 pinned runtime dependencies,
maintained procedure bytes and both combined candidate identities equal PR23.
The experiment controller/evaluator lived outside that unchanged runtime.

## Observed customer outcomes

| Context | Legacy healthy samples / 21 | Precise / 21 | API requests per arm | Remaining after first response, legacy / precise |
|---|---:|---:|---:|---:|
| Two heartbeat updates before dispatch | 11 | 17 | 2 | 0 / 1 |
| Heartbeat plus unrelated annotation | 11 | 11 | 2 | 0 / 0 |
| Heartbeat excursion and return | 11 | 17 | 2 | 0 / 1 |
| Heartbeat after acknowledged repair | 17 | 17 | 2 | 1 / 1 |

All 168 scheduled customer samples were measured with no unknowns. All eight
cases were eligible under the original case evaluator; every case export
reproduced before qualification. Each arm sent eight real broker requests across
four cases. All eight owned clusters were deleted. Each case retained one real
workload for 210 seconds, three operator starts and two cumulative dispatch slots.

The two observed gains extend the original mechanism: an irrelevant conditional
rejection consumes capacity needed for recurrence. Precise retained one slot and
repaired the later fault in both the burst and return contexts. The protected
annotation still forced both contracts to reject and refresh. Neither arm had
capacity for its later recurrence. The post-acknowledgement context tied.
These are sampled observations in authored contexts, not continuous uptime,
production incident frequencies, model discovery or autonomous learning.

## Why the gate did not advance

The final adversarial qualification failed with `KeyError: 'labels'`. The
`altered_intermediate` corruption builder assumed that the real Service response
had a metadata labels map. Kubernetes permits that map to be absent. The builder
crashed before the intended full-resource effect check; a crash cannot qualify
the negative control. The original selection remains null.

The exact original offline replay reproduces the same incomplete result and
failure. The builder now creates the map if absent, with regression tests for
both absent and existing labels. It changes the copied evidence only. A separately
identified post-hoc checker then passes all 21 intended corruption controls against
copies of the original raw evidence, using the immutable original case evaluator.
Original artifact bytes remain unchanged. This corrects the test infrastructure;
it does not retroactively pass the frozen confirmation gate.

Per the preregistered rule, the cohort is retained as **development evidence**.
Automatic PR execution of this corpus is disabled. Any future manual use is a
development regression and cannot claim fresh confirmation. No case was rerun,
discarded, or replaced. Admission and deployment remain unchanged.

## Review and evidence

Fable completed four bounded source reviews before the cohort. Accepted findings
improved recurrence-precondition coverage and execution/retention timeout bounds.
One oversized scope stopped before generation and one response was incomplete;
neither was approval. Other claims were checked against exact dependencies and
retained with their dispositions. The absent-label construction defect was found
by the real cohort's adversarial qualification, despite those reviews.

An additional standard-library audit reconciles raw API requests, journal budgets,
every intermediate controller state, post-acknowledgement ordering and customer
sample counts. It is an implementer-authored cross-check, not an external audit.
Completed verification records are retained, but interrupted verification and
diagnosis work remain incompletely counted. No full cost or ROI claim is supported.

- [Original live cohort and failed qualification](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36291403227)
- [Original source](https://github.com/rvharsha/Autonomy-Lab/tree/bd63ed30269ac85e6aec5a80d0fbb1d56591f437)
- [PR24](https://github.com/rvharsha/Autonomy-Lab/pull/24)

The next authority decision remains withheld. A separately declared fresh
confirmation must precede combined admission; repeating this now-exposed matrix
cannot supply it. Adding admission runtime code will itself create a new runtime
identity and require explicit qualification. The long-term target remains one
persistent service adopting an evaluated improvement under revocable authority.
