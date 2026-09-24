# Recovery after whole-service termination

**The three real GCP termination gates passed:** ordinary stop, restart, and SIGKILL of the entire original service control group. Recovery removed each owned Kubernetes cluster and preserved truthful interruption accounting. Restart did not launch a replacement experiment. The separately declared model-free validation also passed: **32/32 controller-finalized trials, 16/16 supported fallback completions and 32/32 assessed scoped audits**, with automatic cleanup and byte-identical independent exports. The fallback is validated for this bounded policy; the original runbook remains the default/control.

The [prospective declaration](SERVICE_RECOVERY_EXPERIMENT.md) and [selected gate evidence](validation/service-recovery-gates.json) identify the boundaries and outcomes. Runtime and gate source was frozen at `2c2e04e62638920b6003cdb66b45274b88b313db` on the authorized GCP lab host.

## What changed

New cloud studies use a prepared job, an exclusive durable launch claim, and a reserved experiment identity. An ownership token written before provisioning prevents recovery from adopting or deleting a colliding pre-existing experiment. The wrapper and runtime source hashes are checked before execution.

Systemd starts the supervised `ExecStopPost` phase after the original service processes have terminated. It removes the explicitly supplied transient provider file before process inspection or Docker cleanup, records progress, and saves a distinct final recovery receipt. It cleans only the run's registered resources and checks that no owned cluster nodes or registered agent containers remain. If process inspection is unavailable, recovery records failure and refuses resource cleanup rather than treating unknown liveness as death.

The post-stop accounting sidecar preserves controller-committed results, marks uncommitted attempts unassessed, and lists unrun trials. It does not rewrite original trial files or invent controller accounting, timing, scores, usage or audits. A failed post-stop phase is a failed operational gate; an incomplete progress receipt is not successful recovery.

## Actual termination evidence

Each gate declared routing followed by healthy, one fallback actor and one repetition. It triggered only after the broker acknowledged the routing repair while trial 1 was still running. The controller and detached janitor were verified to share the original service control group.

| Gate | Experiment | Attempted, unassessed | Unrun | Owned resources after recovery | Result |
|---|---|---:|---:|---:|---|
| Ordinary stop | `experiment-a4f0bff4` | 1 | 1 | 0 | Passed |
| Restart | `experiment-c769da8f` | 1 | 1 | 0 | Passed; replacement invocation refused |
| Entire-group SIGKILL | `experiment-77f2c190` | 1 | 1 | 0 | Passed |

All three original janitor processes terminated. Systemd launched recovery afterward; this is not evidence that a detached process escaped its control group. Original evidence hashes and launch claims remained unchanged. The restart's new invocation failed on the existing claim; its exit status is not substituted for the interrupted controller's status.

These are **three lifecycle gate passes, not three successful agent completions or clean final trial audits**. Every interrupted attempt remains unassessed. The gates made no model calls and supplied no provider credential. Real credential-file revocation under these cloud stops was therefore not exercised; source review and authored failure tests cover that ordering.

An initial administrative SSH command could not enter the private staged directory and was corrected before any service or trial launched. All executed gate results above are retained; none was replaced by a passing repeat.

## Review and validation

