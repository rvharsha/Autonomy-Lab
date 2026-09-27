# Bind authorization to execution conditions

This is a prerequisite for combined program/contract admission. It narrows the
existing admitted-program path; it does not enable admission of the precise
heartbeat contract or transfer approval from an earlier runtime.

## Decision and scope

An evaluated program must only execute the semantics exercised by its calibration.
The current program calibration exercises `service-resource-version-v1`. The
admission definition now names that contract, and its identity includes that
field. The broker supplies its validated durable binding and constructed patch
while holding the dispatch claim transaction. The registry commits these exact
conditions with the one-use authorization. The adapter compares the stored
conditions with the actual patch immediately before transport. An older ledger
without the conditions cannot reconstruct them or gain new authority.

The new bound callback is exclusive with the existing low-level callback. Other
non-admitted mechanism experiments retain their old callback. Agent proposals
cannot choose either callback or an execution contract. The campaign's existing
refusal of precise-contract program admission remains in place.

## Prospective validation obligations

Before merging, run tests, lint, a bounded Fable source review, and the real
Kubernetes acceptance suite for this exact runtime. Program lifecycle acceptance
must reproduce its newly executed 24-trial calibration and four lifecycle cases;
the offline checker must bind every authorization condition to the broker journal
and independently captured Kubernetes request. Failed or incomplete execution is
retained. These are development regression runs, not fresh confirmation or a
claim of autonomous learning.

Exercise wrong contract, request, condition hash, snapshot, patch and port index;
missing or changed permit conditions; stale/withdrawn admission; and reuse of an
operation ID. Keep historical confirmation pins unchanged. Unit selection tests
may use explicitly authored historical inputs, while a separate unmocked test
requires the historical entry point to reject this changed runtime. Earlier real
cohorts remain reproducible using their archived exact source.

Kill a real child process with SIGKILL after the registry commit and before the
broker claim commits, both with and without intervening withdrawal. Check both
SQLite ledgers after reopening: one retained authorization and condition record,
prepared intent, reserved budget, no dispatch event, and no transport call. An
explicit resume must refuse the consumed authorization, retain it, and release
only the unsent operation's reservation. This process/storage test uses an
authored adapter and must not be presented as a Kubernetes incident. The existing
real Kubernetes lost-acknowledgement case separately tests the opposite boundary:
a remote effect after a committed claim remains reconciliation-only after restart.

## Next decision

Precise-contract admission still requires a trusted, runtime-bound evidence
checker and newly executed qualification of that new runtime. The known final-slot
contexts may serve as regression qualification, not another novel confirmation.
Then test the same workload across explicit durable budget grants without hiding
unresolved operations. A [disposable shadow selection test](SHADOW_SELECTION.md)
can exercise an automatic known-configuration update before these deployment
requirements are complete. Discovery and incremental learning value still require
a separately evaluated proposer comparison; the small catalogue requires an
exhaustive non-model comparator.
