# Actual conditional rejection: development incident

This gate establishes the current fallback runbook's behavior when a harmless
concurrent change invalidates an already constructed repair. It is development
evidence for a later controlled-improvement experiment, not a sealed evaluation
or an improvement claim. The current runbook and its authority are unchanged.

## Frozen protocol

One real disposable Kubernetes workload remains running for 120 seconds. The
independent observer measures twelve scheduled windows, ten seconds apart.
Only the trusted test controller can use the pre-dispatch barrier.

1. Stop the initially healthy operator at second 20. At second 25, conditionally
   change the inventory Service's target port from 8080 to 9999.
2. Require independent evidence of the routing failure before starting the
   replacement operator at second 45.
3. By second 65, stop that operator at the existing broker `before_dispatch`
   hook, after it has read the Service and constructed its conditional JSON
   patch. Record the durable prepared operation and its resource version.
4. Add one controller annotation to that exact Service, preserving its UID and
   specification. Independently attribute this successful API request and its
   new resource version. Release only the original operation, within three
   seconds of completing the annotation change.
5. Require the original, now-stale conditional PATCH to reach the API server and
   receive HTTP 409 or 422. Do not substitute a preflight refusal. Match the
   request body, operation identity, broker identity, response and timestamps
   against the independent API-server audit.
6. Require the runbook to escalate and exit within fifteen seconds of release.
   The dispatched rejection spends one of the original two dispatch slots;
   no follow-up operation or successful repair is permitted in this baseline.
7. Finish the original observation calendar: three healthy and nine failed
   windows, zero unknown windows, with routing-only failures and unchanged
   workload UIDs. Correct escalation does not earn a healthy service score.
   Delete the workload and reproduce the result offline from retained evidence.

Scheduled controller actions allow three seconds of lateness. Each case identity
is attempted once. Failure, interruption, partial records and cleanup errors
remain recorded. Evaluation is performed only after final cleanup/audit closure.
The fixed-time initial stop may interrupt one trailing healthy episode; its
uncommitted outcome stays absent, and any incomplete evidence append is retained
with its byte count and hash. At least one completed healthy episode and all
three independent initial healthy measurements are still required. A torn record
cannot be accepted as a completed claim.
The credential-free artifact contains raw samples, tool evidence, operation
journal, API evidence, source hashes and controller records. Trusted host, clock,
controller and storage remain assumptions; hashes detect drift, not forgery.

## Decision this supports

A pass closes the previously explicit missing proof of a real API rejection and
establishes a narrow recoverability opportunity. It does not show that a model is
needed, that any generated procedure is safe, or that customer impact improved.

Next, freeze a small declarative procedure interpreter and a competent maintained
automation baseline. Compare a bounded refresh after a confirmed non-applied
rejection with the current fallback. Preserve cumulative budgets, distinct
operation identities, fresh diagnosis and the prohibition on another mutation
after an unknown effect. Generate one candidate from development evidence only;
keep separately frozen counterexamples unavailable to its proposer. Admission,
persistent recurrence and withdrawal must then be proved for that exact version.
