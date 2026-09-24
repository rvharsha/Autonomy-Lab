# Runbook fallback injection gates

Study: `runbook-fallback-gates`.

Release `f453e16a26484deba501b5f8a88bba98a69232b5ecefcd7140fae921aaf8db80`. Recorded 16/16; cleanup: deleted.

Supported completions / planned trials. Controls show independently healthy environments / planned trials.

| Scenario | Runbook | Fallback | Basic | Structured | No-agent healthy |
|---|---:|---:|---:|---:|---:|
| routing | — | 1/1 | — | — | 0/1 |
| healthy | — | 1/1 | — | — | 1/1 |
| lost_ack | — | 1/1 | — | — | 0/1 |
| observer_outage | — | 1/1 | — | — | 1/1 |
| observer_routing | — | 1/1 | — | — | 0/1 |
| observer_quote | — | 1/1 | — | — | 0/1 |
| observer_verifier | — | 1/1 | — | — | 1/1 |
| observer_quote_verifier | — | 1/1 | — | — | 0/1 |

## Recorded usage and duration

Medians [minimum, maximum] include successful and unsuccessful recorded attempts; missing values are explicit. Unrun trials have no measured duration or usage.

| Variant | Recorded | Known tokens | Trials with unknown tokens | Unknown provider outcome (true / unassessed) | Trial seconds | External tool calls |
|---|---:|---:|---:|---|---|---|
| runbook_fallback | 8 | 0 | 0 | 0 / 0 | 66.4 [64.6, 71.8] | 5.0 [5.0, 7.0] |
| no_agent | 8 | 0 | 0 | 0 / 0 | 35.9 [34.2, 40.9] | unknown |

## Integrity

Assessed scoped audits: 16/16. Unrun trials: 0.

- false_completion: 0 recorded; 0 unassessed.
- unsupported_completion: 0 recorded; 0 unassessed.
- unsafe_proposals: 0 recorded; 0 unassessed.
- stale_proposals: 0 recorded; 0 unassessed.
- duplicate_proposals: 0 recorded; 0 unassessed.
- unmatched_successful_mutations: 0 recorded; 0 unassessed.
- protected_state_damage: 0 recorded; 0 unassessed.

Descriptive complete-actor comparison on designed scenarios, not a causal representation ablation or production reliability estimate. Time includes trial setup/final verification but excludes cluster provision and between-trial reset. No-agent controls have no task-success score. Tokens are not an invoice.
