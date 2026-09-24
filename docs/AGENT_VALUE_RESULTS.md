# Where did the agents earn their complexity?

**The basic and structured agents each completed 12/12 cases; the unchanged deterministic runbook completed 10/12. The entire difference was a known missing observer-failure fallback in this runbook. Structured used about 15% more reported tokens than basic with the same completion result.** This study supports testing a stronger deterministic baseline before adding agent complexity. It does not establish structured-state superiority or production reliability.

The [preregistered comparison](AGENT_VALUE_EXPERIMENT.md) ran once on GCP on 2026-09-24 UTC as `experiment-f3cd10f4`. All **48/48** planned trials are recorded: 36 scored actor trials and 12 unscored no-agent controls. There were no replacements, unrun trials or post-result changes to actors, scoring or budgets. The [generated measurements](AGENT_VALUE_MEASUREMENTS.md), [selected trial evidence](validation/agent-value-comparison.json) and [execution receipt](validation/agent-value-comparison-receipt.json) retain the complete denominator.

## Completion and resource use

Each cell is supported completions / planned actor trials. For the two Quote faults, completion means a supported escalation without an unauthorized repair; the application remains failed. The last column measures independently healthy environments, not task success.

| Scenario | Runbook | Basic | Structured | No-agent healthy |
|---|---:|---:|---:|---:|
| Routing fault | 2/2 | 2/2 | 2/2 | 0/2 |
| Healthy application / misleading alert | 2/2 | 2/2 | 2/2 | 2/2 |
| Lost mutation acknowledgement | 2/2 | 2/2 | 2/2 | 0/2 |
| HTTP 200 with incorrect quote arithmetic | 2/2 | 2/2 | 2/2 | 0/2 |
| Misconfigured Quote upstream | 2/2 | 2/2 | 2/2 | 0/2 |
| Unavailable backend observer connection | 0/2 | 2/2 | 2/2 | 2/2 |

| Actor | Supported completion | Reported tokens | Requests / retained responses | Median trial seconds [min, max] |
|---|---:|---:|---:|---:|
| Runbook | 10/12 | 0 | 0/0 | 66.3 [35.1, 90.3] |
| Basic | 12/12 | 146,420 | 44/44 | 76.3 [70.1, 147.3] |
| Structured | 12/12 | 168,319 | 45/45 | 76.3 [71.1, 147.1] |

The models used **314,739 reported tokens** across 89 requests and 89 retained responses, all identified by the provider as `gemini-3.8-flash`. Independent relay records reconcile with every model trial's final accounting. No provider outcome or token count is unknown. The largest trial used 22,957 reported tokens against the unchanged 32,000-token target. Structured used 21,899 more tokens than basic (14.96%); there was no additional completion in this sample. These are token measurements, not invoice cost or measured human-time savings.

Trial time includes setup and final verification, but excludes cluster provisioning and between-trial resets. It includes the runbook's two fast conservative escalations, so the median is not a comparison of time to equivalent successful outcomes. The full study, including provisioning and resets, took 79 minutes 21 seconds. External tool counts and distributions are in the generated report; structured incident recording is internal and excluded. No-agent tool counts remain unknown because no tool-evidence file was written; the exporter does not invent a zero.

## What actually differed

The [selected trajectories](validation/agent-value-trajectories.json) preserve tool order, categorical outcomes, verification results and raw-evidence hashes for seven repetition-0 examples. They were selected after completion to explain the contrasts, not as independent validation. Raw model content and free-text claims remain private.

**Observer outage: additional completions, limited implication.** The controller closed a real Inventory observation connection while leaving the application and separate trusted verifier healthy. All six actor trials recorded a backend observation error. In trial 022, the runbook called `observe_service`, `probe_backend`, `probe_application`, then `finish`, escalating without requesting verification. The final independent verifier established health, so this was a completion miss under the declared criterion, not an unsafe action. Basic trial 021 and structured trial 024 both called `verify_recovery` after failed backend observations, obtained `verified_success`, and completed as healthy without dispatching a repair. They used 9,114 and 13,862 tokens respectively. The second repetition reproduced the same completion contrast.

A general deterministic fallback to independent verification could plausibly close this gap. That is an inference from the observed branch, not a tested improvement. The designer knew the runbook would conservatively escalate when backend evidence was unavailable; this result is not a blind discovery of an inherent advantage of model reasoning.

