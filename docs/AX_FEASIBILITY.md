# AX runtime feasibility

Assessment date: 2026-09-22 (America/Los_Angeles). **Historical source review.** The subsequent [executed runtime record](AX_RUNTIME_STATUS.md) now includes a passing local Substrate/gVisor counter suspend/resume cycle. AX task attempts have now run: the cold-boot variant completed one cycle but failed the declared three-cycle gate on worker availability. Reliable AX reconstruction and agent integration remain open. Statements below about unexecuted preparation describe the original assessment.

Local execution is a credible next spike. Agent Substrate publishes a kind deployment path, and its source explicitly accommodates macOS Docker environments and arm64 gVisor assets. A GCP deployment is not a prerequisite for that path. End-to-end AX compatibility on this Mac remains unverified, particularly the task image architecture and suspend/resume behavior. [Substrate quickstart](https://github.com/agent-substrate/substrate#quickstart-development), [pinned cluster creation script](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/hack/create-kind-cluster.sh), [pinned gVisor configuration](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/manifests/ate-install/sandboxconfig-gvisor.yaml)

## Revisions reviewed

| Component | Revision |
|---|---|
| AX | `d8ed0fe38bceb7842d3c47817d53d16ccdfcb601` |
| Agent Substrate | `672533541dbfcd29084e4de2475267088bda3651` |

The Substrate revision is the dependency recorded in the pinned AX `go.mod`, expanded through GitHub's public commit API. AX specifies Go **1.27.1**; Substrate specifies Go **1.27.0**. Use the AX requirement for the combined build. These pins identify the review inputs; they do not establish a successfully tested deployment combination. [AX dependencies](https://raw.githubusercontent.com/google/ax/d8ed0fe38bceb7842d3c47817d53d16ccdfcb601/go.mod), [Substrate dependencies](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/go.mod), [commit metadata](https://api.github.com/repos/agent-substrate/substrate/commits/672533541dbf)

## What is available here

The active development environment is an arm64 Mac. Docker is available, and the main implementation has provisioned a local kind environment. Project-local `kind` and `kubectl` executables exist under `.tools/`. Read-only checks for this assessment found neither `go` nor `ko` on `PATH`.

No AX task, Substrate actor, runtime snapshot, image build, or cloud resource was created for this assessment. The application's local cluster and broker crash/restart tests are separate evidence; they do not validate AX suspend/resume.

## Required local setup

| Requirement | Evidence and implication |
|---|---|
| Go toolchain and image builder | AX builds its CLI with Go and deploys control-plane images with `ko`. Install or provide pinned Go 1.27.1 and a compatible `ko` for the spike. |
| Dedicated Kubernetes configuration | Substrate enables `ClusterTrustBundle`, `ClusterTrustBundleProjection`, `PodCertificateRequest`, and the `certificates.k8s.io/v1beta1` API in its kind configuration. Ordinary application-cluster readiness does not establish these prerequisites. |
| Local image registry | Substrate's kind wrapper defaults to a registry at `localhost:5001` and builds for the host's Linux architecture. AX needs control-plane and task images the cluster can pull. |
| Substrate control plane and storage | The documented local installation includes its API/controller, node supervision, networking, certificate services, PostgreSQL, and RustFS snapshot storage. These are additional infrastructure beyond the lab application. |
| AX control plane | Deploy Redis, the AX controller, and AX server after Substrate is ready. The configured Substrate endpoint is `api.ate-system.svc.cluster.local:443`. |
| A compatible task runner | The AX build target and Dockerfile hardcode `linux/amd64`. This Mac needs an arm64-compatible task image, or an explicitly tested alternative execution environment. |

Sources: [AX build/deploy targets](https://raw.githubusercontent.com/google/ax/d8ed0fe38bceb7842d3c47817d53d16ccdfcb601/Makefile), [Substrate cluster configuration](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/hack/create-kind-cluster.sh), [Substrate kind wrapper](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/hack/install-ate-kind.sh), [local storage overlay](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/manifests/ate-install/kind/kustomization.yaml), [AX controller configuration](https://raw.githubusercontent.com/google/ax/d8ed0fe38bceb7842d3c47817d53d16ccdfcb601/deploy/ax-controller.yaml), [AX task Dockerfile](https://raw.githubusercontent.com/google/ax/d8ed0fe38bceb7842d3c47817d53d16ccdfcb601/Dockerfile.task-runner).

Substrate's cluster script probes `/dev/kvm` inside Docker. It explicitly permits the gVisor path when KVM is absent; microVM support is conditional on KVM. Its pinned gVisor configuration contains both amd64 and arm64 assets. This supports trying native arm64 gVisor first; it does not prove every image or runtime operation will work on this host. [Cluster script](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/hack/create-kind-cluster.sh), [gVisor architecture assets](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/manifests/ate-install/sandboxconfig-gvisor.yaml)

## Credentials and external services

- **Local infrastructure:** the kind wrapper clears GCP project/environment settings and uses a local registry and RustFS. No GCP project or application-default login is specified for this local path. Its storage overlay supplies local development credentials; those are not an AWS account requirement. [Kind wrapper](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/hack/install-ate-kind.sh), [storage overlay](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/manifests/ate-install/kind/kustomization.yaml)
- **Cluster authentication:** AX projects a Kubernetes service-account token with Substrate's API audience and a cluster trust bundle. Substrate's installer configures the cluster's JWT issuer. A reachable port alone is insufficient; the API must authenticate the controller and provide the required templates/worker capacity. [AX controller manifest](https://raw.githubusercontent.com/google/ax/d8ed0fe38bceb7842d3c47817d53d16ccdfcb601/deploy/ax-controller.yaml), [Substrate installer](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/hack/install-ate.sh)
- **Public downloads:** source, Go dependencies, container images, and gVisor assets require network access. The Substrate downloader tries anonymous access for public gVisor assets. An unauthenticated HEAD request to the pinned arm64 archive returned HTTP 200 during this review; the archive was not downloaded or executed. [Downloader](https://raw.githubusercontent.com/agent-substrate/substrate/672533541dbfcd29084e4de2475267088bda3651/cmd/atelet/sandbox_assets.go), [checked arm64 asset](https://storage.googleapis.com/gvisor/releases/nightly/2026-09-02/aarch64/gvisor.tar.zstd)
- **Model access:** AX's example references a Gemini credential secret and includes additional workspace integrations. The first lifecycle probe should use a deterministic command with no model/bootstrap goal. The expectation that this avoids model calls is a proposed test condition, not a completed finding. A later live agent evaluation needs its selected provider credentials and measured API usage. [AX example](https://raw.githubusercontent.com/google/ax/d8ed0fe38bceb7842d3c47817d53d16ccdfcb601/examples/task.yaml)

## Finite next spike

Allocate one bounded implementation session, with a stop after four hours or the first prerequisite that cannot be resolved locally. Preserve logs and report the failed gate rather than extending the experiment into an unplanned cloud deployment.

1. Provide the pinned toolchain, check out both revisions, and record versions. Render the deployment and resolve image architectures before installing it.
2. Use a separate disposable cluster named `autonomy-ax-spike`, with the upstream certificate feature gates and a local registry. Inspect the cluster script first: it deletes the cluster bearing the configured name. Keep the application cluster separate.
3. Install Substrate's local components and run its deterministic counter example. Require successful authenticated API access, worker readiness, request routing, and a suspend/resume cycle with preserved counter state. Capture actor IDs, timestamps, logs, and storage errors.
4. Build a minimal arm64 AX runner image, retaining the documented runner contract, and deploy AX against that Substrate instance. Avoid applying the model-bearing example unchanged.
5. Run one AX task that atomically persists a counter and a run identifier under `/workspace`. Perform three suspend/resume cycles. Require preserved files, a ready task after every resume, explicit startup markers, and no unexpected model calls. Record process identity separately from persistent state.
6. Interrupt that task once after it records an external broker operation ID. On resumption, require it to query the existing journal and handle an uncertain result without issuing another mutation. Keep the broker journal outside the agent workspace.
7. Export the artifacts and remove only the spike's resources. Decide from these gates whether to integrate AX, fix a specific local incompatibility, or retain the explicitly labeled local process runtime while evaluating another host.

The pinned runner contract says `/workspace` survives suspension while resumption starts a fresh container/process tree. It also requires HTTP health/readiness endpoints and graceful command termination. Accordingly, the spike must distinguish restored files from restored execution and must test application-level reconstruction of incident state. This is the contract to verify experimentally, not a claim that it already holds here. [AX runner contract](https://raw.githubusercontent.com/google/ax/d8ed0fe38bceb7842d3c47817d53d16ccdfcb601/docs/runner.md)

**Original blocking prerequisite, since cleared:** there was no deployed, authenticated, tested Substrate execution environment for AX in this lab. Pinned tools and the first real Substrate lifecycle have now passed; that disposable environment was cleaned up. ARM64 AX images now run, but the three-cycle task-reconstruction gate failed. The next runtime work is worker-capacity and transient-failure handling, followed by the full lifecycle gate and external broker-journal reconciliation. No GCP project is required for that declared local spike.
