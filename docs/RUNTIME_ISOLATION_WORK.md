# Runtime, isolation, and evaluation work

Requested scope: close the AX recovery/integration, execution-boundary, and evaluation gaps. No merge or GCP deployment is part of this work.

## Gates (in progress)

- AX: stable execution templates, bounded retry of explicit capacity rejection, three real cold-boot cycles, real capacity-loss recovery, reproducible pinned bootstrap.
- Execution: isolated immutable agent runtime; read-only observation identity; separate broker/verifier processes and durable journal outside agent checkpoint; enforced file/network denials; independent Kubernetes audit; controller-independent local janitor.
- Recovery: actual fresh processes and abrupt exits at model, tool, checkpoint and terminal boundaries; reconcile uncertain writes without duplicate execution; connect the same agent protocol to AX.
- Evaluation: declare context intervention and fresh case contract before trials; preserve protocol/signatures/evidence/accounting; matched development cases, regressions, and held-out cases with explicit uncertainty and all planned trials accounted for.
- Review: adversarial self-review and additional direct Fable review of changed boundaries; appropriate local and real-cluster checks; publish selected evidence and update the open PR without merging.

## Current work

Source inspection found that AX embeds mutable task status and suspend state in AX_TASK_YAML, which is hashed into ActorTemplate names. The recovery patch excludes lifecycle state from that boot input and retries only Substrate's explicit ResourceExhausted rejection for at most 60 seconds. Pinned Substrate emits that rejection before worker assignment. Other RPC errors are not retried. A regression checks stable lifecycle configuration and sensitivity to actual command changes. Real lifecycle validation is in progress; these source findings are not a passing runtime result.
