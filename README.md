# Autonomy Lab

Start with the [research findings and readiness](docs/FINDINGS.md), [annotated trajectories](docs/TRAJECTORIES.md), and [reproduction guide](docs/REPRODUCING.md). The corrected research release is **v0.1.1**; [handoff validation](docs/HANDOFF_VALIDATION.md) records its execution gates.

Next phase: [continuous service ownership](docs/CONTINUOUS_OWNERSHIP_PLAN.md). Its [mixed-state evaluator prerequisite](docs/MIXED_STATE_RECOVERY_RESULTS.md) passed three real GCP termination gates, preserving committed results and subsequent uncertainty. The [first persistent-workload restart gate](docs/PERSISTENT_CAMPAIGN_RESULTS.md) passed on GCP and in CI: 12/12 independent measurement slots, 11 unchanged resource UIDs, and zero repairs through an operator restart. A [five-minute recurrence gate](docs/RECURRENCE_RESULTS.md) now also passes on both platforms: two attributed repairs across restarts, followed by cumulative-budget escalation on a third fault. All 30 slots were assessed, including 15 failed slots. The [ambiguous-effect gate](docs/AMBIGUITY_RESULTS.md) also passes on both platforms: a real write survives operator death without acknowledgement or replay, including an external routing change during downtime. Broader continuous ownership and procedure evolution remain pending.

The [goal alignment check](docs/GOAL_ALIGNMENT.md) distinguishes execution control
from useful adaptation. [Evaluated program admission](docs/PROGRAM_ADMISSION.md)
now governs new operation authorizations and withdrawal. The next
[budget-horizon comparison](docs/BUDGET_HORIZON.md) tests whether spending repair
attempts on one incident worsens outcomes on a later one, under unchanged authority.
Generated improvement and model value remain unproved.

The [80-trial fallback comparison](docs/RUNBOOK_FALLBACK_RESULTS.md) accounts for 79 finalized trials and one interrupted attempt. Original runbook: 14/16; verification fallback: 15/16 with one unknown; basic: 15/16; structured: 16/16, plus 16 unscored controls. The deterministic fallback closed both healthy observer-outage cases with zero model tokens, but a host service restart interrupted its final trial and automatic cleanup. Its promotion gate remains unmet; original evidence and manual cleanup are retained. The subsequent [service-recovery correction](docs/SERVICE_RECOVERY_RESULTS.md) passed real stop, restart and entire-group SIGKILL gates on GCP. Its separate model-free validation finalized **32/32 trials**, with **16/16 supported fallback completions**, complete scoped audits and automatic cleanup. The fallback is validated for that bounded policy and remains an explicit variant; the original runbook stays the default/control. The VM is stopped and both evidence archives are retained.

The earlier [48-trial comparison](docs/AGENT_VALUE_RESULTS.md) remains separate: runbook 10/12, basic 12/12 and structured 12/12, plus 12 controls. These studies add research evidence; they do not expand repair authority or establish production readiness.

A Kubernetes lab for testing diagnosis, bounded repair, independent verification, and recovery after interruption. It runs locally or on the [GCP experiment host](infra/gcp/README.md) in `autonomy-lab-509518`. The research proposal is in [PLAN.md](PLAN.md); milestones are in [BUILD_PLAN.md](BUILD_PLAN.md).

The application is real: Quote API → Inventory Service → Inventory API → PostgreSQL. The controller changes the Inventory Service's target port. A separate verifier checks HTTP responses, protected database rows, and Service configuration. The broker permits one typed field change with identity/version preconditions and a durable SQLite operation journal.

[Executed validation](docs/VALIDATION.md) records the real-system checks. The [28-trial development pilot](docs/PILOT_RESULTS.md) retains successes and non-completions, including the model agents' budget stops. These results do not establish production reliability.

The [adversarial self-review](docs/ADVERSARIAL_REVIEW.md) records the original findings and remaining architecture gates. The [correctness follow-up](docs/CORRECTNESS_FIXES.md) tracks their implementation, validation, and review status.

The [funded Fable follow-up](docs/FUNDED_REVIEW.md) records completed source reviews, checked findings and durability fixes. The Anthropic credit blocker is resolved.

