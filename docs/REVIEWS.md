# Code review workflow

Implementation PRs receive deterministic checks, an additional Claude Fable 5.1 source review, and a checked disposition for each finding. A model response is not merge approval. Review coverage is tied to file hashes; changed components need another review after remediation.

Run tests and lint locally, then choose the affected component:

```sh
make test lint
.venv/bin/python scripts/fable_review.py --scope broker --snapshot-only
.venv/bin/python scripts/fable_review.py --scope broker
```

The first review command lists the exact source manifest without a model call. The second sends the allowlisted component to `claude-fable-5-1`. It reads `ANTHROPIC_API_KEY` or `ANTHROPIC_KEY` from `~/Dev/.env`, independently of the Gemini credential used by the experiments. Local artifacts, environment files, hidden directories, and symlinked source are excluded. Most test bodies are omitted and identified as a test-name index; the review is not a test execution.

Available component scopes include `broker`, `agent_runtime`, `verification`, `tools_runbook`, `scoring`, `infrastructure`, `harness`, and `experiments`. Use `--help` for the current list. Broad scopes previously exhausted the response budget without findings; use the smaller component scopes.

Component reviews use a token-count preflight, fewer than 15,000 input tokens, a hard 12,000 output-token limit, and an estimated request-cost ceiling below $0.80 at the recorded prices. They make one generation request with no tools, retries, continuation, or model fallback. The cost is an estimate, not a billing guarantee. A truncated response, wrong returned model, or missing final text is an incomplete review, never an approval.

Review records stay in `.state/reviews/`. Publish only an explicitly selected summary containing final findings, dispositions, file hashes, and usage. Raw responses and private thinking content do not belong in a PR. Link that summary in the PR description and identify any components changed after the recorded review.

For each finding, reproduce the trigger or explain why the surrounding code prevents it. Fix verified defects with appropriate regression checks. Keep rejected findings and their rationale in the summary so reviewers can assess that decision. After execution-boundary changes, rerun the real Kubernetes acceptance suite.

GitHub runs tests, lint, and real Kubernetes acceptance on PRs. Fable review currently runs locally; no GitHub model credential or automatic paid review workflow has been configured. The `bounded_transport` scope includes the shared HTTP limits and its model, Kubernetes, and observation callers; `experiments` includes the worker and supervisor.
