# AX local runtime spike status

## Recovery gate passed, 2026-09-23 14:38 UTC

The new source variant passed **3/3 real AX cold-boot suspend/resume cycles**.
It then passed a separate capacity-loss case: the worker pool was reduced to
zero, a single resume request encountered real ResourceExhausted responses,
and restoration to one worker allowed the controller to recover without a
second manual resume. Five distinct process boot IDs retained the original run
identity and all preceding durable records. Exactly one task ActorTemplate
remained. The cluster and registry were deleted.

Source inspection found lifecycle state in AX_TASK_YAML changed the template
hash on each reconciliation. `infra/ax/recovery.patch` excludes task status and
suspend state from that boot configuration, and retries only Substrate's explicit
pre-assignment capacity rejection for at most 60 seconds. The previous cold-boot
patch is retained. Go controller tests and the ARM build passed. This is a local
pinned variant, not an upstream release claim. [Selected evidence](validation/ax-recovery.json).

Agent/broker integration, crash-boundary testing, and clean-clone reproduction
are being validated separately. The historical failed attempts below remain
part of the record.

## Executed Substrate gate, 2026-09-23

The first bounded local execution **passed** against the pinned Substrate
revision. The dedicated cluster, ARM64 control plane, one counter worker,
and authenticated API all ran. One real gVisor suspend/resume cycle preserved
both counters: memory and durable file state advanced from `[1, 1]` to
`[2, 2]`. The actor identity remained the same. Its state changed from RUNNING
to SUSPENDED with no worker assignment and a nonempty external snapshot URI,
then returned to RUNNING with an assigned worker.

Execution `20260923T075602331711Z` completed its create/install/counter/check
phases in approximately 33/197/46/3 seconds, within declared deadlines of
600/1200/600/300 seconds. Before installation, the node was capped at 5 GiB
and five CPUs, and the registry at 256 MiB; Docker inspection confirmed the
limits. The dedicated cluster and registry were deleted afterward. Unrelated
containers were left running. Kubernetes discovery caches created in the
working directory were moved into private run evidence, and `.kube/` is now
excluded from Git.

[Selected lifecycle evidence](validation/substrate-lifecycle.json) records
the actual state transitions, counter values, hashes, phase timings, caps and
cleanup. Full private logs remain under `.state/ax-spike/logs/`. This validates
one sequential Substrate/gVisor lifecycle on this host. It does not establish
AX task reconstruction, cross-worker migration, abrupt-death recovery, or
agent/broker integration. The preparation scripts remain local and do not
constitute a portable installer for a fresh clone.

## AX task reconstruction attempts

The first AX attempt (`execution-20260923T081117877684Z`) deployed pinned
ARM64 controller/server binaries, Redis and a model-free task-runner image.
Its task remained Pending for the entire declared 120-second readiness
allowance. It completed **zero of three planned suspend/resume cycles**.
The failed probe and all logs were retained; its cluster and registry were
deleted.

The controller logged an initial Redis connection refusal and no task
reconciliation. Source inspection found that a new consumer group starts at
the current Redis stream tail (`XGroupCreateMkStream(..., "$")`). A task
published before subscription can therefore be skipped. This is a plausible
startup-order explanation, not a proven diagnosis of the original timeout:
cleanup completed before Redis stream/group metadata could be captured.

The second attempt (`execution-20260923T081734268433Z`) added a real
consumer-readiness gate before publishing any task. It required the
`ax-controllers` group to appear in
Redis's actual `XINFO GROUPS` response. It does not create a group or fabricate
an event. Initial AX Running/Ready, a live command process, a persisted startup
record, and suspension with an external snapshot all passed. The first resume
failed with `FailedPrecondition`: the GOLDEN data-resume policy required an
ActorTemplate golden snapshot that was not yet available. The golden snapshot
appeared about ten seconds later, but the controller had acknowledged the
failed event; Redis showed no pending events, and the task did not recover
within the 120-second readiness deadline. This attempt also completed **zero
of three planned cycles**, and its cluster and registry were deleted.

The [recorded compatibility patch](../infra/ax/README.md) changes one AX policy
from GOLDEN to COLD_BOOT for DATA snapshots. Pinned Substrate defines cold boot
as starting containers afresh from their OCI images with durable directories
populated from the snapshot. This matches the lab's intended reconstruction
contract. The original controller binary is retained, and the patched binary
has a separate hash and image. The controller's existing Go tests and its
Linux ARM64 build passed; the substrate adapter package has no Go test files.
This is a lab variant, not an upstream fix or an unmodified AX success.

