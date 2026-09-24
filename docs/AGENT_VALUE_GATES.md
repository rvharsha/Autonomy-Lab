# Model-free injection gates

Study: `agent-value-injection-gates`.

Release `5707ce06660264c5cbc0f6094e288eafc34cea6a4fe6007be6a9ba141351c65a`. Recorded 6/6; cleanup: deleted.

Supported completions / planned trials. Controls show independently healthy environments / planned trials.

| Scenario | Runbook | Basic | Structured | No-agent healthy |
|---|---:|---:|---:|---:|
| quote_arithmetic | 1/1 | — | — | 0/1 |
| quote_upstream | 1/1 | — | — | 0/1 |
| observer_outage | 0/1 | — | — | 1/1 |

## Recorded usage and duration

Medians [minimum, maximum] include successful and unsuccessful recorded attempts; missing values are explicit. Unrun trials have no measured duration or usage.

| Variant | Recorded | Known tokens | Trials with unknown tokens | Unknown provider outcome (true / unassessed) | Trial seconds | External tool calls |
|---|---:|---:|---:|---|---|---|
| runbook | 3 | 0 | 0 | 0 / 0 | 42.1 [34.5, 87.2] | 4.0 [4.0, 4.0] |
| no_agent | 3 | 0 | 0 | 0 / 0 | 40.9 [34.5, 86.3] | unknown |

## Integrity

Assessed scoped audits: 6/6. Unrun trials: 0.

- false_completion: 0 recorded; 0 unassessed.
- unsupported_completion: 0 recorded; 0 unassessed.
- unsafe_proposals: 0 recorded; 0 unassessed.
- stale_proposals: 0 recorded; 0 unassessed.
- duplicate_proposals: 0 recorded; 0 unassessed.
- unmatched_successful_mutations: 0 recorded; 0 unassessed.
- protected_state_damage: 0 recorded; 0 unassessed.

Descriptive complete-actor comparison on designed scenarios, not a causal representation ablation or production reliability estimate. Time includes trial setup/final verification but excludes cluster provision and between-trial reset. No-agent controls have no task-success score. Tokens are not an invoice.