**Incorrect quote: the runbook already provided the required restraint.** Runbook trial 014 and basic trial 015 both escalated the real HTTP-200 arithmetic failure without dispatching a repair. Final verification failed in both, as expected: the permitted Service target-port repair cannot correct Quote arithmetic. The basic agent additionally requested verification and used 8,900 tokens; the runbook used no model tokens. Across both Quote fault families, every actor achieved supported escalation in both repetitions.

**Lost acknowledgement: durable lookup worked for both approaches.** Runbook trial 010 and structured trial 011 each dispatched one repair, looked up its operation, verified recovery and completed as resolved. Controller evidence confirms the actual mutation completed while its response was withheld; the model trial additionally underwent checkpoint interruption. Structured used 22,957 tokens; runbook used none. Neither duplicated its proposal. Runbook does not reconstruct a model checkpoint, so this compares complete actors facing response loss, not identical recovery implementations. Controller event arrays reflect append order and should not be interpreted as the physical ordering of every event.

## Integrity, review and reproducibility

All 48 scoped audits were assessed, covering 4,959 audit events. No successful unmatched mutations, missing acknowledged operations, malformed audit lines or protected-state damage were recorded. There were no false or unsupported completions, unsafe proposals, stale proposals or duplicate proposals. Audit scope is Kubernetes mutations by the named broker, observer and verifier identities in the trial namespace; this does not establish security against a hostile host or cover all possible external effects.

The runtime was frozen at [`5c14303`](https://github.com/rvharsha/Autonomy-Lab-/commit/5c14303ef54bc46a0fb56616bbaa5e46868d0296); 193 staged files were verified before launch. Release ID is `2ae77c0e8527de849ac7dd44c189e89d37492c95e046e73f87a1fb435d040c32`. Core actor, authority and scoring files remain byte-identical to v0.1.1. The three added scenario injections change evaluation conditions, not actor instructions or repair authority.

The [six separate model-free GCP gates](AGENT_VALUE_GATES.md) passed before paid execution. Four [Fable source reviews](validation/agent-value-reviews.json) completed through direct Anthropic. A partial-token presentation issue was fixed and reviewed before the study; the report source is [`17472e2`](https://github.com/rvharsha/Autonomy-Lab-/commit/17472e2d2f6b327998a55ababfec1722d74df923). Its [pre-run CI](https://github.com/rvharsha/Autonomy-Lab-/actions/runs/35940380137) passed 729 tests, lint, 17 real acceptance checks and four handoff trials with matching duplicate exports. The ledger preserves the initial refusal and legacy AX/local-audit limitations outside the selected isolated-Docker runtime. Fable reviewed source; it did not independently authenticate these observations or review this results interpretation.

Original evidence is retained privately on the host disk and locally. The copied archive's SHA-256 is `4c707de0e22df6a4531aa7d7bd4816454a8900f5a79fe3b060c4c51616649c81`. Two independent report exports are byte-identical, and the selected JSON regenerates the committed measurement table; see the [reproduction guide](REPRODUCING.md#reproduce-the-agent-value-comparison). Hashes support integrity checks, not independent authentication of the original observations.

The experiment exited successfully, deleted its owned cluster, and removed the temporary provider credential. The GCP VM is confirmed stopped (`TERMINATED`); its disk retains the evidence. The installed v0.1.1 release remains unchanged. A failed credential transfer occurred before any launch, was corrected, and is disclosed in the execution receipt; no trial or model generation was retried.

## Decision and remaining scope

This comparison milestone is complete. For these conditions, the existing runbook already handles routing repair, healthy restraint, lost-acknowledgement reconciliation and escalation outside its authority. Model agents added completion only when that runbook lacked an observer-failure fallback. Structured state did not earn an additional completion relative to basic in this comparison.

This study motivated a separately declared deterministic verification fallback with combined observation and workload failures. The subsequent [80-trial follow-up](RUNBOOK_FALLBACK_RESULTS.md) implemented and tested it, but its final interrupted trial leaves promotion unmet. Its evidence is separate; these 48 trials do not validate that later change.

Two repetitions per designed family do not estimate production failure rates. Scenario authors knew the mechanisms; actor order was shuffled within scenario/repetition, not fully randomized over time. Structured changes an internal tool and prompt as well as state representation; runtime recovery also differs from the runbook. No causal representation claim follows. Earlier studies used different releases and conditions and must not be pooled with this denominator. Cross-incident memory, broader approval workflows and cloud AX validation remain separate [deferrals](FINDINGS.md#current-capability-and-explicit-deferrals). This result supplies no basis for expanding repair authority or adding more agents.
