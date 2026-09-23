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
