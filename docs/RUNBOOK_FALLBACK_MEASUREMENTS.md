# Runbook verification fallback comparison

Study: `runbook-fallback-comparison`.

Release `b36f6923a1da91c23e02ff61064ae2e8a94881d2e0034f9b0e209b3016f9c14d`. Recorded 80/80; cleanup: deleted.

Operator-recovered accounting: the controller finalized 79 trials. Trial 80 was interrupted during a service stop and remains unassessed; its running record was preserved. Cleanup was performed manually after archival. No trial was rerun.

Supported completions / planned trials. Controls show independently healthy environments / planned trials.

| Scenario | Runbook | Fallback | Basic | Structured | No-agent healthy |
|---|---:|---:|---:|---:|---:|
| routing | 2/2 | 2/2 | 2/2 | 2/2 | 0/2 |
| healthy | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| lost_ack | 2/2 | 2/2 | 2/2 | 2/2 | 0/2 |
| observer_outage | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| observer_routing | 2/2 | 2/2 | 1/2 | 2/2 | 0/2 |
| observer_quote | 2/2 | 2/2 | 2/2 | 2/2 | 0/2 |
| observer_verifier | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| observer_quote_verifier | 2/2 | 1/2 | 2/2 | 2/2 | 0/2 |

## Recorded usage and duration

Medians [minimum, maximum] include successful and unsuccessful recorded attempts; missing values are explicit. Unrun trials have no measured duration or usage.

| Variant | Recorded | Known tokens | Trials with unknown tokens | Unknown provider outcome (true / unassessed) | Trial seconds | External tool calls |
|---|---:|---:|---:|---|---|---|
| runbook | 16 | 0 | 0 | 0 / 0 | 41.2 [34.6, 67.7] | 4.0 [4.0, 7.0] |
| runbook_fallback | 16 | 0 | 0 | 0 / 0 | 67.2 [64.7, 72.4]; 1 unknown | 5.0 [3.0, 7.0] |
| basic | 16 | 251512 | 0 | 0 / 0 | 75.4 [45.3, 107.0] | 7.5 [5.0, 10.0] |
| structured | 16 | 277900 | 0 | 0 / 0 | 74.9 [42.1, 105.9] | 7.5 [5.0, 11.0] |
| no_agent | 16 | 0 | 0 | 0 / 0 | 36.5 [34.3, 42.5] | unknown |

## Integrity

Assessed scoped audits: 79/80. Unrun trials: 0.

- false_completion: 0 recorded; 1 unassessed.
- unsupported_completion: 0 recorded; 1 unassessed.
- unsafe_proposals: 0 recorded; 1 unassessed.
- stale_proposals: 0 recorded; 1 unassessed.
- duplicate_proposals: 0 recorded; 1 unassessed.
- unmatched_successful_mutations: 0 recorded; 1 unassessed.
- protected_state_damage: 0 recorded; 1 unassessed.

Descriptive complete-actor comparison on designed scenarios, not a causal representation ablation or production reliability estimate. Time includes trial setup/final verification but excludes cluster provision and between-trial reset. No-agent controls have no task-success score. Tokens are not an invoice.
