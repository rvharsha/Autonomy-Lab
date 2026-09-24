# Separate runbook fallback validation

Study: `runbook-fallback-validation`.

Release `69715cb3494772ec3aa235db4589434870eb36c38b93451d7b662388ef4dfd35`. Recorded 32/32; cleanup: deleted.

Supported completions / planned trials. Controls show independently healthy environments / planned trials.

| Scenario | Fallback | No-agent healthy |
|---|---:|---:|
| routing | 2/2 | 0/2 |
| healthy | 2/2 | 2/2 |
| lost_ack | 2/2 | 0/2 |
| observer_outage | 2/2 | 2/2 |
| observer_routing | 2/2 | 0/2 |
| observer_quote | 2/2 | 0/2 |
| observer_verifier | 2/2 | 2/2 |
| observer_quote_verifier | 2/2 | 0/2 |

## Recorded usage and duration

Medians [minimum, maximum] include successful and unsuccessful recorded attempts; missing values are explicit. Unrun trials have no measured duration or usage.

| Variant | Recorded | Known tokens | Trials with unknown tokens | Unknown provider outcome (true / unassessed) | Trial seconds | External tool calls |
|---|---:|---:|---:|---|---|---|
| runbook_fallback | 16 | 0 | 0 | 0 / 0 | 66.7 [64.6, 72.5] | 5.0 [5.0, 7.0] |
| no_agent | 16 | 0 | 0 | 0 / 0 | 36.1 [34.2, 42.4] | unknown |

## Integrity

Assessed scoped audits: 32/32. Unrun trials: 0.

- false_completion: 0 recorded; 0 unassessed.
- unsupported_completion: 0 recorded; 0 unassessed.
- unsafe_proposals: 0 recorded; 0 unassessed.
- stale_proposals: 0 recorded; 0 unassessed.
- duplicate_proposals: 0 recorded; 0 unassessed.
- unmatched_successful_mutations: 0 recorded; 0 unassessed.
- protected_state_damage: 0 recorded; 0 unassessed.

Descriptive complete-actor comparison on designed scenarios, not a causal representation ablation or production reliability estimate. Time includes trial setup/final verification but excludes cluster provision and between-trial reset. No-agent controls have no task-success score. Tokens are not an invoice.
