# Autonomy Lab

A local Kubernetes lab for testing diagnosis, bounded repair, independent verification, and recovery after interruption. The research proposal is in [PLAN.md](PLAN.md); milestones are in [BUILD_PLAN.md](BUILD_PLAN.md).

The application is real: Quote API → Inventory Service → Inventory API → PostgreSQL. The controller changes the Inventory Service's target port. A separate verifier checks HTTP responses, protected database rows, and Service configuration. The broker permits one typed field change with identity/version preconditions and a durable SQLite operation journal.

[Executed validation](docs/VALIDATION.md) records the real-system checks. The [28-trial development pilot](docs/PILOT_RESULTS.md) retains successes and non-completions, including the model agents' budget stops. These results do not establish production reliability.

The [adversarial self-review](docs/ADVERSARIAL_REVIEW.md) records the original findings and remaining architecture gates. The [correctness follow-up](docs/CORRECTNESS_FIXES.md) tracks their implementation, validation, and review status.

The [funded Fable follow-up](docs/FUNDED_REVIEW.md) records completed source reviews, checked findings and durability fixes. The Anthropic credit blocker is resolved.

A [focused completion experiment](docs/COMPLETION_EXPERIMENT.md) tests one shared prompt change under unchanged budgets: supported completion rose from 3/8 to 6/8 in matched development conditions. Structured lost-acknowledgement trials still exhausted their budgets. This is development evidence; held-out validation remains outstanding.

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

The selected model is **Gemini 3.8 Flash**, API ID `gemini-3.8-flash`. A basic agent retains interaction history. A structured agent also maintains explicit incident state through an internal tool. Both have the same external observations, repair interface, verifier, and execution policy.

The credential loader recognizes `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `GEMINI_KEY`, first in the environment and then in `~/Dev/.env`. It reads only those assignments, does not execute shell expressions, and does not copy the key into the repository or reports.

```sh
PYTHONPATH=src .venv/bin/python -m autonomy_lab.cli experiment \
  --manifest scenarios/pilot.yaml --env-file ~/Dev/.env
```

This invokes the live model API and may incur charges. The manifest declares the model, token/turn limits, scenario matrix, repetition count, and verification window. The command saves the manifest and source hashes before running, resets the namespace and database between trials, and records every attempted result and any unrun trials. Local model/agent failures are retained as outcomes. A missing credential stops before provisioning.

Each trial runs in a separate POSIX worker with a controller-enforced `trial_timeout_seconds` deadline (900 seconds by default), including trial setup and final verification. On timeout, the controller kills that worker's process group, preserves partial evidence, records a non-completion, and continues normal reset/cleanup. Model requests and mutations are never automatically retried after uncertain completion. A detached janitor watches controller identity and a bounded lease; it removes registered agent containers and the owned cluster after controller death.

Checkpoint schema 2 binds state to its run, release, system instructions and tool declarations. Schema 1 checkpoints remain historical evidence and are rejected without modification; there is no automatic migration or replay. Bounded HTTP runs on the worker's main thread and rejects compressed responses before decoding. The verifier caps each response at 64 KiB; model and Kubernetes responses have separate bounded limits.

The pilot is development evidence, not a statistical reliability claim. Injected adversarial observations count as exposure only if they appear in the actor's recorded observations. Model token usage includes repeated input context and thinking tokens. Preflight conservatively reserves previous thinking carried by the conversation in addition to `countTokens`; [the live accounting failure](docs/TOKEN_BUDGET_FINDING.md) explains why. Infrastructure runtime and any unpriced cost remain separate from token usage.

The [runtime work record](docs/RUNTIME_ISOLATION_WORK.md) tracks the additional isolation, crash recovery, AX and evaluation gates. The 44-trial comparison is declared in `scenarios/context-*.yaml` and runs once with `PYTHONPATH=src .venv/bin/python scripts/run_context_evaluation.py`. It retains failed and unrun trials, enforces unchanged budgets, and stops if its frozen source changes.

## Boundaries and current limitations

- Agent-visible tools contain no shell, arbitrary URL, database write, or unrestricted Kubernetes command. Broker and verifier use separate Kubernetes identities; application and verifier database users have SELECT-only access.
- The trusted local controller holds cluster-admin credentials for setup and scenario injection. With `runtime: isolated-docker`, the agent runs as a nonroot user in an immutable, read-only, network-disabled container with only its workspace mounted. Broker and verifier run outside that container. The Docker daemon, host, and orchestration code remain trusted.
- The local kind API server records independent mutation audit events. The controller correlates successful broker writes to exact conditional patches and rejects missing acknowledged writes or successful unmatched scoped writes. Comprehensive unsafe-execution attribution remains unassessed.
- The patched, pinned [AX runtime](docs/AX_RUNTIME_STATUS.md) passed three data-snapshot resume cycles and a real worker-capacity-loss recovery check. The supported deployment target remains local; live agent integration has a separate recorded gate.
- The basic/structured comparison changes an internal state tool and prompt as well as representation. Full history is archived for both. The declared [bounded-context comparison](docs/CONTEXT_EXPERIMENT.md) tests the same context policy for both variants; results must be read as a shared runtime intervention.
- The initial corpus uses declared, versioned test inputs. All reported system outcomes must come from actual executions.

## Reviews and checks

PR checks run deterministic tests, lint, and real Kubernetes acceptance; the acceptance job can also be triggered manually. It does not invoke model APIs or require model credentials. That job retains only its Markdown report and JSON result summary for 14 days, including failed runs. Kubeconfigs and raw artifact directories are excluded.

Implementation changes receive an additional **Claude Fable 5.1** review. The review uses an allowlisted, hashed source snapshot with tools disabled. Reviewer findings are suggestions that must be checked against the code and tests; a model review is not automatically an approval or permission to merge. [Review commands](docs/REVIEWS.md) describe the local workflow and cost controls; [review results](docs/REVIEW_RESULTS.md) record findings and dispositions.
