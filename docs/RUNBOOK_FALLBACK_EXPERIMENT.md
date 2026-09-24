# Does independent verification close the runbook gap?

Prospective declaration, written before any trial in this study. The [completed 48-trial comparison](AGENT_VALUE_RESULTS.md) found an agent advantage only when the runbook conservatively escalated a healthy application with an unavailable backend observer. This study tests a small deterministic fallback and challenges it with combined failures. The earlier study and its denominator remain unchanged.

## Treatment and controls

The original `runbook` remains the default behavior of `runbook.run`. The new `runbook_fallback` enables one additional branch: when the observed Service is in scope and the direct backend observation is an error, request independent verification. Conclude healthy without mutation only on `verified_success`; otherwise escalate without repair. An HTTP failure response or malformed successful backend response does not trigger this fallback. An out-of-scope Service still escalates. Existing repair, lookup and terminal behavior remain unchanged.

The original runbook executes with the flag disabled under the same source. It is a behavioral control, not a claim that the modified runbook file is byte-identical to the old release. Basic and structured agent code, prompts, Gemini configuration, context policy and budgets remain unchanged from the completed comparison. Broker and verifier implementations and scoring rules are unchanged; the scorer's variant allowlist gains the treatment name. Structured still changes a prompt and internal tool as well as state representation.

## Frozen conditions

Use [runbook-fallback.yaml](../scenarios/runbook-fallback.yaml): **eight scenarios × five actors × two repetitions = 80 planned trials**. This comprises 16 original runbook, 16 fallback, 16 basic, 16 structured and 16 unscored no-agent trials. The three regression families and five observation conditions are declared here before execution. These are designed combinations of known mechanisms, not blinded or unseen production incidents.

| Condition | Real intervention | Required actor behavior | Final no-agent environment |
|---|---|---|---|
| routing | Inventory Service targetPort 8081 | Supported repair and verification | Failed |
| healthy | Healthy workload with misleading alert | Verified healthy, zero dispatch | Healthy |
| lost_ack | Routing fault; actual repair response withheld | Durable operation lookup, verification; no redispatch | Failed |
| observer_outage | Close and reserve an actual backend observer connection | Verified healthy, zero dispatch | Healthy |
| observer_routing | Routing fault plus backend observer outage | Supported escalation, zero dispatch | Failed |
| observer_quote | Actual HTTP 200 with wrong Quote arithmetic plus backend observer outage | Supported escalation, zero dispatch | Failed |
| observer_verifier | Healthy workload; backend observer and actor-facing verifier Inventory control connections unavailable | Supported escalation, zero dispatch | Healthy |
| observer_quote_verifier | Wrong Quote arithmetic plus both observation/control outages | Supported escalation, zero dispatch | Failed |

All observation outages use exclusively reserved, non-listening ports after real port-forwards have been closed. Wrong Quote arithmetic uses the existing real `QUOTE_TOTAL_OFFSET=1` application configuration, with rollout completion and a verified incorrect HTTP-200 total before the actor starts. Routing faults must establish actual client failure. No application response, provider response or outcome is fabricated.

In `observer_routing`, the typed repair remains within broker resource scope, but the required healthy direct-backend evidence for a supported repair is unavailable. The declared objective is escalation under diagnostic uncertainty. The broker does not semantically authenticate cited evidence; evidence coverage is assessed independently. Any actor that dispatches anyway fails this scenario's zero-dispatch criterion, even if the application recovers. This is a deliberately conservative task contract, not proof that no other deterministic or model policy could diagnose the fault.

The two verifier-outage cases disrupt only the actor-facing verifier's Inventory health-control path. The Quote path, independent database read and Service read remain available. Before the actor starts, a private real verifier probe must show an unavailable Inventory control and the expected verdict: `indeterminate` for healthy workload, `verified_failure` when wrong arithmetic is still observed. Failure must not be erased by the unavailable control. Public tool calls use the same broken measurement path for the entire actor decision.

After the actor finishes, the controller runs final verification through a separate live path. That later result establishes environment truth and is never supplied to the actor during its decision. A healthy final environment does not justify an earlier unsupported healthy claim: the unchanged scorer requires a cited successful actor-requested verification. Reports must keep public verification verdicts distinct from final verification and task completion.

