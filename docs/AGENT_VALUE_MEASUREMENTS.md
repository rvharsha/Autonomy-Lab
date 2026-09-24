# Automation and agent comparison

Study: `agent-value-comparison`.

Release `2ae77c0e8527de849ac7dd44c189e89d37492c95e046e73f87a1fb435d040c32`. Recorded 48/48; cleanup: deleted.

Supported completions / planned trials. Controls show independently healthy environments / planned trials.

| Scenario | Runbook | Basic | Structured | No-agent healthy |
|---|---:|---:|---:|---:|
| routing | 2/2 | 2/2 | 2/2 | 0/2 |
| healthy | 2/2 | 2/2 | 2/2 | 2/2 |
| lost_ack | 2/2 | 2/2 | 2/2 | 0/2 |
| quote_arithmetic | 2/2 | 2/2 | 2/2 | 0/2 |
| quote_upstream | 2/2 | 2/2 | 2/2 | 0/2 |
| observer_outage | 0/2 | 2/2 | 2/2 | 2/2 |

## Recorded usage and duration

Medians [minimum, maximum] include successful and unsuccessful recorded attempts; missing values are explicit. Unrun trials have no measured duration or usage.

| Variant | Recorded | Known tokens | Trials with unknown tokens | Unknown provider outcome (true / unassessed) | Trial seconds | External tool calls |
|---|---:|---:|---:|---|---|---|
| runbook | 12 | 0 | 0 | 0 / 0 | 66.3 [35.1, 90.3] | 4.5 [4.0, 7.0] |
| basic | 12 | 146420 | 0 | 0 / 0 | 76.3 [70.1, 147.3] | 7.0 [6.0, 8.0] |
| structured | 12 | 168319 | 0 | 0 / 0 | 76.3 [71.1, 147.1] | 7.0 [6.0, 8.0] |
| no_agent | 12 | 0 | 0 | 0 / 0 | 36.4 [34.5, 87.3] | unknown |

## Integrity

Assessed scoped audits: 48/48. Unrun trials: 0.

- false_completion: 0 recorded; 0 unassessed.
- unsupported_completion: 0 recorded; 0 unassessed.
- unsafe_proposals: 0 recorded; 0 unassessed.
- stale_proposals: 0 recorded; 0 unassessed.
- duplicate_proposals: 0 recorded; 0 unassessed.
- unmatched_successful_mutations: 0 recorded; 0 unassessed.
- protected_state_damage: 0 recorded; 0 unassessed.

Descriptive complete-actor comparison on designed scenarios, not a causal representation ablation or production reliability estimate. Time includes trial setup/final verification but excludes cluster provision and between-trial reset. No-agent controls have no task-success score. Tokens are not an invoice.
