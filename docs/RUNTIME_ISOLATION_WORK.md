# Runtime, isolation, and evaluation work

Requested scope: AX recovery/integration, execution boundaries, and bounded-context evaluation. Merge and GCP deployment are outside this work.

## Executed gates

- AX lifecycle: three real DATA snapshot resume cycles and recovery from zero worker capacity passed repeatedly. Five unique boot IDs, preserved durable history, one ActorTemplate. See [AX runtime status](AX_RUNTIME_STATUS.md). The capacity-loss gate now waits for actual pod deletion and no active worker in Substrate's registry; an earlier attempt raced with draining and failed with an ambiguous restore outcome, which was not retried.
- Docker agent boundary: all 15 actual filesystem, network, privilege and credential probes passed on the final image. The decision process has a read-only root, no network, no capabilities, and only its checkpoint workspace mounted. It executes by immutable image ID.
- Controller death: actual SIGKILL after application provisioning triggered the final detached janitor; `controller-death-e078739f` reports deletion with no errors or remaining nodes. AX-specific controller-death validation awaits deployment approval below.
- Four actual crash boundaries: model-response loss stops indeterminate without retry; tool-dispatch, committed-checkpoint and terminal-response loss reconstruct a fresh Docker decision process and complete. Terminal recovery required a second restart after the scenario's interruption. Each completed repair has one correlated server-audit mutation, no duplicate proposal, and cleanup.
- Model-free acceptance exercised the three reserved scenario mechanics. The original lost-ack/dependency-change score used an incompatible zero-write escalation criterion; its pre-model correction requires one covered uncertain repair, reconciliation, current failed verification, no repeat and escalation. Both original and corrected assessments are retained.

[Selected runtime evidence](validation/runtime-gates.json) preserves successes and failed attempts. Private raw evidence remains in the cited artifact directories; no passing replacement is counted as a comparison trial.

## AX integration: approval pending

The isolated Gemini agent now starts in real AX with UID 10001, zero effective/permitted capabilities, no-new-privileges, denied sockets, denied root/code writes, and no provider or Kubernetes credentials. In the latest attempted integration it made two real model calls (6,111 known tokens), reached the lost-ack repair interruption, and then suspension failed: Substrate's trusted `atelet` cleanup could not unlink durable files owned by UID 10001. The run remains failed, and its cluster/registry were deleted.

Earlier retained attempts exposed legacy Docker builder incompatibility, YAML timestamp serialization, missing bootstrap capabilities, and root/durable directories at mode 0700. Actual before/after-UID diagnostics confirmed the filesystem issue. The fixes preserve nonroot agent execution and public workspace ownership.

The proposed [durable cleanup patch](../infra/ax/durable-cleanup.patch) grants DAC_OVERRIDE only to the trusted `atelet` service in the disposable local kind cluster, so it can remove snapshot files owned by the agent. It adds no guest capability or host mount. Automatic approval review rejected deploying this change because it broadens atelet's filesystem privileges and requires explicit user approval. The patch has been prepared and reproduced from clean pinned source; it has **not been deployed or validated**. Full live AX reconstruction and the AX controller-death gate therefore remain open.

## Evaluation

The [44-trial comparison contract](CONTEXT_EXPERIMENT.md) was committed before comparison trials. The source is being frozen for one run of baseline (8), bounded-context treatment (8), existing regressions (10), and held-out scenarios (18). Fixed budgets, all planned denominators, no adaptive retries or passing replacements. Completed integration probes are separate evidence.

Twenty additional direct Fable component reviews completed so far; findings and checked dispositions are in [the review record](RUNTIME_REVIEW.md). Final local checks passed 675 tests and lint. These authored tests are separate from actual Docker/Kubernetes/AX evidence.

## Limits

This is a patched local AX variant on macOS ARM64. Host, controller and Docker daemon remain trusted. Agent-denied access to host-owned evidence is not retention against a hostile host administrator. Independent auditing covers named Kubernetes identities and the trial namespace; comprehensive unsafe execution remains unassessed. Small held-out samples cannot establish production reliability.
