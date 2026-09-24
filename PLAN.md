# Autonomy Lab

*An eval-first playground for dependable cloud agents*

**Working proposal · September 2026**

Autonomy Lab explores how agents can operate cloud systems over time, with evaluation and bounded execution authority built into the operating loop.

The question I want to investigate is:

> What would it take to trust an agent to perform a cloud operation, and what evidence should determine whether it receives more autonomy?

Autonomy Lab is a small, self-directed technical exercise for exploring that question. It is intended to produce working experiments, understandable failures, and evidence for technical decisions. This document describes the proposed design and experiments; it does not report experimental results or assume knowledge of any internal cloud architecture.

**1. The thesis**

Tool-using models can produce plausible diagnoses and remediations. Establishing whether a diagnosis is justified, whether an action is permitted, and whether the system actually recovered requires more than a plausible explanation.

My starting position is that **evaluation, execution controls, and independent verification belong in the architecture from the beginning.** I want to separate three responsibilities:

- **Reasoning:** investigate the incident and propose what to do.
- **Authority:** enforce which actions may execute against which resources and under what conditions.
- **Verification:** determine whether the intended outcome occurred and protected invariants held.

This separation should make failures easier to contain and understand. Whether additional structure improves the agent's decisions enough to justify its complexity is an experimental question.

**2. The first experiment**

I will begin with a routing fault in a small application:

```text
Client workload → Quote API → Inventory API → PostgreSQL
```

The application will run in a disposable Kubernetes environment. A scenario controller will introduce a mismatch between a Service's target port and the application's listening port. The agent must investigate, propose a permitted repair, and establish whether the application recovered.

The first substantial experiment will interrupt the agent around execution of that repair. In some runs, the mutation will succeed but its response will be lost. In others, another actor will change the resource before the agent resumes.

The primary question is:

> Does explicit, evidence-linked incident state improve recovery after interruption compared with a basic tool agent using its interaction history, under the same tools, execution policy, and budgets?

I will compare verified outcomes first, then stale or duplicate proposals, unnecessary mutations, recovery time, and cost. If both agents recover equally reliably and the additional structure only adds overhead, it has not earned its place for this task.

The execution boundary will reject invalid actions for every variant. That lets me distinguish an improvement in agent behavior from a failure successfully contained by the broker.

**3. A bounded scenario set**

The first fault is a harness integration test. Before drawing conclusions about agent behavior, I will add cases that require different decisions:

| Case | What it tests |
|---|---|
| Routing mismatch | Collect relevant evidence and make a bounded repair |
| Routing mismatch with distracting warnings | Distinguish the cause from a plausible alternative |
| Healthy application with a misleading alert | Investigate and finish without unnecessary mutation |
| Dependency failure outside the agent's authority | Escalate with useful evidence |
| Mutation succeeds but acknowledgement is lost | Reconcile an uncertain action |
| Resource changes during interruption | Revalidate the plan before continuing |
| Operational evidence contains adversarial instructions | Treat observations as evidence without granting them authority |

Each scenario will declare its initial state, injected event, observable symptoms, permitted actions, protected invariants, and outcome criteria. Hidden labels and scenario-control access will remain unavailable to the agent and the runbook baseline.

For diagnosis, I will identify observations that distinguish the plausible hypotheses. In the routing case, that could be the Service configuration together with a direct backend probe or equivalent evidence of the application's listening port. More than one evidence path may be valid.

This supports an **evidence-coverage metric**: did the agent collect a sufficient set of observations before acting? It is a useful diagnostic measure, not proof that the agent used those observations correctly.

Held-out cases will include variations in names, ports, distracting evidence, and interruption timing. Over time, I will add causal variations; renamed copies alone do not establish generalization.

**4. Architecture and responsibility boundaries**

| Component | Responsibility |
|---|---|
| Eval harness | Prepare isolated environments, inject faults, run comparisons, and collect results |
| Agent harness | Run the model and tools, manage incident state, and support interruption and resumption |
| Action broker | Resolve targets, enforce authority and preconditions, track operations, and record execution evidence |
| Application environment | Provide real workload behavior, Kubernetes resources, and operational observations |
| Independent verifier | Assess application behavior and invariants through its own read path |

The operating loop is: **observe → investigate → propose → authorize → execute → verify → continue, complete, or escalate.**

The development loop is: **run evals → inspect failures → change one component → compare outcomes and regressions.**

