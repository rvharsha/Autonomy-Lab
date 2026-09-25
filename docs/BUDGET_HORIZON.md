# Retry now or preserve a later repair opportunity?

This authored development comparison asks whether a policy that improves one
incident can worsen customer outcomes over a longer operating window. It changes
no action authority, runtime, broker budget rule, model or admission decision.

Three exact policies share one trusted interpreter: maintained bounded refresh,
one repair attempt per episode, and a no-repair control. Every campaign starts
with two total dispatch slots and a fresh disposable workload. Each workload
persists for its entire 210-second calendar; operator restarts never replenish
its budget. Rejected dispatched API requests remain spent.

## Frozen sequence

| Offset | Controller action |
|---|---|
| 20 seconds | Stop the initial healthy operator |
| 25 seconds | Break Inventory Service routing |
| 45 seconds | Start an operator; for every attempted repair in this incident, change only the Service annotation after preflight so the stale conditional PATCH reaches the API |
| 80 seconds | Restore routing through the separately attributed controller |
| 120 seconds | Introduce a second routing fault |
| 140 seconds | Start another operator; introduce no further contention |
| 210 seconds | Finish the original calendar and clean up |

The same controller rule applies to all policies; it does not wait for an
operation that a policy declines to propose. No-repair is an observing policy
that escalates, not an actor-free environment. Every arm must retain the first
customer fault, independent intermediate recovery and second fault.

The hypothesis is that refresh spends both slots on the first incident's
contention, while a single-attempt policy preserves one for the second incident.
The controller's intermediate restoration must never be credited to a policy.
Earlier stable-conflict evidence explains why refresh can help in another
context; it is a separate cohort, not a matched trial in this comparison.

## Measurement and decision

The primary descriptive contrast is healthy, failed and unknown customer windows
over the full campaign and after the second response deadline. Report actual API
attempts, spent slots and unsent budget refusals separately. An escalation can be
correct while customer requests fail. A positive result demonstrates a tradeoff
under this declared resource constraint, not that single-attempt repair is
universally better or that a model is necessary.

All three declarations and their seeded order are saved before provisioning.
Attempt each arm once; retain failed and unrun attempts. Independent raw-probe,
audit, program-pin and operation-binding checks distinguish real API rejection
from a preflight refusal. The evaluator checks exact controller patches, all
namespace mutations, fixed schedules, complete calendars, protected state,
resource identity, cumulative budget and cleanup. The expected policy response
sequence is checked separately from the customer-outcome hypothesis; a complete
experiment can record a hypothesis that was not observed.

Run `PYTHONPATH=src .venv/bin/python scripts/check_budget_horizon.py` on the
existing disposable Docker/kind environment. No model credential is used.
The `Budget horizon` CI workflow retains credential-free evidence even on failure.

This is an authored development stress sequence motivated by code inspection.
It is not a hidden test, generated policy, admission/rollout result, sustained
availability claim or cost-effectiveness estimate. If the tradeoff is observed,
the next comparison must include both stable and continuing contention and
fresh incident sequences before choosing a policy. A fixed two-dispatch campaign
is an experimental operating contract, not a claim that production operators
should retain a lifetime budget of two writes. No broader permission or language
feature is needed to test this question.