A [focused completion experiment](docs/COMPLETION_EXPERIMENT.md) tested one shared prompt change under unchanged budgets: supported completion rose from 3/8 to 6/8 in matched development conditions. The later [44-trial context comparison](docs/CONTEXT_RESULTS.md) recorded a null development result (6/8 → 6/8), 8/10 regressions, and 6/18 held-out completions. A [separate batching follow-up](docs/BATCHED_TURN_RESULTS.md) completed both structured lost-ack retests under the same token target, with 7/8 development and 8/10 regression completions. Escalation and provider failures remain, and the earlier held-out results do not validate the later candidate.

The [38-trial reliability candidate](docs/RELIABILITY_RESULTS.md) completed 36/38 cases, including all development and regression cases and 16/18 reserved validation cases. Two basic combined-fault budget failures remain recorded. The [reconciliation follow-up](docs/RECONCILIATION_RESULTS.md) completed 23/24 cases: 6/6 targets and 17/18 regressions. It failed its declared promotion gate, so the released executable source retains `5ab2ebf`; all follow-up outcomes remain recorded separately.

The [GCP deployment record](infra/gcp/README.md#executed-deployment-checks) includes real cloud acceptance, isolation, audit rotation, controller-death cleanup and restart persistence. Its first four cloud trials exposed a Linux audit-permission defect; all four remain recorded. The reviewed correction passed a separately declared four-trial smoke run.

## Run the acceptance demo

Requirements: Docker running, Python 3.12, `uv`, and internet access for pinned tools/images/dependencies. The initial setup downloads a Kubernetes node image and application dependencies. All cluster configuration remains in this project; commands select a dedicated `autolab-*` context.

```sh
make setup
make test lint
make demo
```

The demo creates a fresh cluster, checks healthy behavior, injects a routing fault, checks ineffective and effective repairs, challenges the verifier, exercises broker conflicts and response loss, kills broker processes at deterministic boundaries, writes evidence, and removes its cluster. Successful recovery requires a complete 30-second sampled workload window. Negative checks use shorter declared windows because conclusive failure is sufficient.

After scripted restoration, the acceptance harness allows up to 30 seconds to observe client-path readiness before starting that full window. Only routing-related HTTP 503s may settle; wrong responses, protected-state violations and measurement outages fail immediately. All readiness attempts remain in the evidence. Kubernetes acknowledgement alone does not establish that the application path has recovered.

Each upstream HTTP request opens a fresh connection so a pre-fault keep-alive connection cannot bypass the changed Service route. Faulted trials must demonstrate a client-visible failure before an actor starts.

Reports are under `artifacts/demo-*/REPORT.md`. The raw probes, journal events, API request instrumentation, and process-kill evidence remain alongside them. These directories also contain local kubeconfigs and must not be published wholesale.

To keep an environment for inspection:

```sh
PYTHONPATH=src .venv/bin/python -m autonomy_lab.cli demo --keep
PYTHONPATH=src .venv/bin/python -m autonomy_lab.cli cleanup artifacts/demo-RUN_ID
```

Replace `RUN_ID` with the actual run printed by the command. Cleanup only targets the cluster recorded in that run's metadata. Failed runs retain their evidence even when their cluster is deleted.

## Run the agents

The selected model is **Gemini 3.8 Flash**, API ID `gemini-3.8-flash`. A basic agent retains interaction history. A structured agent also maintains explicit incident state through an internal tool. Both have the same external observations, repair interface, verifier, and execution policy. The selected Gemini 3.8 Flash adapter requests low thinking; requested token limits and host accounting still apply.

The credential loader recognizes `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `GEMINI_KEY`, first in the environment and then in `~/Dev/.env`. It reads only those assignments, does not execute shell expressions, and does not copy the key into the repository or reports.

```sh
PYTHONPATH=src .venv/bin/python -m autonomy_lab.cli experiment \
  --manifest scenarios/reliability-development.yaml --env-file ~/Dev/.env
```

This current manifest selects `runtime: isolated-docker`. Older pilot/completion manifests retain the legacy trusted local-process runtime for historical reproduction.

This invokes the live model API and may incur charges. The manifest declares the model, token/turn limits, scenario matrix, repetition count, and verification window. The command saves the manifest and source hashes before running, resets the namespace and database between trials, and records every attempted result and any unrun trials. Local model/agent failures are retained as outcomes. A missing credential stops before provisioning.

Each trial runs in a separate POSIX worker with a controller-enforced `trial_timeout_seconds` deadline (900 seconds by default), including trial setup and final verification. On timeout, the controller kills that worker's process group, preserves partial evidence, records a non-completion, and continues normal reset/cleanup. Model requests and mutations are never automatically retried after uncertain completion. A detached janitor watches controller identity and a bounded lease; it removes registered agent containers and the owned cluster after controller death. For cloud studies, use the [managed service entry point](infra/gcp/README.md#operate-and-clean-up): its supervised post-stop phase also handles termination of the original service group and prevents replay through a durable launch claim.

Checkpoint schema 2 binds state to its run, release, system instructions and tool declarations. Schema 1 checkpoints remain historical evidence and are rejected without modification; there is no automatic migration or replay. Bounded HTTP runs on the worker's main thread and rejects compressed responses before decoding. The verifier caps each response at 64 KiB; model and Kubernetes responses have separate bounded limits.

The pilot is development evidence, not a statistical reliability claim. Injected adversarial observations count as exposure only if they appear in the actor's recorded observations. Model token usage includes repeated input context and thinking tokens. Preflight conservatively reserves previous thinking carried by the conversation in addition to `countTokens`; [the live accounting failure](docs/TOKEN_BUDGET_FINDING.md) explains why. Later responses also [reported output usage above the requested limit](docs/PROVIDER_OUTPUT_LIMIT_FINDING.md). The host records that usage and stops; local request gating is not a proven strict provider billing cap. Infrastructure runtime and any unpriced cost remain separate from token usage.

The [runtime work record](docs/RUNTIME_ISOLATION_WORK.md) tracks the additional isolation, crash recovery, AX and evaluation gates. The original 44-trial comparison is declared in `scenarios/context-*.yaml`; reproduce its source from commit `9dcc8ef` before running `PYTHONPATH=src .venv/bin/python scripts/run_context_evaluation.py`. The runner retains failed and unrun trials, keeps requested limits unchanged, and stops if its frozen source changes.

## Boundaries and current limitations

- Agent-visible tools contain no shell, arbitrary URL, database write, or unrestricted Kubernetes command. Broker and verifier use separate Kubernetes identities; application and verifier database users have SELECT-only access.
- The trusted local controller holds cluster-admin credentials for setup and scenario injection. With `runtime: isolated-docker`, the agent runs as a nonroot user in an immutable, read-only, network-disabled container with only its workspace mounted. Broker and verifier run outside that container. The Docker daemon, host, and orchestration code remain trusted.
- The local kind API server records independent mutation audit events. The controller correlates successful broker writes to exact conditional patches and rejects missing acknowledged writes or successful unmatched scoped writes. Comprehensive unsafe-execution attribution remains unassessed.
- The patched, pinned [AX runtime](docs/AX_RUNTIME_STATUS.md) passed three data-snapshot resume cycles and a real worker-capacity-loss recovery check. Full live lost-ack recovery and AX controller-death cleanup also passed on the authorized local variant; [selected evidence](docs/validation/ax-release.json) retains the preceding failed provider attempt. AX remains local to the tested macOS ARM64 variant; the GCP host uses the existing isolated Docker runtime.
- The basic/structured comparison changes an internal state tool and prompt as well as representation. Full history is archived for both. The declared [bounded-context comparison](docs/CONTEXT_EXPERIMENT.md) tests the same context policy for both variants; results must be read as a shared runtime intervention.
- The initial corpus uses declared, versioned test inputs. All reported system outcomes must come from actual executions.

## Reviews and checks

PR checks run deterministic tests, lint, and real Kubernetes acceptance; the acceptance job can also be triggered manually. It does not invoke model APIs or require model credentials. That job retains only its Markdown report and JSON result summary for 14 days, including failed runs. Kubeconfigs and raw artifact directories are excluded.

Implementation changes receive an additional **Claude Fable 5.1** review. The review uses an allowlisted, hashed source snapshot with tools disabled. Reviewer findings are suggestions that must be checked against the code and tests; a model review is not automatically an approval or permission to merge. [Review commands](docs/REVIEWS.md) describe the local workflow and cost controls; [review results](docs/REVIEW_RESULTS.md) record findings and dispositions.
