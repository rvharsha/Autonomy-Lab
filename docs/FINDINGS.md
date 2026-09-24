# Research findings and readiness

This is the current decision summary for the initial Autonomy Lab research milestone. The [proposal](../PLAN.md) and [build plan](../BUILD_PLAN.md) describe intent; dated experiment reports preserve results for their named source candidates. Their historical deployment and remaining-work statements are not current status.

## What we set out to learn

The lab asks what evidence should justify trusting an agent with a cloud operation. Its first comparison asks whether explicit incident state improves interruption recovery over persisted interaction history under common execution controls and budgets.

**Conclusion: the execution boundary and independent verifier work for the tested scope. Structured-state superiority is not established.** The evidence supports continued bounded experiments and a technical demonstration. It does not justify expanding authority to unfamiliar operations or production workloads.

The completed [48-trial automation and agent comparison](AGENT_VALUE_RESULTS.md) restored deterministic and no-agent baselines. Its agent advantage came entirely from a missing observer-failure fallback. The separately declared [80-trial follow-up](RUNBOOK_FALLBACK_RESULTS.md) implemented that fallback: original runbook 14/16, fallback 15/16 with one unknown, basic 15/16, structured 16/16, plus 16 controls. The fallback completed both healthy observer-outage cases and all six regressions without model tokens. Its final trial was interrupted during a host service restart, so its promotion gate remains unmet. Hardening job termination and cleanup is the next operational prerequisite for further cloud experiments.

## Evidence and interpretation

| Experiment | Observed result | What it supports |
|---|---|---|
| [Initial pilot](PILOT_RESULTS.md) | Runbook 6/7; basic 5/7; structured 2/7 | A working comparison and concrete failures; one repetition per family |
| [Shared prompt intervention](COMPLETION_EXPERIMENT.md) | Matched development completion 3/8 → 6/8; reported tokens 212,154 → 196,606 | A targeted improvement on development cases; structured lost-ack failures persisted |
| [Context intervention](CONTEXT_RESULTS.md) | Development 6/8 → 6/8 | A null result; the change did not earn a completion benefit in this comparison |
| [Selected reliability candidate](RELIABILITY_RESULTS.md) | 36/38; basic 17/19, structured 19/19 | Descriptive evidence on known families; two basic combined-fault budget failures remain |
| [Reconciliation follow-up](RECONCILIATION_RESULTS.md) | Targets 6/6, regressions 17/18; promotion failed | Improving the target did not satisfy the complete declared gate; candidate withheld |
| [GCP deployment](../infra/gcp/README.md#executed-deployment-checks) | Initial four cases had infrastructure errors; separately declared correction 4/4 | Linux deployment defect diagnosed and fixed; cloud smoke evidence only |
| [Automation and agent comparison](AGENT_VALUE_RESULTS.md) | Runbook 10/12; basic 12/12; structured 12/12; 12 unscored controls | Models handled observer outage; runbook matched completion elsewhere; structured used more tokens without additional completion |
| [Verification fallback comparison](RUNBOOK_FALLBACK_RESULTS.md) | Runbook 14/16; fallback 15/16 with one interrupted unknown; basic 15/16; structured 16/16; 16 controls | Fallback closed the observer gap in both repetitions; Basic had a budget stop; host service restart prevented full fallback validation and automatic cleanup |

These rows involve different releases and conditions. Do not pool their denominators or interpret the sequence as one controlled experiment. Reserved cases are fresh executions of known scenario families, not evidence of broad generalization. The structured treatment changes an internal tool and prompt as well as representation. Runbook and no-agent controls were included in the pilot and the 48- and 80-trial comparisons; they were not repeated in the earlier 38-trial agent comparison.

The selected 38-trial candidate reported 546,910 tokens and 143 retained responses from 143 generation requests. All 38 scoped audits were assessed, with no recorded unmatched successful mutations or false completion claims. This scope covers the trial namespace and named identities, not all external effects or a hostile host. Earlier provider failures and output-limit overruns remain separate, retained limitations.

## Concrete technical conclusions

1. Application recovery and agent completion are separate outcomes. A correct patch does not replace a supported final decision, and a healthy application does not make a blocked agent successful.
2. A lost response requires durable operation lookup and current verification. Restoring an agent workspace alone cannot establish what happened in Kubernetes.
3. Context and bookkeeping consume the same budget needed to finish. Grouping observations improved a development comparison, but neither more state nor a context policy guarantees a benefit.
4. Promotion needs the full declared regression gate. The 23/24 follow-up remains unselected even though its six targeted cases passed. The preflight failure's underlying cause is unestablished.
5. Real deployment adds evidence that local tests cannot supply. Native Linux audit-log ownership differed from Docker Desktop and initially prevented scoring; all original failures remain recorded.
6. Compare against a capable deterministic baseline before attributing value to agent complexity. A model completing a branch absent from one runbook does not show that deterministic automation cannot complete it.
7. Detaching a cleanup process does not separate it from a systemd control group. The latest host service stop interrupted both controller and janitor, requiring explicit offline accounting and manual cleanup. An interrupted attempt remains unknown and cannot be replaced with an earlier passing gate.

Read the [three annotated trajectories](TRAJECTORIES.md), then use the [reproduction and demonstration guide](REPRODUCING.md).

## Current capability and explicit deferrals

The CLI lab implements real application faults, typed conditional repair, broker budgets and durable intent, independent verification, scoped audit correlation, isolated Docker agents, and detached cleanup. The GCP host has the reviewed kind/Docker harness installed and is currently stopped. The latest study exposed a host service-termination gap: cleanup does not independently survive that service's control-group interruption. This must be challenged with a real service-stop acceptance test before another cloud comparison. The patched AX variant has separate local recovery evidence; AX has not been validated on GCP.

The initial milestone is complete when the reviewed tools regenerate the published tables, a fresh checkout executes the declared model-free handoff experiment and exports matching reports, the annotated evidence is available, and the corrected release is published and installed. Execution receipts are recorded in [HANDOFF_VALIDATION.md](HANDOFF_VALIDATION.md); they determine the status of these gates.

Deferred to a separately declared next phase:

- No/relevant/misleading/stale cross-incident memory comparisons.
- Separate read-only, recommendation, and human-approval execution workflows. The existing bounded broker policy is implemented; this wider autonomy ladder is not.
- A representation ablation and new causal scenario families if a stronger claim about structured state is desired.
- GCP AX integration if cloud AX execution becomes a requirement.

More authority would require a new action/resource contract, independently challenged invariants, adversarial and interruption cases, a preregistered comparison with fresh causal variation, and an explicit promotion decision. Passing this lab or deploying its release grants no additional authority by itself. A conclusive structured-state advantage is not required to finish the initial research milestone.