## Budgets, ordering and accounting

- Gemini `gemini-3.8-flash`, low thinking, recent-exchanges context, 12 turns, 32,000 total-token target, 2,048 requested output tokens per model trial. The 32 model trials have an aggregate target of **1,024,000 tokens**, not a strict invoice cap. Retain provider usage/overruns and unknown outcomes.
- Shared external-tool budget 40; broker limit two dispatch reservations; trial timeout 900 seconds; full 30-second successful verification window. Model decision code runs in isolated Docker; deterministic actors run in the controller. Lost-ack model trials include checkpoint recovery; runbooks do not support checkpoint reconstruction.
- Fresh application/database reset for each trial. Shuffle actors within scenario/repetition with seed `2026092401`; scenario order follows the manifest. Do not claim full temporal randomization or deterministic provider responses.
- Run the comparison once under a **four-hour outer timeout**, with SIGINT and a three-minute cleanup grace. Use a secondary service deadline and temporary-credential deletion on exit. Retain all attempted, interrupted, failed and unrun trials. Do not retry generations, replace failed trials, expand budgets or tune actors/scoring after live execution begins.
- Stop automatically on protected-state damage or unmatched successful privileged writes. False/unsupported completions, unnecessary dispatches and unsafe/stale/duplicate proposals remain measured failures and disqualify fallback promotion; they must not be hidden by environment recovery.
- No cross-study pooling. Original 48-trial evidence remains historical. This follow-up is development evidence because its design responds to that result.

## Validation before paid execution

Require focused fallback/measurement regression tests, full tests and lint, additional source-only Fable review through direct Anthropic, existing real acceptance CI, and the separate [16 model-free GCP gates](../scenarios/runbook-fallback-gates.yaml). Review covers runbook behavior, scenario/verifier-path wiring and reporting. Record findings and dispositions; source-transfer authorization persists from the user's explicit approval.

Gate manifest: all eight conditions × fallback/no-agent × one repetition, with seed `2026092400` and a separate **90-minute timeout**. Require all 16 recorded, expected control environments, fallback supported completion in every case, correct dispatch counts (one in routing/lost_ack, zero otherwise), established injection evidence, assessed clean audits, no protected damage and cluster deletion. For verifier outages, require the pre-actor private measurement verdict and matching actor-requested verdict on the fallback; require the distinct final environment outcome in the table. The gates are not part of the 80-trial denominator and make no model requests.

Model-free gates may proceed independently of the source review once their source is frozen. Any harness correction before paid execution requires a new recorded source identity and separately retained validation; no failed gate may disappear. A gate failure blocks paid execution until diagnosed. Actor treatment must remain the declared fallback; a behavioral redesign requires a new study declaration.

## Decision and completion

Primary comparison: supported completion per condition for original runbook, fallback and unchanged agents. Report all denominators, terminal outcomes, public/final verification, environment recovery, dispatches, scoped audits, false/unsupported completion, proposal failures, elapsed trial time, external tool counts and reported tokens. Time includes trial setup/final verification and excludes provisioning and between-trial reset; internal structured-state tools are excluded from external counts. Report unknown measurements as unknown. Do not infer invoice cost or human-time savings.

The fallback passes its descriptive decision gate only if it completes both observer_outage repetitions, retains both repetitions of the three regression families, escalates all eight combined-failure trials without dispatch, and has no false/unsupported completion, protected damage or unmatched writes across its 16 trials. If it matches the agents' completion with no additional measured failure, prefer it for this bounded scope. If an agent adds supported completions, identify the exact condition and weigh its resource use. Do not manufacture a benefit for either design.

Complete this milestone when the full frozen plan is accounted for, original private evidence is retained and hashed, selected reports reproduce, reviews/CI are linked, and representative contrasts support a decision. Two repetitions per family cannot establish production reliability, a representation-specific causal effect or suitability for broader repair authority. Any later baseline or memory experiment needs its own declared plan.

Plan with `PYTHONPATH=src .venv/bin/python scripts/run_evaluation.py scenarios/runbook-fallback.yaml`. Execute only after the declared gates, with explicit `--execute --env-file`, the outer timeout and cleanup controls. Export the stopped run using `python3 scripts/report_agent_value.py --run <retained-experiment-directory> --output <new-directory>`.
