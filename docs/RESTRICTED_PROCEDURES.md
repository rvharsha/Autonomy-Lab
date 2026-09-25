# Restricted procedure language

This slice makes an authored operating policy representable as bounded data. It
resolves a prerequisite for candidate evaluation: the maintained baseline and a
future proposer use the same representation and trusted execution boundary.
It does not generate a candidate or establish a model advantage. The separate
[program admission protocol](PROGRAM_ADMISSION.md) evaluates exact definitions
and governs each new dispatch authorization.

## Exact degrees of freedom

Version 1 has exactly three decisions and eight configurations:

| Decision | Choices | Fixed boundary |
|---|---|---|
| `backend_unavailable` | `escalate`, `verify` | Verification is read-only; it requires a scoped Service and an unavailable direct-backend observation. Only independent success can justify health. |
| `repairable_routing` | `escalate`, `repair` | Existing Service/backend/application diagnosis and broker scope, conditional write and cumulative budget apply. |
| `conditional_rejection` | `escalate`, `refresh` | Received, request-bound non-application; one fresh diagnosis, same identity/scope, remaining budget and one distinct proposal. Unknown effects cannot enter refresh. |

The authored baseline is [bounded-refresh.json](../procedures/bounded-refresh.json):
`verify`, `repair`, `refresh`. No loops, expressions, arbitrary tool names, shell,
Python, network destinations, IAM changes, budgets or verifier definitions are
accepted. Duplicate keys, extra/missing fields, wrong types, unsupported versions,
invalid UTF-8 and inputs larger than 4,096 bytes fail before tool calls.

The language selects already implemented guarded decisions. Generating its best
configuration would demonstrate bounded policy selection, not discovery of the
refresh algorithm. Selecting `escalate` for a repairable route is syntactically
valid but can fail a customer recovery objective. Parsing is not empirical
acceptance, and no acceptance is inferred from a valid program or source hash.

## Execution and provenance

The legacy runbook and interpreter share the reviewed trusted decision engine.
Legacy defaults and flags retain their behavior. The program interface requires
a fresh workspace, including refusing adoption of an existing terminal claim.
The old runbook's idempotent terminal read remains available through that legacy
interface. Existing pending-operation reconciliation still precedes new campaign
episodes and retains original operation identity.

A definition binds exact original UTF-8 bytes (including whitespace), their
SHA256, and the existing release manifest of source, dependency locks, container
and workload/verifier files. The campaign freezes it before provisioning; each
episode records the full pin before any tool call. Immediately before every real
API write, the adapter rechecks current source/definition identity and the episode
pin, then atomically saves a separate operation-ID binding. A failed save or
reused binding prevents the write. Both refresh operations retain separate
bindings to the same definition and their original cumulative budget.

`procedure_program` is an explicit experimental campaign contract field. It
cannot combine with legacy `bounded_refresh` or `admitted_procedure`. These
records alone are execution provenance. Opt-in `admit_program` additionally
requires raw calibration, a program admission ledger and per-operation authorization
serialized with withdrawal. Known-variant admission remains separate and supports
only its two reviewed single-dispatch procedures. No actor receives a new cloud permission or action family.

The processes and evidence storage share a trusted host. Hashes detect drift;
they do not authenticate a hostile host or prove which machine instructions ran.
The language prevents executable candidate input; it is not a new OS sandbox.

## Declared validation

Run `PYTHONPATH=src .venv/bin/python scripts/check_refresh.py --interpreted` after
`make setup` on the supported real Docker/kind environment. The new
`restricted-procedure` CI gate attempts the same three authored development cases
as the maintained [refresh baseline](BOUNDED_REFRESH.md): stable conflict,
continued contention, and interrupted acknowledgement plus external change.
It keeps the same schedules, budgets, full customer calendar and API assertions.
The legacy baseline remains a separate same-source CI job.

Each case is attempted once and retained, including failures. In addition to all
existing raw evidence checks, the evaluator reconstructs the frozen definition
and checks every episode pin and every operation binding against raw tool
observations, broker journal dispatches and independent API request timestamps.
Both rejected and applied requests require bindings written before the API call.
Missing, extra, late, changed or cross-episode bindings fail; original base-gate
failures cannot become passes. A process killed between attempt creation and its
pin write may retain an empty unclaimed attempt, only when no committed or partial
tool evidence and no operation binding exists. Artifacts are retained under
`restricted-procedure-results` without credentials.

Authored tests cover all eight configurations, parser refusals, drift, failed
binding writes, replay, uncertainty, fresh diagnosis and verifier boundaries.
Replaying old retained observations is a compatibility check, not fresh execution
or independent evaluation. Live results require the frozen CI source and raw
artifacts; test doubles are never experiment outcomes.

## Next decision

Commit fresh independent cases outside a bounded proposer's context before its
request. Retain actual model identity, exact input/output bytes, parse decision
and costs. Compare the immutable candidate with this maintained baseline and an
authored syntactically valid adverse control. The separate admission/withdrawal gate must qualify the complete multi-operation
definition before any rollout.
A tie can establish the selection mechanism; repeated fresh incident families and
measured costs are needed to justify operating a model-assisted improvement loop.