The patched third attempt (`execution-20260923T082857818525Z`) completed
**one of three cycles, then failed the declared gate**. After its first resume,
the original run ID and startup record remained intact, exactly one new
startup with a different random boot ID appeared, the command was alive, and
AX reported Running/Ready. On the second resume, Substrate returned
`ResourceExhausted: no free workers available`. The task remained Failed with
Ready false until the 120-second deadline. Both observed suspensions retained
the same actor UID and had an external snapshot. The single worker was still
Running without restarts in the final Kubernetes observation; that does not
mean it was available for another actor. Competing golden-template work is a
plausible explanation, but no scheduler trace was captured before cleanup,
so worker ownership at the failed request is not established.

All three attempts retain their failures and cleanup records in the
[selected AX evidence](validation/ax-lifecycle.json). The last cluster and
registry were deleted. No readiness assertion, cycle count, or deadline was
relaxed, and no failed resume command was retried. The cold-boot patch remains
experimental; it is not integrated into the application runtime. The next
runtime work must account for worker capacity and recover safely from
transient scheduling failures, then repeat the full lifecycle gate before
testing external broker-journal reconciliation.

The three reconstruction cycles and their assertions remain
unchanged: preserve run identity and prior durable records, add exactly one
startup with a new random boot ID per resume, retain a live command process,
and observe AX Running/Ready after a Substrate SUSPENDED state with an
external snapshot. No model resource, bootstrap goal, or model credential is
provided. This local launcher gate does not fix general AX event recovery
when controllers start late or fail.

## Historical preparation record

**Everything below records earlier preparation, before the executions above.**
Its statements about unexecuted phases and unchanged source apply to those
historical checkpoints, not to the current runtime status.

The following records preparation on 2026-09-22 (America/Los_Angeles), performed on
2026-09-23 from 01:56 UTC. **Source checkout, tool verification, ARM compilation,
local manifest rendering, and public ARM image-manifest checks passed. No AX/Substrate deployment or suspend/resume
test has run.** This extends the source assessment in [AX_FEASIBILITY.md](AX_FEASIBILITY.md).

The preparation uses only `.state/ax-spike/`. The existing application cluster
was not accessed or changed. No Docker container, registry, Kubernetes cluster,
cloud resource, task image, or model call was created. User credentials were not
read. Deployment is deferred while the main application trials use this host;
the next phase needs explicit coordination before starting another cluster.

## Evidence collected

| Check | Actual result |
|---|---|
| AX source | Detached checkout at `d8ed0fe38bceb7842d3c47817d53d16ccdfcb601`; tracked files unchanged after compilation. |
| Substrate source | Detached checkout at `672533541dbfcd29084e4de2475267088bda3651`; tracked files unchanged after compilation. |
| Go | Official `go1.27.1.darwin-arm64.tar.gz`; checksum and size matched Go's release JSON before extraction. Local executable reports `go1.27.1 darwin/arm64`. |
| ko | Official `ko_0.19.1_Darwin_arm64.tar.gz`; checksum matched both release checksums and GitHub asset digest before extraction. Local executable reports `0.19.1`, matching Substrate's pinned ko module. |
| Native CLIs | `ax` and `kubectl-ate` compile for `darwin/arm64`; `ax version` and `kubectl-ate --help` exit successfully without a cluster connection. |
| AX ARM binaries | Task runner, controller, and server compile for `linux/arm64`. |
| Substrate ARM binaries | gVisor worker (`ateom-gvisor`) and deterministic counter compile for `linux/arm64`. |
| Substrate kind overlay | Project-local kubectl `v1.35.8` / Kustomize `v5.7.1` renders 49 resources successfully. No apply, API validation, image build, or image resolution was performed. |

The Linux outputs are actual statically linked ARM aarch64 ELF binaries. This is
compilation evidence only: the binaries and their container images have not run
under Substrate. The rendered overlay still contains `ko://` references and is
not the installer's complete assembled deployment.

Verified download hashes:

| Archive | SHA-256 |
|---|---|
| Go 1.27.1 darwin/arm64 | `ee215d57e0ec269c60cc9ceca68e6bda321ba9ee5afe24f4b0988703c2d87d12` |
| ko 0.19.1 darwin/arm64 | `a1338c4140c8c94e789733e21b161a3de177b467cd3c388b634fe1a869574509` |

