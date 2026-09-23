# Token preflight failure found in live runs

The development smoke and stopped pilot exposed a concrete budget-accounting defect. Gemini's `countTokens` result did not include previous thinking carried in the preserved conversation, while subsequent generation responses charged those tokens as prompt input. All numbers below come from `experiment-ea63fad3`'s saved requests and provider usage metadata; no response thinking content is reproduced.

| Basic-agent request | `countTokens` input | Previously generated thinking tokens | Billed prompt tokens |
|---|---:|---:|---:|
| 1 | 888 | 0 | 888 |
| 2 | 3,501 | 111 | 3,612 |
| 3 | 4,381 | 889 | 5,270 |
| 4 | 4,758 | 994 | 5,752 |

The same equality held in the inspected structured smoke and partial pilot histories. This is observed provider behavior, not a promise that every model/version will account identically. The API describes `countTokens` as tokenization and reports separate prompt, thinking, candidate, and total usage fields. [Token counting](https://ai.google.dev/api/tokens), [usage metadata](https://ai.google.dev/api/generate-content#UsageMetadata).

The previous reservation subtracted only counted input from the remaining total budget. That could allow a request whose actual input plus permitted output exceeded the remaining allowance. The stopped pilot's recorded totals stayed within 32,000 tokens, but that did not prove the next-call bound was correct.

The corrected policy reserves counted input plus all previously reported thinking tokens while retaining the full provider history and signatures. The remaining allowance caps the next generation's output, including its thinking. Both raw count and conservative reservation are saved. Missing or inconsistent usage prevents a further generation unless the prior thinking count can be derived from valid total, prompt, and candidate counts. If future token counting already includes this history, the extra reservation may stop the agent earlier; it cannot be described as an exact universal billing estimate.

Regression tests exercise the observed metadata pattern, a request that would previously have fit but now stops before generation, interrupted checkpoints, and unknown usage. A subsequent live run must still validate this release's behavior. The original failed/partial artifacts remain unchanged.
