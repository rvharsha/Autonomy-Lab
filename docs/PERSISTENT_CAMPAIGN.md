# Persistent workload: operator restart gate

The [first real results](PERSISTENT_CAMPAIGN_RESULTS.md) passed on GCP and in CI.

This is the first implementation slice of [continuous ownership](CONTINUOUS_OWNERSHIP_PLAN.md),
not a completed autonomous-cloud or improvement loop. It uses the existing trusted
deterministic runbook. No model request is made by the campaign.

One owner provisions one real Quote/Inventory/PostgreSQL cluster, records Namespace,
Service, Deployment, PVC and Pod UIDs, and deletes its resources at campaign end.
The operator and independent observer have separate processes and port forwards.
Killing the operator's registered process group cannot reset the workload, the
observer, the frozen calendar or the broker's SQLite journal. The operator's
exclusive lock is not inherited by its subprocesses. A duplicate operator is
refused. Operator episode directories preserve incomplete attempts as unknown.

The broker keeps the campaign identity and dispatch budget across operator starts.
Restart reconciles prepared/dispatching/uncertain operations and escalates instead
of replaying them. This gate runs on a healthy workload and requires zero repairs;
recurrence, budget exhaustion and response-loss integration gates remain pending.
The runbook and its authority are trusted host code in this slice; process separation
does not isolate an untrusted actor from the host's credentials or files.

## Frozen first gate

[The contract](../scenarios/campaign-restart.json) fixes 120 seconds of measurement,
12 scheduled slots 10 seconds apart, a one-second minimum verifier window per slot (including a terminal probe),
two-second request timeouts and maximum start lateness, two cumulative dispatches,
three operator start attempts (initial, refused duplicate, resumed) and at most
45 seconds of operator downtime. The cleanup lease is 1,800 seconds including
provisioning. Every observation uses the existing independent expectation corpus,
real HTTP requests, a read-only database connection and scoped Service reads.

[The checker](../scripts/check_campaign.py) declares before launch: stop the first
operator at offset 30 seconds, start the replacement at offset 60, require at least
two complete independent measurements wholly inside that downtime, and require a
completed healthy episode from each successful operator generation. Collection must finish before the next scheduled slot; the minimum verifier
window is not a one-second collection deadline. Actual start/end times and request
latencies remain explicit. Every scheduled slot must pass; missing, late or indeterminate measurements fail this gate. All
11 initial workload resource UIDs must remain unchanged, no repair may occur,
normal owner cleanup must complete and two scorecard exports must be byte-identical.
A failure stays recorded under its original campaign identity, including failures
in final cleanup. The owner completion record means its window ended; only the
external checker evaluates the restart contract and issues a gate pass. Start
budgets count attempts, including a refused duplicate, and the operator CLI waits
for readiness before returning success.

Measured request latency and HTTP outcomes are exported alongside coverage, raw
sample hashes, worker attempts and operation accounting. Request counts include
expected negative corpus cases (such as unknown products); a non-200 response is
not automatically a correctness failure. Do not infer continuous availability
between probes, customer traffic volume, production reliability or ROI.

## Run and inspect

On an isolated Linux Docker host with `make setup` completed:

```sh
PYTHONPATH=src .venv/bin/python scripts/check_campaign.py
PYTHONPATH=src .venv/bin/python -m autonomy_lab.campaign_report \
  artifacts/campaign-gate-ID/campaign artifacts/campaign-gate-ID/export.json
```

The checker prints its unique evidence directory. Keep the whole directory private:
it includes cluster credentials. Only reviewed scorecards and gate receipts should
be published. Source, contract and checker hashes bind each run to its input files.

This first gate proves normal owner cleanup after an operator-group interruption.
A detached janitor also registers campaign workers, but a whole systemd control-group
or host failure is not covered by this gate. A separately supervised owner cleanup
path and its stop/restart/kill gates are required before claiming continuous cloud
ownership. Observer restart/gaps, repeated faults, ambiguous effects, versioned
procedures, independent holdouts and comparative improvement are subsequent work.
