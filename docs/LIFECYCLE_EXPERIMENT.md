# Missing evidence and campaign-owner termination

This preregistered protocol extends the [ambiguity experiment](AMBIGUITY_RESULTS.md).
The decision is whether the persistent operating foundation can retain missing
evidence and clean up after its owner disappears, before introducing procedure
updates. These are deterministic campaigns with real Kubernetes, HTTP/database
observations, OS signals and API-server audit. Authored fixtures only test the
implementation; they cannot supply experiment results.

## Telemetry: two different missing-evidence boundaries

The [210-second contract](../scenarios/campaign-telemetry.json) fixes 21 slots ten
seconds apart, one-second minimum windows with terminal probes, two-second request
timeouts and start-lateness bounds. At most three operator starts and two broker
dispatches are allowed. The [controller](../scripts/check_telemetry.py) declares
its schedule and hashes before provisioning one persistent workload.

| Offset from measurement start | Event |
|---|---|
| 25 seconds | SIGSTOP the registered observer process group; confirm stopped state |
| 65 seconds | SIGCONT the same observer; retain its original identity |
| 80 seconds | Stop the initial operator |
| 85 seconds | Conditionally change Inventory routing from 8080 to 9999 |
| 105 seconds | Start a repair operator after independent client failure is observed |
| By 130 seconds | Reach the real post-response/pre-acknowledgement barrier |
| Within 3 seconds of the barrier | Request termination of only the repair operator |
| 5 seconds after confirmed termination | Remove `get` from the broker Role; retain scoped `patch` |
| 15 seconds after confirmed termination | Start the third operator |

Controller schedule events may be at most three seconds late. Require escalation
and clean exit within fifteen seconds of the last start request, and restart
downtimes at most 45 seconds. The observation calendar ends at the original 210
seconds, followed by normal owner cleanup. No reset or budget renewal occurs.

The [scorer](../src/autonomy_lab/telemetry.py) requires exactly slots 3-6 to remain
missing/unknown. Earlier committed samples must be byte-identical. At least two
complete healthy operator claims must occur during the collection outage, proving
that actor claims are not substituted for absent independent measurements. All
other slots must be assessed. Observed pre-fault slots must be healthy; fault slots
may fail only from the injected routing mismatch and resulting client 503s.

One real conditional broker repair must be independently audited and interrupted
before acknowledgement. A later actual broker Service GET must receive API-server
403, and reconciliation must record `unavailable`, with attribution not established
and recovery not verified. Require one uncertain operation, one spent dispatch of
two allowed, no new episode or write, and escalation. At least three independent
samples after restart must be healthy. A current healthy service does not make an
unavailable operator observation available.

Account for all three successful Service/Role mutations: the Service fault injection,
the broker repair, and the broker Role change. Preserve the eleven workload UIDs
and protected state at observed points. Dependent Kubernetes controller updates
outside these resource types are not included in the actuator counts. Duplicate
exports must match byte for byte.
This tests an actual collection interruption and permission-denied read, not a
network partition or loss of all telemetry simultaneously.

## Campaign owner: original cleanup processes also die

Two separately declared [120-second campaigns](../scenarios/campaign-owner-stop.json)
exercise `restart` and whole-control-group `SIGKILL`. These gates require a Linux
host administrator and systemd, and are executed on the GCP lab VM. They are not
claimed to run in the ordinary GitHub integration job.

The [service wrapper](../scripts/service_campaign.py) owns an exclusive durable
launch claim and an immutable post-stop receipt. An identity cannot be replayed,
including after an interrupted or torn launch. `ExecStopPost` performs accounting
and cleanup; an accounting failure must not prevent owned-resource cleanup. The
host, storage, Docker and systemd must survive. No host/power-loss claim is made.

The [privileged controller](../scripts/check_campaign_stop.py) declares the protocol
and source hashes in the existing root-owned receipt directory before preparation.
It suspends the original operator at 20 seconds, injects the conditional routing
fault at 25, requires an independent failed sample, and resumes the same operator
at 35. A real broker response must reach the interruption barrier by 65 seconds.
Within three seconds of that barrier, request unit restart or SIGKILL of the entire
unit control group. Schedule events may be at most three seconds late.

Before termination, record all resource UIDs and verify that the owner, operator,
observer and original janitor are four live processes in the same control group.
Require their original identities to be absent afterward. The supervisor's
post-stop receipt must belong to the original invocation, complete within 390
seconds of the stop request, and confirm no owned containers remain. Restart must
refuse a new invocation through the original launch claim, with no new workload.

The [scorer](../src/autonomy_lab/campaign_stop.py) requires initial healthy samples,
an independently observed fault before operator resume, exactly one audited repair,
and the unchanged `dispatching` operation with no acknowledgement or reconciliation.
The interrupted episode remains uncommitted and the campaign owner remains
unfinished. Preserve every committed sample hash and the entire twelve-slot
calendar; future slots remain unknown. Cleanup success is recorded separately from
campaign completion. Repeated scorecard and evaluation exports must be identical.

## Stop rules and evidence

Missed boundaries, unavailable required audit, unexpected mutations, absent process
identities, incorrect permissions, unknown measurements outside the declared gap,
replay, and incomplete cleanup fail the relevant gate. Retain the original failed
identity and its partial artifacts. No deadlines, scorer criteria, or source files
may change during execution. A changed implementation requires a new frozen source
and separately labeled run. All installed-release state remains separate from the
isolated study. No model credentials are required on the VM.

The evidence supports bounded lifecycle decisions only. These campaigns do not
prove production reliability, new diagnoses, model advantage, learned procedures,
human-work savings or return on investment. Procedure promotion and withdrawal
remain the next capability milestone after these foundation gates.
