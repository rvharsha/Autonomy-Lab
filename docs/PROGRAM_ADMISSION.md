# Admission and withdrawal of restricted programs

This development milestone admits exact finite-policy bytes from reproduced raw
outcomes, then checks authorization at each new operation. It does not generate a
policy, claim a sealed holdout, or establish model value. All actors, host storage,
evaluator and controller remain trusted. Hashes detect drift, not authenticity.

## Calibration before rollout

`scripts/check_program_lifecycle.py --execute` freezes the baseline bytes,
interpreter/runtime manifest, eight existing calibration scenarios and randomized
three-arm order before provisioning. The 24 real trials compare the maintained
`verify/repair/refresh` policy, an authored valid adverse policy that declines
repairs, and no action. Thirty-second verification windows and the existing raw
semantic checks, execution audit and cleanup rules apply. The adverse policy must
fail the routing and lost-ack recovery cases; baseline must pass all eight.

Every trial request includes the complete frozen configuration. Each program
trial additionally retains the exact definition pin before any tool observation.
The evaluator reconstructs scores, raw verifier probes, scoped API audit and pins
on the exact release. Missing or malformed records refuse admission; complete
behavioral failures produce ineligible receipts. A candidate's JSON validity or
self-reported acceptance is never admission evidence. This is a known development
calibration, not independent evidence of generalization. Refresh execution is
separately exercised in the live admitted stable case.

The admission definition binds program bytes/runtime, calibration protocol,
source dependencies and built image metadata. The runbook executes in the trusted
trial worker; the built agent image is release metadata. Each persistent workload
receives a fresh ledger and reproduces admission before provisioning.

## Two durable decisions

An episode starts with an immutable selected version and activating revision.
The broker obtains a separate, one-use authorization before each dispatch claim.
That authorization binds the original operation ID, full proposal digest, episode,
program definition and activation/decision revisions. The registry records it
under the same SQLite `BEGIN IMMEDIATE` lock used by withdrawal. Withdrawal and
new authorizations therefore have one transaction order. Timestamps support audit
correlation; they do not decide which side of withdrawal an authorization occupies.

Withdrawal blocks new episode starts and all later operation authorizations,
including a refreshed proposal in an already running episode. It cannot cancel
an authorization that committed first or undo an API request already sent.
Historical authorizations may be inspected but cannot be reused to dispatch:
the broker's one-use journal claim, unique authorization ID and durable per-operation
binding stay mandatory. Activation changes also prevent an older pin from obtaining
new authorizations. A rejected candidate does not relabel an active pin.

The broker still controls scope, conditional PATCH and cumulative dispatch budget.
A refusal before dispatch releases only that unsent reservation; a prior API
rejection remains spent. Crash between authorization and broker dispatch leaves
prepared intent reserved. Crash after actual write leaves dispatching/uncertain
intent reserved. Restart reconciles original IDs before admission and never resumes
an old episode or automatically replays either case. A guard failure after the
dispatch claim but before transport is recorded as known not sent, never as lost
acknowledgement. Its already-claimed budget slot stays spent conservatively; it
cannot trigger refresh. Registry refusal-storage failure is separately identified
in that broker outcome. The registry and broker use
distinct databases; authorization is durably committed first, not an atomic commit
across both databases. This ordering can conservatively strand intent but cannot
justify replay. Failed authorization storage fails closed.

## Declared persistent cases

All four declarations are frozen before calibration starts. Attempt each once;
retain failures and unrun cases. Use separate disposable workloads and preserve
resource identity within each case, a complete customer measurement calendar,
scoped independent API evidence and owner cleanup.

1. **Admitted stable refresh:** a real conditional rejection, fresh diagnosis and
   successful second operation under the same admitted program. Twelve samples
   over 120 seconds. Both actual API attempts require distinct authorizations.
2. **Withdrawal before the first authorization:** pause a valid prepared repair,
   withdraw, then release it. No broker API request, no spent slot, recorded
   authorization refusal and continued measured customer failure. This isolates
   withdrawal without an unresolved effect or conditional rejection.
3. **Withdrawal between attempts:** spend one slot on a real conditional rejection,
   prepare the fresh second proposal, withdraw, then release it. Only the first
   request reaches the API; one slot remains spent. Keep the same episode, both
   original IDs and the failed customer calendar.
4. **Withdrawal after an actual write before acknowledgement:** use the unchanged
   150-second interruption schedule. Withdraw at the real-write barrier, terminate
   only the operator, restart after 30 seconds, reconcile the original uncertain
   operation and escalate without new admission/authorization or replay. Independent
   audit can attribute the write while the broker journal still lacks acknowledgement.

Offline checks reproduce the calibration receipt, admission decisions, episode
pins, operation authorizations, original broker events, actual conditional requests,
raw customer verification and final exports. Unit fixtures challenge malformed,
missing, late or mismatched evidence, stale/concurrent decisions and crash boundaries;
these fixtures are not live experiment outcomes.

The next independent comparison still needs maintained automation, exhaustive
finite selection and one bounded model proposal under identical frozen rules.
Passing this lifecycle proves evaluation-controlled configuration execution, not
algorithm discovery, model necessity or production availability.
