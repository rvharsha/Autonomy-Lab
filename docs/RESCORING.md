# Historical scoring audit

The scorer at commit `9004ed51abda49e4ef245b9a416e135e248dacd8` was applied to the original persisted observations, operation records, terminal claims, and final verification of two historical development runs. **None of the nine completed trials changed any existing score metric or headline outcome.** This was an offline audit: no model requests or experiment reruns occurred, and the original artifacts were not rewritten.

| Historical run | Completed trials rescored | Observed task success | Environment recovered |
|---|---:|---|---|
| `experiment-ea63fad3` | 2 | 1 success, 1 non-success | 2 of 2 |
| `experiment-0db726fd` | 7 | 4 successes, 1 non-success, 2 inapplicable no-agent controls | 5 of 7 |

Both recorded structured-agent non-successes remain non-successes: the agents exhausted their token budgets before recording a terminal claim, even though their environments recovered. Rescoring does not repair historical token accounting or execution defects, and these development runs do not establish comparative reliability. No completed trial in these two runs exercised an uncertain operation; the new reconciliation metric is therefore inapplicable here.

The stopped pilot declared 28 trials. Its derived accounting is **7 completed with scores, 1 started without a final verification, and 20 not started**. `trial-008` retains its original `running` trial status and recorded budget-exhausted agent state. Because it lacks final verification, this audit assigns it **no score**. The original accounting file lists that started trial among 21 unrun trials; that original file remains unchanged.

Only the derived audit corrects event-presence metadata: stopped-pilot `trial-003` and `trial-007` contain operational events inside their `observe_service` observations, so their derived `operational_events_observed` value is true instead of the original false. This does not change their scores. Injected-text exposure is a separate measure and was not rewritten.

## Provenance

Both original release manifests record scorer SHA-256 `d2c4d577c48725dd5fcf4ce00a0f672ab3b5cb8a2bfcb6c5cad06d57fb4a1135`. The audited current scorer SHA-256 is `dcb54d65ef455d3af7048a044d7c5ff0bb9959519fee2f4f0c3e4d82ba4fc04e`.

The local derived report is `.state/audits/historical-rescoring-dcb54d65ef45.json`; its SHA-256 is `da84b8aefbed5d2f9fa1b32360bd1871e5b503d57adf3647fd70852662097ae8`. It retains original and current scores, added metrics, observation IDs supporting event presence, and individual input-file hashes. The local reproduction script is `.state/audits/rescore_historical.py`. These ignored local audit files contain no kubeconfigs, credentials, or provider responses.

| Historical run | SHA-256 of the sorted input artifact hash index |
|---|---|
| `experiment-ea63fad3` | `329a00e3b5ad88d69a39ffcc85219d0efa76ffb8a3167a069ba917811378b822` |
| `experiment-0db726fd` | `b202714af94e6e645ff18efe0cf9bef6c43a3c8eadfa2ebe0932d240875aebeb` |

The index covers original manifests, releases, accounting, results, cleanup, and available per-trial metadata, observations, operations, and final verification. Every hashed input was checked again after scoring and remained byte-for-byte unchanged. The index digest hashes Python's `json.dumps(index, sort_keys=True)` UTF-8 representation.
