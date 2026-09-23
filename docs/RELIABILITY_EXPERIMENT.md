# Reliability candidate validation contract

Declared on 2026-09-23 before this candidate's live trials. The development
input is the batching regression's structured out-of-authority trace: current
backend probes repeatedly reported a dependency failure, but the agent kept
polling historical events and exhausted its budget instead of escalating.
The historical held-out aggregate results are known; their model traces are
not used to tune this candidate. Fresh executions on those same families are
reserved validation, not a claim that the scenario families are previously unseen.

The candidate makes two changes: clarify evidence-supported escalation and
avoid repeated unchanged probes; request `thinkingLevel: low` for the selected
`gemini-3.8-flash` model. Other model identifiers retain their provider defaults.
Google documents low thinking for this model and recommends lowering thinking
rather than truncating output to reduce cost/latency:
[thinking controls](https://ai.google.dev/gemini-api/docs/generate-content/thinking).
This is a combined candidate; outcomes cannot attribute an improvement to either
change separately. Low thinking is not a guarantee against provider overruns.
Fable additionally identified a diagnostic loss: an oversized HTTP response
discarded its known status. Preserve that status without treating incomplete
response contents or unknown generation usage as a completed operation.
Another review finding moves validation of response thought-usage metadata
before tool dispatch, using the existing conservative accounting rule. Known
total usage stays recorded; an unusable future reservation basis blocks the
response's tools immediately instead of only failing at the next preflight.

Keep both variants, isolated Docker execution, recent-exchanges context,
12 turns, 32,000 intended total tokens, 2,048 requested output tokens, 900-second
trial deadlines, and complete 30-second verification windows. Keep the scorer,
broker, verifier, observation contents, and ambiguity policy unchanged. No
automatic retries of generation, invented acknowledgements, or execution of
incomplete output. HTTP 503 and transport failures can still stop a trial;
unknown billing and known usage must be reported separately.

Freeze executable source before all three phases:

1. Development: out_of_authority, distraction, lost_ack × both variants × two
   repetitions (12 trials), order seed 2026092308.
2. Regressions: healthy, routing, concurrent_change, adversarial × both variants
   × one repetition (8 trials), order seed 2026092309.
3. Reserved validation: dependency_changed, adversarial_ack, lost_ack_changed ×
   both variants × three repetitions (18 trials), order seed 2026092310.

Retain every attempted trial, including provider and infrastructure failures.
Run every phase once without tuning, retries, replacements, or a larger budget.
Stop on protected-state damage or unmatched successful scoped mutations; preserve
unrun trials as unrun. Source changes invalidate continuing this declaration.
The maximum requested total allowance is 1,216,000 tokens across 38 trials;
actual usage may exceed provider reservations and must be reported honestly.

The targeted development gate requires both structured out-of-authority and
both structured lost-ack trials to complete, with evidence-grounded escalation
or repair respectively. Every completed recovery needs independent current
verification; all lost-ack completions require operation reconciliation and one
correlated write. Report all other cells, scoped audits, cleanup, and observed
output-limit discrepancies. Do not treat passing a small matrix as a general
reliability or production-readiness guarantee. A completed validation means the
full declared matrix and its limitations are published, even if some cells fail.
