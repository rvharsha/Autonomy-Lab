# Bounded refresh: maintained automation baseline

The decision is whether one bounded refresh can recover from a received,
non-applied conditional rejection without repeating uncertain effects. This is
an authored deterministic baseline informed by the [conditional-rejection
incident](CONDITIONAL_REJECTION.md), not a generated procedure or sealed test.
The old fallback remains the control in the same release's conditional-rejection
CI job. Its one-rejection behavior is unchanged.

## Operating boundary

`bounded_refresh` is opt-in and defaults to false. The broker still owns policy,
conditional writes, durable operation identity and the original cumulative
budget. A received 409/422 rejection keeps its dispatch spent. A new proposal
requires the exact original operation/request, retained budget, a remaining slot,
and three new eligible observations. The same Service UID/scope must have a
changed resource version and the same incorrect target. The backend must still
be healthy at the original desired port; the customer path must return the
fixture's explicit inventory-unavailable 503. A status code alone is insufficient.

At most one new operation ID is created. A second rejection escalates. An unknown
response is looked up by its original ID; observing recovery does not manufacture
attribution. Changed identity, unavailable or malformed evidence, another cause
and exhausted budget cannot authorize refresh. The broker revalidates every new
proposal, so a race after the fresh diagnosis remains a conditional rejection.
No IAM or action family is added. The public operation response now includes the
configured budget limit alongside used budget.

The flag is prohibited with `admitted_procedure`. Current admission binds one of
two known single-dispatch variants; this baseline is explicitly experimental.
A future declarative interpreter and immutable per-operation admission bindings
must be reviewed before a generated two-dispatch procedure can be promoted.

## Frozen real cases

Run `PYTHONPATH=src .venv/bin/python scripts/check_refresh.py` on the supported
real Docker/kind environment after `make setup`. Every case is declared before
execution, attempted once, and retained if it fails; subsequent declared cases
are not retries. No model is invoked.

| Case | Required evidence and outcome |
|---|---|
| Stable conflict, 120 seconds | Controller changes only an annotation after preflight; original PATCH receives 409/422. Three fresh observations precede a distinct acknowledged repair, independent verification and later healthy customer samples. Both dispatches remain spent. |
| Continuing contention, 120 seconds | Controller performs another conditional annotation change at the second preflight. Both actual PATCH requests are rejected. Two spent dispatches, no third operation, timely escalation and continued customer failure. |
| Unknown effect with external change, 150 seconds | Real repair is interrupted after its API response but before durable acknowledgement. After an external route change, a restarted refresh-enabled operator reconciles the original operation, escalates and never dispatches a second mutation despite a remaining slot. |

The first two cases use the control's schedule: stop the initial operator at
20 seconds, inject routing failure at 25, begin repair at 45. First barrier is due
by 65 seconds; the second is due within 10 seconds of first release. Annotation
change to release is bounded by 3 seconds; terminal repair/escalation is due
within 15 seconds of first release. A controller release binds exactly one
prepared operation. The original calendar and workload persist until owner
cleanup. Customer failures and unknowns are separate from whether the operator
made a correct terminal decision. Windows between samples remain unmeasured.

All Service API mutation attempts are counted, including rejections. In the
unknown-effect case the three allowed successful requests are the admin fault,
the single broker repair, and the admin external change; any extra request,
including a rejected replay, fails the gate. Broker,
observer and verifier attempts on other resources also cannot disappear from
the audit. Probe verdicts are reconstructed from raw observations; operation
journals, original requests, controller records, changed resource versions,
source hashes, terminal evidence and cleanup are checked offline. The new cases
retain raw evidence as `bounded-refresh-results`; credential files are excluded.

The stable/continuing cases require a complete 12-slot calendar, failed customer
measurements before intervention, and the declared customer result in every
sample after the terminal decision. They do not hardcode a favorable recovery
slot during intervention. The unchanged control declares 3 healthy/9 failed
slots. Compare observed counts and deadlines from the same source release,
without pooling historical runs or claiming statistical superiority from one
attempt per case.

## Independent reproduction and next decision

On the exact tested commit with the downloaded archive extracted:

```python
from pathlib import Path
from autonomy_lab.campaign import read
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import save
from autonomy_lab.refresh import evaluate

root = Path('retained-evidence').resolve()
for gate in sorted(root.glob('refresh-gate-*/*')):
    if not (gate / 'declaration.json').exists():
        continue
    for suffix in ('a', 'b'):
        assert evaluate(gate) == read(gate / f'evaluation-{suffix}.json')
        assert scorecard(gate / 'campaign') == read(gate / f'scorecard-{suffix}.json')
    save(gate / 'reproduced.json', evaluate(gate))
```

A pass shows that maintained automation handles this development conflict while
retaining the unknown-effect boundary. It does not show model advantage,
learning, production availability, economic benefit, or safe admission of a new
procedure. Next: freeze a restricted procedure representation and maintained
baseline, isolate a single bounded proposer request from independently sealed
cases, then compare the immutable candidate with this baseline. A tie supports
bounded generation/selection, not novel discovery or a need for a model.

## Retained first execution

The first cohort at `75c21b6dc0b59f5da188959bc96eef149d7e662f`
([run 36099505746](https://github.com/rvharsha/Autonomy-Lab/actions/runs/36099505746))
failed the new gate: stable/continuing cases exposed two evaluator representation
assumptions; the unknown-effect case passed. The broker's durable receipt holds
only UID/version. The controller's `kubectl get` output omits `managedFields` by
default, as documented in the [kubectl reference](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_get/).
The corrected evaluator binds that receipt to the independent API response and
compares all Service fields except specifically omitted `managedFields`. Identity,
version, annotations, exact intended spec change, budgets and deadlines still
must match. Operating behavior and fault schedules did not change.

Original failed assessments and raw evidence remain retained and reproduce on
that source. They are not retrospectively passed. A new frozen revision must run
the complete declared cohort; these cases remain development feedback.
