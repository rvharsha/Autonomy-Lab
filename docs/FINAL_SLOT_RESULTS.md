# Final-slot confirmation result

The six-case study in [PR 25](https://github.com/rvharsha/Autonomy-Lab/pull/25)
qualified its predeclared selection gate on exact source
`4a80d1d31658a3a7aea4112a25c915b6e5c61f1c`. The
[execution and reproduction workflow](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36297772135)
passed all five jobs. Selection grants no admission or deployment authority.

Each case ran once for 210 seconds with 21 independently scheduled customer
samples, three operator starts and two cumulative dispatch slots. The first
repair consumed one slot before the recurring incident. The same finite program
and exact runtime ran under both execution contracts.

| Change around the second response | Legacy healthy / failed | Precise healthy / failed |
|---|---:|---:|
| Heartbeat after preparation | 11 / 10 | 17 / 4 |
| Heartbeat and protected annotation after preparation | 11 / 10 | 11 / 10 |
| Protected annotation before the operator's observation | 17 / 4 | 17 / 4 |

All six cases had complete measurement and cleanup. All 24 specified corruption
controls reached their required refusals. Offline reproduction matched the
original result, with all 1,015 original artifact files unchanged. There were
12 actual broker requests: nine acknowledged and three rejected with HTTP 422.
In the protected-after-preparation case, requests were sent and Kubernetes
rejected their conditions; the operators did not abstain.

The result supports a narrow engineering conclusion: under the declared
heartbeat-only interference, more precise execution conditions preserved the
last repair opportunity without allowing a stale protected-metadata condition.
It does not establish model learning, production incident prevalence, continuous
availability, or net economic value. Completed operator verification files are
a lower bound on request work. The prior [eight-case cohort](CONTRACT_CONFIRMATION_RESULTS.md)
remains failed original confirmation and subsequent development evidence.

The [frozen protocol](FINAL_SLOT_CONFIRMATION_GATE.md) and
[source review](FINAL_SLOT_REVIEW.md) describe this study. Reproduce original
results using its exact source; later runtime changes must not silently update
its pin. The next step is [bound dispatch authorization](BOUND_DISPATCH_AUTHORIZATION.md),
then separate qualification for precise-contract admission and explicit persistent
budget cycles.
