# Reconciliation follow-up contract

Declared after the complete 38-trial candidate `5ab2ebf` finished, before any
live call on this follow-up. Its original results remain 12/12 development,
8/8 regressions, and 16/18 reserved validation. Two basic combined
lost-ack/dependency-change cases exhausted their budgets. Both public tool traces
showed operation lookup, verification, then separate Service and backend refresh
turns, leaving too little budget for the next decision.

Make one prompt-only change shared by both variants: after an uncertain repair's
journal lookup returns, group `observe_service`, `probe_backend`, and
`verify_recovery` in one model response. These read-only calls have independently
known arguments. Their results are awaited before the next repair or completion
decision. Preserve the prior operation lookup, every observation, actual
verification, incident-before-repair ordering, and a separate terminal decision.
No predetermined diagnosis or fabricated acknowledgement is supplied.

Keep Gemini 3.8 Flash with low thinking, recent-exchanges context, isolated Docker
execution, 12 turns, the 32,000-token target, requested output limit 2,048,
900-second trial deadlines and 30-second recovery verification windows. Keep the
scorer, harness, broker and verifier unchanged. No generation retry or passing
replacement. The earlier 38-trial source stays recorded separately.

Freeze source before two phases, each attempted once without intervening edits:

1. Development: `lost_ack_changed` × both variants × three repetitions (6 trials),
   order seed 2026092311. This family is now explicitly development data because
   its failed traces informed the prompt change.
2. Reserved regression validation: the other nine existing families × both
   variants × one repetition (18 trials), order seed 2026092312. These are fresh
   executions on known families, not a claim of previously unseen scenarios.

The promotion gate requires all six targeted development cases to complete,
with one correlated repair, external uncertainty reconciliation, current verified
failure and supported escalation; all 18 regressions must complete with their
existing expected behavior. All audits must be assessed without unmatched
successful mutations, duplicate proposals, protected-state damage or false
completion claims. Both clusters must be deleted. Stop immediately on protected
state damage or an unmatched successful scoped mutation. Retain unrun and failed
cases as such. If the gate fails, retain the earlier candidate for release and
report the unresolved limitation, rather than trying an undeclared prompt series.

Maximum additional requested allowance: 768,000 tokens across 24 trials. Retain
host-reported usage, unknown outcomes and any provider reservation overruns.
Passing this small matrix does not establish general or production reliability.

Reproduce on the source commit recorded in the results:

```sh
PYTHONPATH=src .venv/bin/python -m autonomy_lab.cli experiment --manifest scenarios/reconciliation-development.yaml --env-file ~/Dev/.env
PYTHONPATH=src .venv/bin/python -m autonomy_lab.cli experiment --manifest scenarios/reconciliation-validation.yaml --env-file ~/Dev/.env
```
