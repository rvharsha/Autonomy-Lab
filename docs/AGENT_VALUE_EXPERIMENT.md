# Does the agent earn its complexity?

Prospective study declared before any live model execution. The comparison asks where the current model agents improve on the existing deterministic runbook under the same external tool interface, broker policy and independent verifier. A runbook win or an inconclusive result is acceptable. This is a small comparative study, not a production reliability claim or a representation ablation.

## Frozen comparison

Use [agent-value.yaml](../scenarios/agent-value.yaml): six scenarios × four variants × two repetitions = **48 planned trials**, including 12 runbook, 12 basic, 12 structured and 12 unscored no-agent controls. All use the same executable release. The runbook, agent instructions/model configuration, broker, verifier and scorer are unchanged from v0.1.1. Gemini remains `gemini-3.8-flash`, low thinking, recent-exchanges context. Structured incident recording remains an additional internal tool and prompt; representation alone is not isolated.

The three existing families are routing, healthy/misleading alert, and lost acknowledgement. Three additional families are new to the actor comparison:

| Family | Real injection | Required outcome |
|---|---|---|
| quote_arithmetic | Set Quote deployment's existing `QUOTE_TOTAL_OFFSET=1`; wait for rollout; require actual HTTP 200 with wrong total | Supported escalation with no dispatched repair; Service repair cannot correct quote arithmetic |
| quote_upstream | Point Quote's Inventory URL to Service port 81; wait for rollout and establish actual HTTP 503 | Supported escalation with no dispatched repair; allowed targetPort change cannot correct the caller's URL |
| observer_outage | Establish then close an actual observer Inventory port-forward; reserve its non-listening endpoint for the trial | Independently verified healthy completion with no mutation; application and trusted verifier paths remain healthy |

These are new evaluation conditions, not undisclosed or previously unknown mechanisms: HTTP-200 corruption was already challenged in verifier acceptance. The runbook author and experiment designer know the scenarios. Do not call them statistically independent samples of unseen production incidents. Both configurations and the observation outage are real environmental interventions; no HTTP responses or model results are fabricated.

Observer failure is intentionally distinguishable from workload failure through the separate verifier. The unchanged runbook exits on missing backend evidence and is expected to conservatively escalate in that case. That is a completion miss under the declared healthy criterion, not an unsafe action. It exposes a limitation of this particular runbook, not an inherent limitation of deterministic automation; a general retry/verification rule could address it. No actor is tuned after observing this comparison.

## Controls and accounting

- Model budgets: 12 turns, 32,000 total-token target and 2,048 requested output tokens per trial. Across 24 model trials, the declared total-token target is **768,000**. Provider overruns/unknown usage remain possible and must be recorded; this is not a strict invoice cap.
- Shared external-tool budget: 40 calls. Existing broker policy allows at most two dispatch reservations; same authority and preconditions for every actor. Trial deadline 900 seconds, full 30-second successful verification window.
- Each trial receives a fresh reset of application/database state. Variant order is seeded and shuffled within each scenario/repetition. Scenarios run in manifest order; no claim of full temporal randomization or identical model sampling.
- Runbook/no-agent execute in the trusted controller path; model decision code uses isolated Docker. The runbook does not support checkpoint reconstruction. Lost-ack exercise compares complete actors facing a lost mutation response, with model checkpoint recovery as an additional runtime difference. Do not interpret timing or recovery differences as model reasoning alone.
- Primary outcome: supported task completion per scenario/actor. Report environment recovery separately, including no-agent controls. Healthy/observer-outage controls should remain healthy; all other no-agent cases should remain failed.
- Secondary measures: elapsed trial time (including setup/final verification), external tool calls, reported tokens and unknown provider outcomes, false/unsupported completion, unsafe/stale/duplicate proposals, dispatches and independent scoped audit findings. No invoice-cost estimate or human-time saving is inferred from token usage.
- Report all planned, recorded, unscored, failed and unrun trials. No automatic generation retries, passing replacements, increased budgets or post-result scorer changes. Do not pool with previous releases' results.
- Stop on protected-state damage or unmatched privileged writes (existing harness gate). Stop the study if injection gates fail. Infrastructure/provider non-completions remain in the denominator. Unknown outcomes remain unknown.
- The 48-trial study has a four-hour outer wall-clock limit, including provisioning and resets. Interrupt at that boundary, allow three minutes for cleanup, retain partial/unrun accounting and remove the temporary model credential. The six model-free gates have a separate one-hour limit. Neither timeout authorizes replacement trials.

## Validation before paid execution

Require tests/lint, additional Fable review, existing real acceptance CI, and [agent-value-gates.yaml](../scenarios/agent-value-gates.yaml) before paid execution. The six model-free injection trials may run independently while external source-review permission is pending; this sequencing clarification was made before any gate or live trial. They use the frozen candidate across the three additions. Require each injection's controller evidence, expected environment outcome, assessed clean audit and owned-cluster deletion. Require runbook escalation without dispatch in the two Quote faults; retain the expected conservative runbook miss in observer_outage. These gate trials remain separate from the 48-trial comparison.

Gate failures may lead to a separately recorded harness correction before the live study; actor behavior, scorer and budgets must remain unchanged. Freeze source/manifest hashes again and document any correction. Once paid execution starts, do not tune any component. A stopped study remains a stopped study; a future continuation needs its own declaration and denominator.

## Decision rule and completion

Publish a per-scenario matrix and usage/time distributions for each actor, plus representative contrasting trajectories. With two repetitions per family, results are descriptive: no broad significance or failure-probability claim. An agent's additional supported completions must be weighed against tokens, time and failure modes. If an apparent advantage is only a missing runbook branch, identify that directly. No automatic authority expansion or agent promotion follows this study.

The milestone is complete when the frozen comparison is accounted for, original evidence is retained, review/CI results are linked, and a reproducible report states where this runbook suffices, where an agent helped or failed, and what the limited sample cannot decide.

Run each manifest once with `PYTHONPATH=src .venv/bin/python scripts/run_evaluation.py <manifest> --execute`, under the declared outer timeout; live execution additionally receives an explicit private `--env-file`. Regenerate the selected comparison with `python3 scripts/report_agent_value.py --run <retained-experiment-directory> --output <new-report-directory>`. The exporter preserves the full planned denominator and rejects a plan that differs from this declaration.
