# Finite policy comparison

This development experiment asks whether any configuration in the current
[eight-program language](RESTRICTED_PROCEDURES.md) improves customer outcomes
over the maintained `verify / repair / refresh` program across both declared
contention contexts. It does not propose or promote a procedure. A null result
retains the maintained baseline.

## Frozen comparison

The plan job freezes exact program bytes, dependency hashes, controller source,
all sixteen cases, their seeded order and four disjoint shards before any workload
is provisioned. Every configuration runs once in each context, including choices
that are not reached. No static equivalence claim substitutes for a trial.

Each case uses a fresh disposable Kubernetes cluster. Its workload persists across
three operator generations for a 210-second calendar: 21 one-second customer
measurement windows, two total dispatch slots, and the existing routing-only
authority. Each real API attempt spends a slot, including a rejected write.
Restarting the operator does not replenish the budget.

| Offset | Both contexts | Stable after first rejection | Continuing contention and recurrence |
|---|---|---|---|
| 20 s | Stop initial healthy operator | | |
| 25 s | Break inventory routing | | |
| 45 s | Start first response | Conflict only its first actual prepared dispatch | Conflict every actual prepared dispatch |
| 80 s | | No controller repair | Controller restores routing |
| 120 s | | No new fault | Controller breaks routing again |
| 135 s | Stop/reap first response operator if still alive | | |
| 140 s | Start second response, no contention | May encounter the original unresolved fault or a healthy service | Encounters the second fault |
| 210 s | Finish observation and delete owned cluster | | |

Conflicts are annotation-only conditional version changes after preflight and
before the actual broker request. The audit must contain the corresponding
409/422 rejection. A policy declining repair has no such exposure; its customer
failure remains an outcome, and it receives no credit for handling a rejection.
Controller repairs are independently attributed.

## Evaluation and selection

Measurement validity requires the entire on-time calendar, raw semantic probe
reproduction, unchanged resource identities, exact source and program bindings,
closed API audit, declared controller timing and successful cleanup. Every
mutation must be attributed. Existing safety and cumulative-budget checks apply.
First-response deadlines and worker failures determine candidate eligibility.
Customer outcomes are reported separately: escalation is not customer recovery.

Selection requires valid evidence for all sixteen cases and an eligible baseline.
A challenger must be eligible in both contexts, have at least as many healthy
windows and spend no more dispatches than baseline in each, and have strictly more
healthy windows in at least one. Ties retain baseline. Multiple qualifying
challengers use canonical policy-ID order. There is no assumed incident-frequency
weighting and no aggregate score that can conceal a regression in one context.

The independent aggregation job reconstructs results from raw campaign evidence;
it does not trust uploaded evaluation summaries alone. Missing/failed cases block
selection. Failed attempts, partial calendars and unrun ledger entries remain in
artifacts. No automatic retry or replacement sample is permitted within a cohort.
A correction requires a new source-pinned cohort, retaining the failed one.

The budget is sixteen campaigns, at most two dispatches each, four shard jobs
bounded to 35 minutes each, and zero proposer requests. Freeze and reproduction
jobs are bounded to ten minutes each. Regression qualification and review costs
are additional and must be recorded separately. Human active time and billed
compute cost are unknown unless independently measured; neither is assumed zero.

## Reproduction

The `Finite policy comparison` workflow publishes `policy-search-plan`, four
`policy-search-shard-N` archives and `policy-search-selection`. On the exact source
revision, download the plan into `artifacts/policy-search-plan` and each shard
under `artifacts/policy-search-download/policy-search-shard-N`, then run:

```sh
PYTHONPATH=src .venv/bin/python scripts/check_policy_search.py reproduce \
  artifacts/policy-search-plan/plan.json \
  artifacts/policy-search-download \
  artifacts/policy-search-reproduced
```

The destination must not already exist. This offline command needs no cluster
credentials. Live trials use `freeze` followed by `run PLAN SHARD DESTINATION` for
shards 0 through 3. Artifact paths are allowlisted; kubeconfigs and owner logs are
excluded.

## Decision boundary

These are authored development contexts. Backend-observation unavailability,
rejection followed by a changed diagnosis, and uncertain writes are not matched
search contexts in this cohort. Existing regression gates exercise parts of those
paths for maintained programs; they do not establish comparative coverage for all
eight candidates.

A selected challenger would still need a separately frozen fresh-confirmation
protocol, complete causal coverage, and admission/canary/withdrawal evidence before
reuse. Selection grants no authority. If the current language contains no
qualifying improvement, stop this selection attempt and report that limitation.
Do not widen authority or add a paid model merely to obtain a positive result.

The full continuous, improving-operator objective remains open. This comparison
can support a bounded policy decision; it cannot establish generalization,
production availability, learned improvement, model value or human-work savings.
