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

The [44-trial comparison](CONTEXT_RESULTS.md) completed on frozen source `9dcc8ef`: baseline 6/8, bounded-context treatment 6/8, existing regressions 8/10, and held-out scenarios 6/18 supported completions. Context compaction did not solve the structured lost-ack budget failures. All planned trials remain, with no adaptive retries or passing replacements. All 44 audits were assessed with no duplicate proposals, unmatched successful scoped mutations, protected-state damage or false completion claims. Every phase's cluster was deleted. Completed integration probes are separate evidence.

The provider twice reported output above its requested allowance, including one 272-token excess over the intended trial ceiling. The host retained the usage and stopped; [the accounting finding](PROVIDER_OUTPUT_LIMIT_FINDING.md) limits any strict billing-cap claim.

A [separate follow-up contract](BATCHED_TURN_EXPERIMENT.md), recorded in `7bfce90`, tests ordered incident recording and repair in one model response. That candidate was applied only after the original comparison and cleanup finished. Its next gate is eight live development trials; it preserves evidence, verification dependencies and original trial limits. The earlier held-out results do not validate this later candidate.

Twenty-one additional direct Fable component reviews completed so far; findings and checked dispositions are in [the review record](RUNTIME_REVIEW.md). The frozen comparison release passed 675 tests and all 17 real CI acceptance checks. The separate batching candidate passed 682 tests and lint. These authored tests are separate from actual Docker/Kubernetes/AX evidence.

## Limits

This is a patched local AX variant on macOS ARM64. Host, controller and Docker daemon remain trusted. Agent-denied access to host-owned evidence is not retention against a hostile host administrator. Independent auditing covers named Kubernetes identities and the trial namespace; comprehensive unsafe execution remains unassessed. Small held-out samples cannot establish production reliability.