The [exact-source CI run](https://github.com/rvharsha/Autonomy-Lab-/actions/runs/36017718526) passed **797 tests, lint, 17 real Kubernetes acceptance checks and four model-free handoff trials**. The downloaded acceptance artifacts were inspected; duplicate handoff exports were byte-identical. The same 797 tests and lint passed on the GCP host.

Nine additional [Fable source reviews and checked dispositions](validation/service-recovery-reviews.json) cover lifecycle, termination gates and the separate validation/reporting contract. Four preflights exceeded the existing input ceiling and made no generation request; narrowed snapshots retained the same review cost limits. Verified findings corrected credential revocation ordering, liveness-error receipts, stop-phase deadlines, failed-receipt preservation and a restart-state race. Conditional findings contradicted by the implementation are retained with their rationale. Model review does not authenticate the measured observations.

Actor code, model adapter, broker, runbook, verifier, scorer, observation tools and scenario implementations remain byte-identical to the prior comparison's `cbddb250` source. The change concerns cloud orchestration and recovery, not repair authority or a new agent treatment.

## Separate fallback validation: complete

The declared `runbook-fallback-validation` ran once as `experiment-0acc5582` under `autolab-study-0acc5582.service`. The [generated measurements](RUNBOOK_FALLBACK_VALIDATION_MEASUREMENTS.md), [selected per-trial evidence](validation/runbook-fallback-validation-32.json) and [execution receipt](validation/service-recovery-execution.json) preserve its own 32-trial denominator. This is not a new Gemini comparison or a replacement for the interrupted study.

| Condition | Fallback supported / planned | Required terminal outcome | No-agent healthy / planned |
|---|---:|---|---:|
| Routing fault | 2/2 | Resolved; one dispatch per trial | 0/2 |
| Healthy workload | 2/2 | Healthy; no dispatch | 2/2 |
| Lost acknowledgement | 2/2 | Resolved; one dispatch, no duplicate | 0/2 |
| Backend observer outage | 2/2 | Healthy; independent verification, no dispatch | 2/2 |
| Observer plus routing fault | 2/2 | Escalated; no dispatch | 0/2 |
| Observer plus incorrect quote arithmetic | 2/2 | Escalated; no dispatch | 0/2 |
| Observer plus verifier outage | 2/2 | Escalated; no dispatch | 2/2 |
| Observer, incorrect arithmetic and verifier outage | 2/2 | Escalated; no dispatch | 0/2 |

All 16 fallback trials achieved supported completion: four verified repairs, four healthy/restraint outcomes and eight supported escalations. The 16 no-agent controls remain unscored. Fault-injection records establish actual routing, semantic and measurement-outage exposure. Both fallback lost-ack cases record a completed mutation with withheld response and no duplicate proposal. Actor-facing verdicts remain distinct from the controller's later independent environment check.

All 32 audits were assessed. There were no recorded false/unsupported completions, unsafe/stale/duplicate proposals, unmatched successful mutations, missing acknowledged operations, malformed audit lines or protected-state damage. No outcome, token usage or provider result was unknown. The study made zero generation calls and used zero model tokens; no provider credential was supplied.

The controller finalized all 32 trials and cleaned its owned cluster. The supervised post-stop phase also finished, with no remaining owned resources and accounting of 32 committed, zero unassessed and zero unrun. Two cloud exports matched byte for byte; a third export generated locally from the copied private archive matched both. The preregistered checker's hash was verified before and after execution; its criteria were not relaxed after results.

The raw archive is retained privately locally and on the GCP disk. Its SHA-256 is `ed8d052826770c35bcf786b1bfdf735270dac1c73274607a178d692a116a277f`. It includes original evidence, source provenance, launch declaration, frozen checker, gate receipts and service journal. Raw kubeconfigs and other runtime material are not public; selected reports contain categories, counters and hashes. Hashes support integrity, not independent authentication of the observations.

## Limits and next decision

This proves the declared process-termination boundary on an operating GCP host. It does not establish recovery from host/power loss, unavailable Docker/systemd, hostile host administration or termination of the post-stop phase itself. Those conditions remain outside the guarantee. Missing or failed recovery receipts require investigation; they must not be called clean shutdowns.

The original [80-trial comparison](RUNBOOK_FALLBACK_RESULTS.md) remains 79 finalized plus one interrupted, unassessed attempt. Its promotion gate is still unmet. The new 32-trial validation satisfied its separately declared completion, restraint, verification, audit and cleanup criteria. The `runbook_fallback` variant is now validated for this narrow policy; it remains explicitly selected in manifests, with the original `runbook` unchanged as the default/control. Neither cohort grants broader repair authority. Two repetitions per known designed family do not establish unseen generalization or production reliability.
