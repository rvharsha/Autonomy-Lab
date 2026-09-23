# Fable review results

The [funded follow-up](FUNDED_REVIEW.md) completed 13 additional direct Anthropic reviews, fixed substantiated findings, and checked rejected findings against their callers. The credit blocker is resolved. The records below describe the earlier rounds and their historical coverage boundaries.

Claude Fable 5.1 completed eight initial component reviews covering 15 runtime files, six remediation reviews, and two focused patch reviews. The last review also covered the complete current Gemini transport and CLI. The implementation received local engineering review and executed regression tests. Reviewer responses are source-review opinions, not test results or merge approvals.

The [component review ledger](validation/component-review-summary.json), [remediation reviews](validation/remediation-review-summary.json), [first patch review](validation/final-patch-review-summary.json), and [agent follow-up](validation/agent-followup-review-summary.json) contain final answers, usage, snapshot hashes, and incomplete attempts. Recorded and estimated review costs total **$11.441595**, including earlier failed attempts; this is not an invoice. The first patch request's initial attempt failed TLS during preflight with zero generation requests; one authorized retry completed.

The original broad CLI attempt and two broad API reviews exhausted their output budgets without final findings. They are recorded as incomplete and were not counted as reviews. A large combined tools/scoring request stopped at token preflight without generation. Smaller, bounded component requests returned final findings successfully.

The agent follow-up stopped twice at the unchanged 8,000-input-token gate (11,594 and 8,208 tokens), with zero generation requests. Removing unchanged agent code and formatting overhead produced a 7,716-token request; one generation completed for an estimated $0.22706. Its agent scope includes the changed guards and calling context, not a new review of the omitted unchanged execution body. Full Gemini and CLI source were included. No further paid review requests followed.

## Verified findings addressed

| Area | Change | Validation |
|---|---|---|
| Broker budget | Release a reservation on rejection before dispatch; keep it spent after an API dispatch, including rejection. | Stale evidence, policy/budget revocation, and API-rejection regression cases. |
| Broker acknowledgement | Malformed or contradictory acknowledgement becomes uncertain; never automatically send it again. | Invalid metadata, unchanged version, incorrect named port, and nested-shape cases. |
| Agent checkpoint | Persist response, usage, message content, and pending tool queue together. | Crash before/after the atomic checkpoint; pending billed request never replays. |
| Checkpoint loading | Preserve terminal states; reject incompatible or malformed required resume fields through a separate error record. Failure to write that record never falls back to overwriting the original. | Byte/mtime preservation, zero provider/tool calls, sidecar-write failure, and eight checks using copies of real pilot checkpoints. |
| Agent incident state | Invalid model-authored state returns a durable rejection without changing incident memory. | Invalid state and resumed rejection cases. |
| Token budget | Reserve prior thinking omitted from the observed token-count result; validate direct or arithmetically derived usage. | Live metadata pattern, strict accounting boundaries, missing/malformed usage, and interrupted requests. |
| Interruptions | Reject unavailable interruption-tool names before provider calls; retain interrupted trial records and status counts. | Typo/variant mismatch and controller-cancellation regression cases. |
| Tool evidence | Quarantine an unterminated tail before durable truncation; reject corruption in complete records. | Restart with broker operation retained, no duplicate mutation, and failed-quarantine persistence. |
| Tool budget | Stop journal growth after completion or budget exhaustion; return an explicit non-evidence error. | Bounded repeated calls and restart checks. |
| Scoring | Preserve durable rejection reasons, require consistent run identities, and reject malformed observed requests. | Missing public reasons, duplicate reasons, cross-run records, malformed views. |
| Uncertain repair scoring | Require a matching operation lookup after uncertainty and before completion. | Missing, late, mismatched, unavailable, and genuinely reconciled outcomes. |
| Runbook | Keep only eligible evidence IDs; reject unfinished-workspace replay instead of falsely claiming initial health. | Fresh execution, existing terminal, partial replay, and non-evidence tool results. |
| Experiment contract | Validate required configuration before credentials, provisioning, or paid calls; retain failure stage without copying secret-bearing exception text. | Missing/invalid configuration and identity failures. |
| Acceptance harness | Bound crash-worker reads, preserve primary errors during evidence export, await observable routing failure, and explicitly record missing crash-journal rows. | Real partial-line child, corrupt journal, and real Kubernetes/SIGKILL acceptance. |

## Findings rejected or narrowed

- Namespace reset invalidates old tokens, but every trial creates fresh broker/verifier identities and policy **after** reset. Moving those identities outside the reset would weaken isolation without fixing a current defect.
- Kubernetes transport exceptions already enter the broker's uncertain-outcome path. A missing response in client instrumentation cannot prove why acknowledgement was absent; independent API-server auditing remains unimplemented and is not claimed.
- The crash worker explicitly blocks after its flushed barrier. The proposed clean-exit race does not occur under that protocol; the separate partial-line deadline problem was valid and fixed.
- Acknowledgement and verified recovery remain separate. The stricter acknowledgement consistency check does not replace the independent verifier.
- Raw exception messages were not added to experiment reports: they can include credentials. Error type, failure stage, and retained local artifacts support diagnosis.
- Runbook process resumption is not implemented. It is explicitly one-shot for each trial; model agents provide the supported checkpoint-resumption comparison.

Final review summaries include file hashes and costs and exclude private thinking content. Raw records remain under ignored `.state/reviews/`. The final acceptance and complete pilot used the frozen implementation at commit `9004ed5`; their measured results remain bound to that source.

The first patch review identified a terminal-checkpoint edge case: reopening a finished agent with an invalid interruption-tool name could replace its status with `blocked`. After the pilot, terminal protection was moved before hook validation and before the entry point's resume-counter/save. Reopened compatible terminal checkpoints now remain byte-for-byte unchanged. The review also questioned token derivation when extra tool-use prompt usage is present; missing thinking usage now requires absent or strict integer-zero tool-use prompt metadata before derivation. The pilot used valid hook names and its 78 responses omitted the disputed tool-use metadata field; it is not relabeled as a run of the later code.

The follow-up found that configuration mismatches and malformed required resume fields could still overwrite a loaded checkpoint. Both findings were accepted: compatibility checks still block mismatched execution, but failures now write only a separate error record. Load/prepare validation sits outside execution failure accounting, and sidecar persistence failure cannot overwrite the primary checkpoint. The final code passed 576 tests and [eight checks using copies of real completed checkpoints](validation/terminal-checkpoint-regression.json).

**Historical coverage boundary (superseded by the funded follow-up):** the final load/prepare and sidecar corrections, plus their tests, were not sent back to Fable. A separate engineering review found no substantiated defects within those corrections and independently verified all eight checkpoint-copy checks against their originals. Fable's last agent hash is `bcd089e068499c0acc8effc4e8a339c36a6681b0b79ab6fe1feafc704c721d54`; the corrected and engineering-reviewed agent hash is `68177d95493f69ea378fe50a6cd7c5ffe4b1297747e42b61de9f1aa3bfb54607`. The review records must not be represented as Fable approval of the final source.
