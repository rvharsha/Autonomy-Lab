# Funded Fable review follow-up

After the Anthropic account was funded, Claude Fable 5.1 completed **13 bounded
source reviews** directly through `api.anthropic.com`. Two larger scopes stopped
at token counting with zero generation requests; smaller scopes covered their
files without increasing the limits. The [selected review ledger](validation/funded-review-summary.json)
retains every final answer, disposition, source hash, token usage and estimated
cost. This round used an estimated **$4.49065** from observed provider tokens at the recorded rates; this is not an invoice. These are source-review opinions, not test executions or merge approval.

## Changes and checked findings

| Finding | Disposition and validation |
|---|---|
| A public `prepared` proposal can later be dispatched in its durable journal, after cited verification. | Fixed: invalidate old verification using both public and durable dispatch possibility. The authored scoring regression failed before the fix. All 54 retained actual trial scores remain unchanged. |
| Case variants of `Accept-Encoding` could survive the identity override. | Fixed with case-insensitive headers. A real loopback server observes exactly one `identity` value. |
| An unknown native SIGALRM handler cannot be restored safely. | Refuse it before mutation; do not replace it with the default handler. The test models the documented unknown-handler boundary. |
| A pending alarm could interrupt cancellation or cleanup and leave the handler installed. | Disable late callbacks and use nested cleanup guarantees. Tests deliver real SIGALRM during cancellation and at cleanup entry; timer and prior handler are restored. |
| SQLite export contexts did not close their connections. | Explicitly close harness and experiment export connections. A real SQLite test confirms closure even on the primary-failure path. |
| A newly appended evidence file lacked a directory flush. | Flush the parent directory after the journal file before returning evidence. A test observes actual file and directory fsync calls. |
| Crash-journal inspection could create a missing SQLite file and omit a named failure. | Inspect read-only and record unreadable-journal failures. Missing/corrupt-file boundary tests preserve the original state. |
| JSON report replacement could truncate an earlier completed record. | Stage, fsync, atomically replace, and flush the directory. A forced publication failure preserves the original bytes and removes the temporary file. |

The final diff review found an additional cleanup-entry signal window; the
nested cleanup fix and regression address it. The subsequent focused review
confirmed handler restoration but argued that a response arriving near the
deadline should avoid a cleanup-edge timeout. That recommendation was rejected:
the total deadline includes cleanup, and received bytes are not yet a validated
Service acknowledgment. Uncertainty remains the correct outcome if the bounded
operation does not return successfully. Its assertion that the cancellation
test cannot pass is contradicted by the executed test and overlooks the
inactive callback at that injection point.

Other findings were rejected after checking the omitted callers:

- Terminal state survives agent interruption because a fresh `ObservationTools`
  replays the durable finish claim. Basic and structured tests use the real
  journal and a model double; both resume without token-count or generation
  calls, and without changing journal bytes. These are authored regression
  tests, not live-model outcomes.
- The broker normalizes request defaults before persisting them. Its lookup
  and public tool view return the same stored request, so exact uncertainty
  binding is intentional.
- Readiness observed after its declared deadline remains a failure; later
  success cannot silently extend the allowance.
- An oversized HTTP body cannot establish a valid Service acknowledgment from
  its status alone. Oversized `finish` results are explicit tool errors, not
  accepted claims; a compact corrected claim can subsequently succeed.
- Keeping the independent broker alive during agent-only resumption does not
  bypass durable state: every broker operation opens and closes SQLite and
  reads its journal. The experiment comment now states that boundary clearly.
- A claimed missing `release_id` in the restart test overlooked its local
  wrapper. The final follow-up included that wrapper and corrected the finding.

The AX policy patch also received a bounded review against pinned source
excerpts. Existing templates retain their old policy, so its documentation now
requires a fresh isolated deployment. This remains an experimental patch:
the previously recorded **one-of-three-cycle failure** is unchanged, and no
new runtime success is claimed.

## Validation and coverage

**644 tests and Ruff passed locally.** The added checks distinguish actual
loopback traffic, SQLite/file operations and signal delivery from authored
record shapes and boundary injections. Offline rescoring used the original
28-trial pilot and 26 completion-comparison/regression trials: all 54 score
records are unchanged, input hashes still match, and no model or infrastructure
calls were made. Historical runs remain bound to their original releases.

Coverage combines full component snapshots with subsequent explicit diffs and
named-function context. Most broad requests include test names rather than
test bodies; the ledger identifies exactly what was supplied. Current runtime
file hashes and the preceding review hashes are retained separately. Private
thinking, provider credentials and raw responses are excluded from the published
ledger. Final pushed-commit CI is recorded on the PR.

The credit blocker is resolved. Remaining architecture gates are reliable AX
recovery and broker integration, controller-death cleanup, isolated execution,
independent auditing, fresh held-out evaluation and GCP deployment. This review
round does not close those gates or authorize a merge.
