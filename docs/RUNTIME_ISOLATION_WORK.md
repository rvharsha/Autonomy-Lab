# Runtime, isolation, and evaluation work

Current authorized scope: AX recovery/integration, execution boundaries, reliability validation, and PR review/merge/release. GCP deployment remains outside this work.

## Executed gates

- AX lifecycle: three real DATA snapshot resume cycles and recovery from zero worker capacity passed repeatedly. Five unique boot IDs, preserved durable history, one ActorTemplate. See [AX runtime status](AX_RUNTIME_STATUS.md). The capacity-loss gate now waits for actual pod deletion and no active worker in Substrate's registry; an earlier attempt raced with draining and failed with an ambiguous restore outcome, which was not retried.
- Docker agent boundary: all 15 actual filesystem, network, privilege and credential probes passed on the final image. The decision process has a read-only root, no network, no capabilities, and only its checkpoint workspace mounted. It executes by immutable image ID.
- Controller death: actual SIGKILL after application provisioning triggered the final detached janitor; `controller-death-e078739f` reports deletion with no errors or remaining nodes. AX-specific controller death also passed in `ax-controller-death-9df1d37d`: SIGKILL, no cleanup errors, no remaining owned containers, and runtime marker removed.
- Four actual crash boundaries: model-response loss stops indeterminate without retry; tool-dispatch, committed-checkpoint and terminal-response loss reconstruct a fresh Docker decision process and complete. Terminal recovery required a second restart after the scenario's interruption. Each completed repair has one correlated server-audit mutation, no duplicate proposal, and cleanup.
- Model-free acceptance exercised the three reserved scenario mechanics. The original lost-ack/dependency-change score used an incompatible zero-write escalation criterion; its pre-model correction requires one covered uncertain repair, reconciliation, current failed verification, no repeat and escalation. Both original and corrected assessments are retained.

[Selected runtime evidence](validation/runtime-gates.json) preserves successes and failed attempts. Private raw evidence remains in the cited artifact directories; no passing replacement is counted as a comparison trial.

## AX integration: passed

After explicit user authorization, the scoped [durable cleanup patch](../infra/ax/durable-cleanup.patch)
was deployed to trusted atelet in the disposable local kind cluster. The deployed
container drops ALL capabilities and adds DAC_OVERRIDE for snapshot cleanup.
The decision process remains UID 10001 with zero effective/permitted capabilities,
no-new-privileges, denied sockets, denied root/code writes, and no provider or
Kubernetes credentials; all 12 actual checks passed.

The first authorized attempt failed on its first generation, before any tool
call, with no retained response or usage. It remains a failed attempt with one
unknown provider outcome; audit and cleanup completed. Candidate `5ab2ebf` then
passed the full live gate: one uncertain repair, a real DATA suspend/resume, two
distinct nonroot process boot IDs, external operation lookup, full independent
30-second verification, and a supported resolved claim. All five generations
were retained (20,522 reported tokens), with one correlated write, no duplicate
proposal, no protected-state damage, and deletion of the cluster and registry.
The separate controller-death gate also passed. [Selected evidence](validation/ax-release.json).

The [AX history](AX_RUNTIME_STATUS.md) retains earlier startup, reconstruction,
filesystem and provider failures. These local gates do not claim arbitrary
mid-restore recovery, a portable fresh-host installer, or production reliability.

## Evaluation

The [44-trial comparison](CONTEXT_RESULTS.md) completed on frozen source `9dcc8ef`: baseline 6/8, bounded-context treatment 6/8, existing regressions 8/10, and held-out scenarios 6/18 supported completions. Context compaction did not solve the structured lost-ack budget failures. All planned trials remain, with no adaptive retries or passing replacements. All 44 audits were assessed with no duplicate proposals, unmatched successful scoped mutations, protected-state damage or false completion claims. Every phase's cluster was deleted. Completed integration probes are separate evidence.

The original comparison had two responses with reported output above their requested allowance, including one 272-token excess over the intended trial ceiling. The follow-up had another request-reservation overrun of 294 tokens, below its trial ceiling. The host retained usage and stopped; [the accounting finding](PROVIDER_OUTPUT_LIMIT_FINDING.md) limits any strict billing-cap claim.

A [separate follow-up](BATCHED_TURN_RESULTS.md), declared in `7bfce90` and executed on `ec7feb1`, records incident state and repair in one model response. It was applied only after the original comparison and cleanup finished. Both structured lost-ack retests completed under the unchanged 32,000-token target (28,017 and 27,818 tokens), with durable state before repair, one audited write each, reconciliation and full verification. Development completion was 7/8 and the conditional regressions 8/10. All 18 audits were assessed with no recorded scoped safety violations, and both clusters were deleted. One development generation returned HTTP 503 without usage; its billing remains unknown. Structured out-of-authority escalation still exhausted its budget, and a structured distraction trial stopped on the provider overrun. The earlier held-out results do not validate this later candidate.

Twenty-one direct Fable component reviews covered the earlier runtime work; findings and checked dispositions are in [the review record](RUNTIME_REVIEW.md). The frozen comparison release passed 675 tests and all 17 real CI acceptance checks. The separate batching candidate passed 682 tests and lint. These authored tests are separate from actual Docker/Kubernetes/AX evidence.

The subsequent reliability candidate and final remedial changes received three more completed direct Fable reviews, bringing this runtime/release sequence to 24. [Release review dispositions](RELEASE_REVIEW.md) distinguish accepted fixes from findings contradicted by the surrounding implementation. Candidate `5ab2ebf` passed 693 tests and lint. Its [38-trial results](RELIABILITY_RESULTS.md) are 12/12 development, 8/8 regressions and 16/18 reserved validation, with all scoped audits assessed and cleanup complete. Two basic combined lost-ack/dependency cases still exhausted their budgets. The [reconciliation follow-up](RECONCILIATION_RESULTS.md) completed 23/24 cases: 6/6 targets and 17/18 regressions. It failed its declared promotion gate, so the released executable source retains `5ab2ebf`; all follow-up outcomes remain recorded separately. A further direct Fable review brings this runtime/release sequence to 25 completed reviews. [Release source selection](validation/release-selection.json) verifies the final executable files against the selected candidate.

## Limits

This is a patched local AX variant on macOS ARM64. Host, controller and Docker daemon remain trusted. Agent-denied access to host-owned evidence is not retention against a hostile host administrator. Independent auditing covers named Kubernetes identities and the trial namespace; comprehensive unsafe execution remains unassessed. Small held-out samples cannot establish production reliability.