Official inputs: [Go release JSON](https://go.dev/dl/?mode=json&include=all),
[ko release](https://github.com/ko-build/ko/releases/tag/v0.19.1).
TLS verification remained enabled. The system `curl` client handled public
downloads after the Python client lacked a usable certificate trust path.

## Installer review and next deployment boundary

The three pinned scripts were read before any installation action:
`hack/create-kind-cluster.sh`, `hack/install-ate-kind.sh`, and
`hack/install-ate.sh`. Their downloaded copies are in `source-review/`; neither
cluster creation nor installer execution was attempted.

The cluster script deletes the cluster named by `KIND_CLUSTER_NAME`, whose
default is `kind`. Its registry container name is hardcoded to `kind-registry`;
if an existing container has a different port mapping, the script removes it.
Changing only the cluster name therefore does not fully isolate this spike.
It also uses the shared Docker `kind` network and can try to recreate that
network for a non-IPv4 configuration. A later run must use the spike's dedicated
cluster/registry names and kubeconfig, and avoid that shared-network mutation.
Preserve any minimal source customization as a recorded diff before execution.

The script enables `ClusterTrustBundle`, `ClusterTrustBundleProjection`, and
`PodCertificateRequest`, plus `certificates.k8s.io/v1beta1`. It probes Docker's
`/dev/kvm`, adjusts proxy sysctls inside its created node, and connects the local
registry to the kind network. Its `hack/kind.sh` wrapper resolves the pinned
kind `v0.33.0` tool through Go; that tool has not yet been built in this spike.

The kind installer chooses native Linux architecture, sets `NO_DEV_ENV=true`,
targets an explicit context, and uses local RustFS. Its core deployment creates
CRDs/RBAC, SandboxConfig, certificate infrastructure, PostgreSQL, API/controller,
node supervision, routing/egress, and telemetry. Run it with a clean, scoped
environment: the wrapper unsets several GCP variables but does not clear every
possible inherited external-service override.

Substrate's default image configuration includes `linux/arm64`, and its gVisor
SandboxConfig pins an ARM archive and checksum. AX's upstream task-runner build
and Dockerfile still hardcode `amd64`. The successful direct ARM compilation
removes a source-build uncertainty; an ARM container recipe preserving the
documented runner contract remains necessary. No image architecture claim has
been established by compilation alone; the follow-up registry checks below
validate the selected public image manifests, without executing them.

The upstream counter example requests three workers, each with 1 GiB memory,
in addition to the control plane. Account for that capacity before a concurrent
cluster is started. Its ActorTemplate requests full snapshots; the proposed
counter test must record process state and durable files separately.

## Reproducing and continuing

`build_tools.py` records exact compile commands, timestamps, exit codes, and
per-target logs. Builds use `-mod=readonly`, `-p=2`, `GOMAXPROCS=2`, `CGO_ENABLED=0`,
an explicit public module proxy/checksum service, and caches under the spike
directory. They receive a small explicit environment with no inherited provider
credentials. From the project root:

```sh
.venv/bin/python .state/ax-spike/build_tools.py
.venv/bin/python .state/ax-spike/build_tools.py --runtime
```

Evidence under `.state/ax-spike/logs/` includes `source-revisions.json`,
`source-cleanliness.json`, official release metadata, `go-verified.json`,
`ko-verified.json`, `tool-versions.json`, `build-records.json`,
`runtime-build-records.json`, `binary-checks.json`, `cli-smoke.json`,
`manifest-render.json`, and the raw `substrate-kind-render.yaml`.

The next unpassed gate is an isolated, authenticated Substrate runtime with
resolved ARM images, followed by the real counter suspend/resume test. After
that, deploy AX and test its `/workspace` reconstruction and external broker
operation lookup as specified in the feasibility plan. Existing lab process
restart results are not evidence for either runtime gate.

## Prepared second-phase launch (not executed)

Prepared at approximately 02:37 UTC on 2026-09-23. Only the spike directory and
this status file changed. No image pull/build, container/cluster creation,
installer invocation, lifecycle probe, or provider generation was performed.

The entry point is `.state/ax-spike/launch/run.sh`, with separate `create`,
`install`, `counter`, and `check` phases. These are prepared commands for the
coordinated next run, not evidence that their runtime behavior has passed:

```sh
bash .state/ax-spike/launch/run.sh create
bash .state/ax-spike/launch/run.sh install
bash .state/ax-spike/launch/run.sh counter
bash .state/ax-spike/launch/run.sh check
```

The launcher fixes the cluster to `autonomy-ax-spike`, context to
`kind-autonomy-ax-spike`, registry to `autonomy-ax-spike-registry` on loopback
port `5007`, and kubeconfig to `.state/ax-spike/runtime/kubeconfig`. It starts
the selected phase with `env -i`, explicit project-local Go caches, an empty
project-local Docker config, and the observed local Docker socket. It supplies
no provider, GCP, AWS, or external database credentials. It neither assigns nor
changes the user's `HOME`. Each phase records a timestamped launch log.

The pinned Substrate checkout now has three recorded local adaptations:

- Cluster creation refuses an existing named cluster, registry, or kubeconfig;
  it never deletes/replaces them. It uses an immutable ARM registry image,
  an explicit node image, IPv4, and an explicit kubeconfig. The shared-network
  deletion and IPv6 kubeconfig-rewrite paths are removed. The first gate uses
  gVisor only, so the KVM probe container is omitted. The remaining node
  proxy-ARP/NDP changes apply only to nodes belonging to the named spike cluster.
- The original counter WorkerPool uses one worker instead of three. Its image,
  1 GiB worker memory, counter code, durable volume, and full-snapshot policy
  remain unchanged. The API permits one replica, and the template reconciler
  suspends its golden actor after snapshot creation, allowing the single worker
  to serve the subsequent sequential counter actor. Actual scheduling remains
  a runtime gate.
- The kind atelet overlay rewrites actor-image references from localhost to
  `autonomy-ax-spike-registry:5000`. Upstream hardcodes `kind-registry:5000` here;
  changing only the cluster creation script would leave actor-image pulls
  pointing at the wrong registry even if Kubernetes pod-image pulls succeeded.

The exact changes and hashes are in `launch/upstream-adaptations.patch` and
`launch/adaptation-record.json`. `launch/prepare_adaptations.py` reproduces only
these local changes and refuses unexpected source changes. AX source is
unchanged. All launch shell files passed `bash -n`; the Python preparation/probe
files passed compilation and Ruff. No execution test of these launch phases
has been performed.

Read-only Docker checks found **11 CPUs, 7.65 GiB configured memory, Linux
aarch64, and Docker 27.5.1**. This is capacity, not a measurement of free RAM.
Other user containers were observed and left unchanged. Port 5007 had no
observed listening socket during preparation. Neither fact guarantees capacity
or port availability at the later launch; do not run this alongside the main
application trials. Full captured commands and measurements are in
`logs/docker-capacity.json`.

The prepared node image is kind v0.33.0's supported **Kubernetes 1.36.4** image,
pinned by digest. This keeps the existing kubectl 1.35.8 within one minor
version and matches the pinned Substrate release's documented feature-gate
generation. All **11 selected public prerequisite images**, including the
registry, kind node, pause image, PostgreSQL, ko base, and local control-plane
dependencies, have verified Linux ARM64 manifest entries. Ko application images
still need their real build/push phase. Two `docker manifest inspect` commands
failed digest verification; independent raw registry downloads matched the
exact pinned SHA-256 values and contained ARM64 entries. Original failures and
successful verification evidence are both preserved in
`logs/image-platform-checks.json`, `logs/image-platform-verified.json`, and the
raw manifest files. No digest was replaced to bypass a failed check. The
launcher blocks if a recorded public-image prerequisite remains unverified.

The smallest prepared lifecycle probe (`launch/counter_check.py`) creates one
fresh named actor from the upstream counter template, sends one POST, records
the running actor, suspends it, requires `ACTOR_STATE_SUSPENDED` and a nonempty
external snapshot URI, then sends exactly one more POST. Both the memory and
file counts must increase by exactly one and the actor must return to RUNNING.
There are no automatic POST retries. A random loopback port is used for the
owned router port-forward, and that process alone is stopped on exit. Raw
responses, actor states, command timestamps, and the outcome are retained in a
new actor-specific log directory. The actor remains available for inspection;
cluster/resource cleanup must be coordinated separately and scoped to this
spike. This single-worker check does not claim cross-worker migration, AX
reconstruction, or broker recovery.

No concrete ARM snapshot incompatibility was found during these source and
manifest checks. Whether the host actually supports Substrate's complete
gVisor snapshot/restore path remains untested. The next gate is to run the
prepared phases after the main trials release the host, then assess the actual
lifecycle evidence before adding AX.

## Launch audit and resource boundary

The follow-up audit inspected the prepared phases against the pinned source.
The registry correction above is included in the recorded patch with SHA-256
`c24b67f958f67fcc8419755608284a7c19a842096505dfee50953a76a30fc96c`.
The adapted atelet overlay has SHA-256
`a743015ed7092f734bb16b049cba6deef15286a94a3babb80d639b2dd78934a2`.
Re-running the adaptation generator leaves the recorded hashes unchanged.
The complete kind overlay renders 49 resources with the intended registry
argument and no `kind-registry` reference. The separate PostgreSQL overlay also
renders. Rendering uses upstream's `--load-restrictor=LoadRestrictionsNone`
because its Kustomizations reference parent directories. Shell syntax, Python
compilation, and Ruff passed again. Commands, render hashes, and results are in
`logs/launch-audit-validation.json`; no resources were applied.

No other hardcoded old registry name reaches the selected gVisor phases.
`install-ate-kind.sh` defaults to `localhost:5001`, but the launcher supplies
`KO_DOCKER_REPO=localhost:5007`. Remaining matches belong to unused micro-VM,
e2e, setup, and deletion paths or CLI help text. In particular, do not use
upstream `hack/delete-kind-cluster.sh`: its registry cleanup still targets
`kind-registry`.

The installation is materially larger than the one counter worker. The core
overlay includes two API replicas; controller, router, RustFS, Jaeger,
OpenTelemetry collector, Prometheus, and certificate-controller deployments;
the atelet DaemonSet; and a bucket-initialization Job. The installer additionally
deploys PostgreSQL and egress routing and creates cluster-scoped CRDs, RBAC,
SandboxConfig, certificates, and locally generated authentication secrets.
All are intended for the dedicated spike cluster. Most core containers have no
explicit memory limits, so there is no aggregate memory cap.

The known steady-state requests alone total **2,208 MiB and 610m CPU**:

| Workload | Memory request | Memory limit | CPU request |
|---|---:|---:|---:|
| PostgreSQL | 1 GiB | 2 GiB | 250m |
| PostgreSQL TLS reloader | 32 MiB | unset | 10m |
| Prometheus | 128 MiB | 512 MiB | 100m |
| One counter worker | 1 GiB | 1 GiB | 250m |

This excludes unrequested services, the Kubernetes control plane, image builds,
Docker overhead, and existing user containers. RustFS and PostgreSQL each
request a 1 GiB PVC; these requests are not proof of available disk or enforced
disk quotas. Preparation occupies approximately 593 MiB of tools, 1.6 GiB of
Go caches, and 172 MiB of source checkouts before any container-image builds.
Recheck available capacity after the pilot exits; do not stop unrelated
containers or prune shared Docker resources to make room.

One sequential, real counter suspend/resume cycle is a practical first gate
once the host is released. The CLI JSON field names, actor states, routing
header, counter response, full-snapshot policy, and synchronous suspend call
match pinned upstream code. The test requires independent memory and file
continuity, plus a completed external snapshot. It does not prove AX task
reconstruction, cross-worker restoration, or broker recovery. Those remain
later gates.

The prepared commands have individual CLI/HTTP/readiness timeouts, but neither
image building nor the whole installation has an overall deadline. HTTP
timeouts also apply per operation rather than to total elapsed response time.
Run the first attempt with an outer supervised time budget, stop at the first
real blocker, and preserve its logs. Do not describe the prepared launcher as
an already validated bounded runtime. No source or public-image evidence
currently rules out ARM gVisor snapshot/restore; only the real lifecycle can
establish that capability.

## Scoped cleanup, only after evidence collection

These commands are recorded for the later coordinated teardown and have not
been executed. Run from this project root. They target the spike's named kind
cluster and kubeconfig, then remove its named registry only if its ownership
label matches. They leave image caches, evidence, the shared `kind` network,
and unrelated containers/configuration alone; do not substitute upstream's
deletion script or a Docker prune command.

```sh
AX_SPIKE_DIR="$(pwd)/.state/ax-spike"
env -i PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  AX_SPIKE_DIR="${AX_SPIKE_DIR}" \
  DOCKER_HOST="unix:///Users/harsha/.docker/run/docker.sock" \
  DOCKER_CONFIG="${AX_SPIKE_DIR}/runtime/docker-config" \
  /bin/bash <<'SH'
set -euo pipefail
"${AX_SPIKE_DIR}/../../.tools/kind" delete cluster \
  --name autonomy-ax-spike --kubeconfig "${AX_SPIKE_DIR}/runtime/kubeconfig"
if docker container inspect autonomy-ax-spike-registry >/dev/null 2>&1; then
  owner=$(docker inspect --format '{{index .Config.Labels "created-by"}}' autonomy-ax-spike-registry)
  [[ "${owner}" == autonomy-lab-ax-spike ]] || {
    echo "Registry ownership mismatch; refusing removal" >&2
    exit 1
  }
  docker rm -f -v autonomy-ax-spike-registry
fi
rm -f -- "${AX_SPIKE_DIR}/runtime/kubeconfig"
SH
```

Removing the empty spike kubeconfig after successful teardown permits a later
fresh create; the prepared create phase intentionally refuses an existing
file. Registry removal also removes only that container's anonymous volume.
Retain the source adaptations and lifecycle logs when cleaning up.