I plan to use Google's open-source AX for isolated task execution and suspend/resume, validating the required behavior against a pinned revision. Its public interfaces are evolving. The lab will explicitly own its incident records and action semantics rather than assume that runtime recovery reconstructs an operational decision. [AX repository](https://github.com/google/ax)

AX's runner documentation describes restoring a persistent workspace into a fresh container. The application must therefore persist the state it needs and reconcile external effects after resumption. Paired experiments will also require isolated application environments: restoring an agent checkpoint does not restore Kubernetes or PostgreSQL state. [AX runner contract](https://github.com/google/ax/blob/main/docs/runner.md)

The agent's infrastructure interface will be a small set of typed observation and remediation tools. The first implementation will expose one bounded mutation. Infrastructure credentials will reside with the broker; the agent will not receive unrestricted shell or `kubectl` access.

**5. The action contract**

A routing proposal will carry the resolved resource identity, observed version, intended field change, supporting observation references, and an operation identifier. The broker will independently check current authority, target scope, preconditions, and remaining budget.

For the first action, the contract will limit changes to the designated Service and field in the test environment. The broker will enforce those limits even if the model supplies a persuasive but incorrect explanation. Authorization is not proof that the diagnosis is correct; the verifier remains necessary.

Conditional Kubernetes updates can reject a mutation based on an outdated resource version. A condition on one object does not establish that every dependency used in the diagnosis is unchanged, so relevant dependencies must also be reconsidered before execution. [Kubernetes update semantics](https://kubernetes.io/docs/reference/using-api/api-concepts/#updates-to-existing-resources)

The broker will durably record intent before dispatch and distinguish acknowledged, rejected, and uncertain outcomes. Repeated operation identifiers will be checked against the original request. An uncertain action will enter reconciliation using operation records, execution evidence where available, and current resource state.

Reconciliation may establish completion, permit a safely revalidated retry, or leave ambiguity that requires escalation. An operation identifier alone does not guarantee exactly-once external effects. Testing the gap between mutation and outcome recording is part of the experiment.

Rollback will be treated as another conditional action. A stored prior configuration is useful evidence, but restoring it must not overwrite legitimate intervening work.

**6. Verification and honest completion**

The independent verifier will assess the environment against criteria defined before the run. It will use known workload inputs and expected application behavior, rather than accept the agent's proposed success criteria.

For the initial application, it will check correct quote totals and availability responses, protected data and configuration invariants, and sustained behavior over a declared observation window. A successful tool call, healthy pod, or cleared alert alone will not establish recovery.

The verifier will return **verified success, verified failure, or indeterminate**, with supporting evidence. Its own unavailable probes or inconsistent readings must not silently become agent failures or successes.

A separate scorer will compare the agent's claims and actions with the verified outcome. An attempted repair that fails, followed by an accurate report and escalation, is different from claiming that an unresolved incident is fixed.

Restraint will be assessed from the agent's attributable action sequence as well as the final state. A final diff alone can miss a harmful change that was later reversed or include changes made by the fault injector and other actors.

The verifier will itself be tested: a no-op repair must not pass; plausible but incorrect application responses must be detected; and a verifier outage must produce an indeterminate result. The agent will not be able to modify the verifier, its fixtures, or the scenario's outcome criteria.

**7. Comparing complete agent releases**

The unit under evaluation will be an immutable **Agent Release** containing the model configuration, instructions, tool implementations, skills, memory configuration and contents, execution policy, budgets, and harness version. Each experiment will also record the scenario, environment, and verifier versions.

I will use three baselines:

| Variant | Purpose |
|---|---|
| Deterministic runbook | Establish what conventional automation can achieve from the available observations |
| Basic tool agent | Establish what a simple model-and-tool loop can achieve using persisted interaction history |
| Structured operational agent | Test whether explicit incident state and evidence links improve decisions |

All acting variants will share the broker's mandatory controls and independent scoring. Model-based variants will use the same model, tool interface, and budgets for the initial comparison. A no-agent control will help identify recovery caused by the environment or another actor.

I expect the runbook to be strong on a predictable routing fault. If it wins, that identifies where agent complexity adds little value. The agent becomes interesting when investigation must distinguish ambiguous situations while preserving those same execution constraints.

Each report will include:

- Verified recovery on repairable incidents, correct no-action decisions, and appropriate escalation, reported separately.
- False completion claims and indeterminate outcomes.
- Unsafe proposals and unsafe executions, distinguished explicitly.
- Evidence coverage, stale or duplicate proposals, and unnecessary mutations.
- Model and tool usage, elapsed time, estimated cost, and human intervention where applicable.

Comparisons will use matched scenario conditions, isolated resets, controlled run order, and repeated trials. Before the comparative evaluation, I will fix the primary measures, scenario set, repetition count, and treatment of failures and timeouts.

Results will show denominators and uncertainty where the sample supports it. Repeated trials from one scenario will not be treated as independent evidence of broad coverage. Consistency across repeated attempts will matter alongside average success. A small pilot may justify descriptive conclusions without supporting a strong statistical claim.

Development cases will support iteration; regression cases will preserve prior behavior; held-out cases will test generalization. Once a held-out case is used to tune the system, it will no longer count as unseen evidence.

**8. Durable state, memory, and failure diagnosis**

The structured agent will persist observations with source and time, hypotheses linked to evidence, action intents and outcomes, and policy and budget decisions. Model context will be reconstructed from these records after interruption.

On resume, it will reconcile uncertain actions, revalidate authority, refresh observations relevant to the next decision, and reconsider hypotheses affected by changes. Freshness limits can guide observation refresh; they cannot prove that the world has remained unchanged. Mutation preconditions remain necessary.

After the initial recovery experiment, I want to test a second hypothesis: **similar but irrelevant incident memory can encourage an agent to skip necessary investigation.** I will compare no memory, relevant memory, misleading memory, and stale memory while holding the model, tools, and policy constant. Evidence coverage, verified outcomes, and investigation cost will help show where memory helps or hurts.

Failure analysis may also compare a different model, explicitly supplied diagnostic evidence, or a targeted harness change. These are diagnostic interventions, not automatic proof of root cause. Supplying evidence changes both access and salience; a stronger model may improve investigation as well as reasoning. Trajectories will be needed to understand what changed.

**9. What the evidence would justify**

The lab will exercise read-only investigation, recommendation, approval-required execution, and bounded autonomous execution under explicit policies. Authority will be defined by action, resource scope, environment, preconditions, and operational limits. It will remain revocable.

Passing a lab evaluation, deploying a release, and expanding its authority are separate decisions. The experiments can identify failures, compare designs, and support a defined next stage of testing. They cannot establish production safety across unfamiliar services or workloads.

My initial platform hypothesis is that release identity, trajectory records, action and policy interfaces, and evaluation execution are useful shared infrastructure. Domain owners should define action semantics, correctness invariants, and acceptable exposure within broader platform constraints. I want the experiments to sharpen that boundary rather than assume it in advance.

**10. Implementation sequence and intended output**

1. **Establish the verifier.** Build one application and routing fault. Demonstrate healthy behavior, failed verification after injection, recovery after scripted repair, and rejection of a no-op repair.
2. **Add the execution boundary.** Implement the typed action, preconditions, operation records, and controlled interruption points. Exercise stale updates and uncertain outcomes with deterministic clients.
3. **Introduce the agents.** Add observation tools, the basic agent, the structured variant, and complete trajectory recording. Include healthy and out-of-authority cases before claiming diagnostic capability.
4. **Run the comparison.** Evaluate matched cases under common controls, report failures and uncertainty, and identify one reproducible failure mechanism.
5. **Demonstrate an improvement.** Make a targeted change, rerun the comparison and held-out variations, and explain what improved, what became more expensive, and what remains unresolved.

The intended output is a reproducible scenario, versioned releases, comparative results, and a few annotated trajectories. I would rather bring one well-understood failure and improvement to the discussion than a large collection of successful demonstrations.

Optimization, security hardening, richer skills, and longer-running workflows are possible extensions. The first implementation will stay focused on diagnosis and bounded remediation; it will not attempt to become a general Kubernetes copilot, a new runtime, or a multi-cloud platform.

The questions I would most like to compare notes on are:

- Which failure classes currently limit dependable autonomy most: investigation, execution, verification, or coordination between them?
- What belongs in a shared agent and eval platform, and where do domain-specific semantics resist standardization?
- What evidence has been most useful in deciding that a capability is ready for a broader scope of operation?

I expect some of my initial assumptions to be wrong. The purpose of the lab is to find out which ones, understand why, and arrive with technical opinions grounded in experiments.
