# Release candidate review

Candidate `5ab2ebfd8cda7b96a86688840e76ec15951c42dd` adds evidence-supported
escalation guidance and low thinking for Gemini 3.8 Flash, preserving the model,
trial budgets, scorer, broker authority and independent verification. All 693
tests and lint pass locally. The live results and CI are reported separately.

Three further direct Anthropic Claude Fable 5.1 reviews completed: full agent
source, transport components, and the final remedial diff with complete relevant
functions. Two larger inputs stopped at token preflight without generation.
The agent's successful review supplied its complete source without display-only
line-number prefixes, within the original token and cost bounds. Coverage,
findings, hashes and usage are in the [selected ledger](validation/release-reviews.json).

Checked dispositions:

- **Accepted: response accounting checked too late.** Known total usage was
  recorded before tool execution, but an invalid thought-token reservation basis
  was rejected only at the next model preflight. The same validation now runs
  before tools are queued. Six cases check both variants, zero repair dispatch,
  retained known usage, and no dispatch or paid retry after restart.
- **Accepted: oversized responses lost known HTTP status.** Gemini now retains
  that status while leaving response contents, usage and completion unknown.
  Four cases check count/generation and HTTP 200/503 without retry. The claim
  that a 200 header alone proves a complete result or known bill was rejected.
  Kubernetes still requires its valid response/journal reconciliation contract;
  an oversized response is not converted to a fabricated acknowledgement.
- **Rejected: an interrupted finish necessarily replays blindly.** The actual
  toolbox reconstructs its terminal claim from the durable evidence log, and
  the runner checks that terminal before processing the pending queue. Existing
  real terminal-crash evidence also exercises this boundary. The finding assumed
  omitted toolbox behavior; no new ambiguous retry policy was added.
- The final scoped remedial review found no substantiated defect. Its two
  conditions were checked: model call count increments before generation and
  response validation; forwarded status is metadata and is not used as proof of
  a complete response or a known provider bill. Incomplete responses execute no
  tools.

The self-review also confirmed the escalation instruction requires actual current
backend and Service observations, leaves uncertain-operation lookup mandatory,
and requires current verification after repair. Historical events cannot replace
current evidence. Low thinking is set by the common count/generation payload
builder only for the selected model; other model families receive no unsupported
thinking setting. This is a combined treatment, not an attribution experiment.

These reviews supplement the previous 21 runtime reviews. Model source review,
authored unit tests, real runtime gates and model evaluations are distinct kinds
of evidence; none independently establishes production reliability.

## Reconciliation prompt follow-up

One further direct Fable review covered the prompt-only follow-up on `5369e13`,
with the surrounding usage guards supplied in full. The final wording on
`a38b0d0` explicitly requires reconciliation against current read-only evidence,
states that a known journal record is not completion, and forbids redispatch
merely because verification reports failure. All 132 agent protocol tests passed
after that clarification; the exact candidate also passed [693 tests, lint and
17 real Kubernetes CI checks](validation/reconciliation-ci.json).

The review's acknowledgement-only prerequisite for verification was rejected:
uncertain operations require independent observation to reconcile their outcome.
Verification cannot mutate or decide completion, and the proposed `failed` and
`in_progress` statuses are not broker states. No repair or completion decision is
batched with unseen results. The [selected review](validation/reconciliation-review.json)
records the exact snapshot, finding, clarification and disposition; it does not
claim that the later wording received a second source review.

This brings the runtime/release sequence to **25 completed Fable reviews**.
Their combined API cost estimate is **$9.17381**, not an invoice. Preflight stops
and the earlier incomplete response are retained separately and are not counted
as completed reviews. Live evaluation and runtime evidence remain separate from
these source reviews.

The completed [follow-up evaluation](RECONCILIATION_RESULTS.md) failed its declared promotion gate. The prompt-only follow-up is not shipped: the agent source was restored exactly to the previously reviewed and validated `5ab2ebf` candidate. [Source selection evidence](validation/release-selection.json) verifies every executable release file.
