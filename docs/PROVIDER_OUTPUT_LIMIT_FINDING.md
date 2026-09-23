# Reported output usage exceeded a requested limit

During the frozen 44-trial comparison, treatment trial 003 (`experiment-31b761fa`, structured `lost_ack`) stopped indeterminate. Its sixth generation returned `MAX_TOKENS`, and the host retained the response's usage but did not execute its incomplete output or retry.

| Measurement | Tokens |
|---|---:|
| Known usage before the request | 25,125 |
| Remaining declared trial budget | 6,875 |
| Provider-counted input | 6,104 |
| Reserved retained-signature thinking | 330 |
| Reserved input / reported prompt usage | 6,434 / 6,434 |
| Requested `maxOutputTokens` | 441 |
| Reported candidate tokens | 95 |
| Reported thinking tokens | 618 |
| Reported generation total | 7,147 |
| Known cumulative usage | 32,272 |
| Excess over the declared 32,000-token trial budget | 272 |

The input reservation matched the reported prompt usage. The discrepancy is in reported generated usage: 713 candidate-plus-thinking tokens against a requested allowance of 441. This is distinct from the earlier missing signature-carried input accounting. The request was not raised above its remaining allowance.

[Google's thinking documentation](https://ai.google.dev/gemini-api/docs/generate-content/thinking#token-limits-and-max_output_tokens) describes the output limit as an infrastructure cutoff covering thinking and candidate tokens. This observed response does not establish that guarantee for billed usage. It is evidence of a request/usage discrepancy; it does not establish the provider's internal cause.

The host ledger records all six responses and 32,272 known tokens, then blocks further generation. Its `pending: true` field is also used as a fail-closed marker for reservation overruns; here it does **not** mean the sixth response or its usage is missing. The decision agent received the failure and reports unknown usage locally; the host record is the accounting source.

The trial remains in the original comparison as a non-completion. No retry, replacement, increased budget, source change, or held-out tuning was applied. The original contract remains unchanged; this is a recorded deviation from its intended token ceiling. Subsequent report totals must use host usage and separately report overruns. Local preflight and post-response enforcement cannot be described as a proven strict provider billing cap.

Private evidence: `artifacts/experiment-31b761fa/trial-003/model-relay.json`, `agent-state.json`, and `trial.json`. Selected numeric evidence is included in the final context-evaluation report; model response content and opaque signatures stay private.

## Second observed discrepancy

Regression trial 004 (`experiment-ac4b2fd7`, basic `out_of_authority`) returned
`MAX_TOKENS` on generation four. Its reserved and reported prompt usage both
equaled 5,225 tokens. The requested output allowance was 2,048; reported output
was 233 candidate plus 1,897 thinking tokens, exceeding that allowance by 82.
The host captured all four responses and 17,294 cumulative tokens, then stopped
without executing the incomplete response or retrying. This run stayed below
its trial total limit, but violated the per-request reservation. The second
case shows the discrepancy also occurred with the normal 2,048 output setting,
not only the smaller final allowance in treatment trial 003.

## Follow-up candidate discrepancy

The separately declared batching regression trial 008 (`experiment-5533bbd9`,
structured `distraction`, source `ec7feb1`) returned `MAX_TOKENS` on generation
two. Its reserved and reported prompt usage both equaled 3,853 tokens. Reported
output was 497 candidate plus 1,845 thinking tokens: 2,342 against a requested
2,048, an excess of 294. The host retained both generation responses and all
7,698 reported trial tokens, blocked further generation, and did not execute
the incomplete response's tools. This is a known reservation overrun below the
trial total ceiling; it is separate from the follow-up development HTTP 503
whose generation usage is unknown. Neither trial was retried or replaced.
