# AX local runtime spike status

Recorded 2026-09-22 (America/Los_Angeles), with preparation performed on
2026-09-23 from 01:56 UTC. **Source checkout, tool verification, ARM compilation,
and local manifest rendering passed. No AX/Substrate deployment or suspend/resume
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
been validated against registry manifests in this preparation.

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
