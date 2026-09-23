# Autonomy Lab

A local Kubernetes lab for testing diagnosis, bounded repair, independent verification, and recovery after interruption. The research proposal is in [PLAN.md](PLAN.md); milestones are in [BUILD_PLAN.md](BUILD_PLAN.md).

The application is real: Quote API → Inventory Service → Inventory API → PostgreSQL. The controller changes the Inventory Service's target port. A separate verifier checks HTTP responses, protected database rows, and Service configuration. The broker permits one typed field change with identity/version preconditions and a durable SQLite operation journal.

[Executed validation](docs/VALIDATION.md) records the real-system checks. The [28-trial development pilot](docs/PILOT_RESULTS.md) retains successes and non-completions, including the model agents' budget stops. These results do not establish production reliability.

The [adversarial self-review](docs/ADVERSARIAL_REVIEW.md) records open correctness findings and the remaining runtime, isolation, evaluation, and cloud-deployment gates.

## Run the acceptance demo

Requirements: Docker running, Python 3.12, `uv`, and internet access for pinned tools/images/dependencies. The initial setup downloads a Kubernetes node image and application dependencies. All cluster configuration remains in this project; commands select a dedicated `autolab-*` context.

```sh
make setup
make test lint
make demo
```

The demo creates a fresh cluster, checks healthy behavior, injects a routing fault, checks ineffective and effective repairs, challenges the verifier, exercises broker conflicts and response loss, kills broker processes at deterministic boundaries, writes evidence, and removes its cluster. Successful recovery requires a complete 30-second sampled workload window. Negative checks use shorter declared windows because conclusive failure is sufficient.

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

The pilot is development evidence, not a statistical reliability claim. Injected adversarial observations count as exposure only if they appear in the actor's recorded observations. Model token usage includes repeated input context and thinking tokens. Preflight conservatively reserves previous thinking carried by the conversation in addition to `countTokens`; [the live accounting failure](docs/TOKEN_BUDGET_FINDING.md) explains why. Infrastructure runtime and any unpriced cost remain separate from token usage.

## Boundaries and current limitations

- Agent-visible tools contain no shell, arbitrary URL, database write, or unrestricted Kubernetes command. Broker and verifier use separate Kubernetes identities; application and verifier database users have SELECT-only access.
- The trusted local controller holds cluster-admin credentials for setup and scenario injection. The Python orchestration code is trusted. This is not an isolation environment for arbitrary untrusted Python programs.
- API mutation logs are client instrumentation, not independent Kubernetes audit logs. The scorer leaves comprehensive unsafe-execution attribution unassessed.
- Checkpoint resumption currently reconstructs local files. AX runtime suspend/resume has not been executed. [AX feasibility](docs/AX_FEASIBILITY.md) records pinned source findings and the required next spike.
- The basic/structured comparison changes an internal state tool and prompt as well as representation. Full interaction history remains available to both; this does not establish a memory-compression benefit.
- The initial corpus uses declared, versioned test inputs. All reported system outcomes must come from actual executions.

## Reviews and checks

PR checks run deterministic tests and lint. The GitHub Actions workflow also provides an explicitly triggered real Kubernetes acceptance job; it does not invoke model APIs or require model credentials. That job retains only its Markdown report and JSON result summary for 14 days, including failed runs. Kubeconfigs and raw artifact directories are excluded.

Implementation changes receive an additional **Claude Fable 5.1** review. The review uses an allowlisted, hashed source snapshot with tools disabled. Reviewer findings are suggestions that must be checked against the code and tests; a model review is not automatically an approval or permission to merge. [Review commands](docs/REVIEWS.md) describe the local workflow and cost controls; [review results](docs/REVIEW_RESULTS.md) record findings and dispositions.
