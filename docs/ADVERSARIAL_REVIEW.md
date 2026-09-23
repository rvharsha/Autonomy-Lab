# Adversarial self-review and remaining work

Reviewed implementation: `54b39dafd1de2baec2a1ede6b0d348cd13b5cbcc`, on `feat/verified-agent-lab`. This is a self-review of the current local prototype, not a new Fable review or an approval to merge. Findings below remain open; this review changes documentation and exports review evidence, not runtime code.

Subsequent implementation and validation are tracked in [CORRECTNESS_FIXES.md](CORRECTNESS_FIXES.md). The findings and priorities below preserve the original review rather than silently rewriting its conclusions.

**Assessment:** the repository contains a working local application, controlled repair path, verifier, and development experiment harness. It can support a draft implementation PR. It has not passed the runtime, isolation, attribution, and comparative-evaluation gates needed for dependable autonomous cloud operation. Resolve the concrete correctness findings before freezing the next comparison.

## Reproduced findings

Priority is relative to this project's purpose: P1 affects evaluation correctness or bounded execution; P2 is a narrower correctness gap that should be fixed before expanding use. These are not claims of a remote exploit in the current trusted local setup.

### F1 — P1: A newer failed verification does not invalidate an older successful citation

Location: [scoring.py, line 392](../src/autonomy_lab/scoring.py#L392), with completion classification at line 400 and task success at line 413.

`cited_verification` accepts any cited successful verification before the terminal claim. It does not check whether later evidence available to the agent contradicts that success. If the controller's final verification subsequently succeeds, the scorer can award task success to an unsupported claim.

Reproduction: copy the real successful basic-agent trace from `experiment-06ca7c8b/trial-002`; insert an explicitly authored failed verification after its successful verification and before `finish`; leave its old citation and successful final controller verification intact. The current scorer returns:

```json
{"task_success": true, "false_completion": false, "unsupported_completion": false}
```

This counterfactual is a scoring test input, not an observed model trajectory. It models a claim made after a known regression, followed by recovery before the controller's final check. Later recovery cannot retroactively ground the earlier claim.

Required change: define verification freshness at the claim boundary. At minimum, a newer failed or indeterminate verification must invalidate an earlier successful citation until a subsequent successful verification establishes recovery. Consider intervening mutations under the same explicit rule. Preserve the distinction between environment recovery and support for the agent's claim.

Acceptance: test success → failure → claim, success → indeterminate → claim, failure → success → claim, and recovery only after the claim. The first two cannot receive successful grounded-completion credit; the third may. Audit historical records without overwriting original scores.

### F2 — P1: HTTP inactivity timeouts do not bound request or trial duration

Location: [verifier.py, line 243](../src/autonomy_lab/verifier.py#L243), blocking collection at line 195, and [experiments.py, line 401](../src/autonomy_lab/experiments.py#L401). Similar synchronous HTTP patterns occur in the model and Kubernetes transports.

The verifier uses a synchronous `client.get()` and reads the entire body. Its HTTP timeout limits inactivity, not total request duration. The verification window is checked only after the collector returns. The experiment runner supplies no independent wall-clock trial deadline, so a continuously trickling response can prevent trial completion and delay the `finally` cleanup indefinitely. This is distinct from the intentionally sampled nature of the verification window.

Reproduction used a real, finite loopback HTTP server: one byte every 0.04 seconds with a 0.1-second client timeout. The verifier returned a response after **0.86282 seconds**, rather than timing out. A separate response retained a **262,144-character** JSON string in full. No cluster or provider was involved. The finite probe demonstrates the missing total-duration and body-size bounds; it did not attempt an indefinite hang or exhaust memory.

Required change: declare and enforce total request and trial deadlines, bound response bytes before buffering/parsing, and preserve partial evidence on cancellation. A timed-out mutation or billed model request must remain uncertain, with no automatic retry. Cleanup needs a supervisor capable of acting when the worker is blocked or killed.

Acceptance: real slow-stream, oversized-body, and blocked-worker tests terminate within declared bounds, retain the attempted trial, and release owned resources. Test timeout after mutation dispatch separately from timeout before dispatch.

### F3 — P2: Checkpoints are not bound to the run or release being resumed

Location: [agent.py, line 171](../src/autonomy_lab/agent.py#L171) and compatibility checks at line 558.

State persists model and variant, but no explicit run identity or release identity. Resume checks only model and variant compatibility. Reusing a checkpoint path with a different toolbox run silently returns the previous terminal result if that checkpoint is complete. Nonterminal state also lacks a release/prompt/tool-contract compatibility check.

Reproduction: copy the unchanged real completed checkpoint from `trial-002`; call `run_agent` with the same model/variant and a toolbox whose `run_id` is different. The function returns `completed` and the old terminal claim, without invoking any model or tool method. Original and copied checkpoint bytes remain unchanged.

The current experiment harness creates fresh trial directories, so this is not evidence of cross-run contamination in the recorded pilot. It becomes especially relevant when implementing checkpoint selection and AX workspace restoration. The scorer's separate run-consistency checks do not substitute for rejecting incompatible execution state at resume.

Required change: persist and validate run identity and an immutable execution-contract/release identifier, including prompts, declarations, policy and relevant runtime configuration. Reject incompatible checkpoints before returning a terminal result or continuing execution, preserving the original evidence. Any legacy migration must be explicit.

Acceptance: wrong-run, wrong-release, changed-tool, and changed-prompt resumes fail without provider calls, mutations, or checkpoint replacement. Compatible resumes retain original counters and operation IDs.

### F4 — P2: Invalid model configuration passes the pre-provisioning validator

Location: [experiments.py, line 57](../src/autonomy_lab/experiments.py#L57), with the transport constructor at line 263.

The manifest validator accepts any nonempty model string. The transport later requires a bare `gemini-...` identifier. An invalid value can therefore survive validation and reach cluster provisioning and trial setup before failing during actor setup.

Reproduction, entirely offline: replace the pilot manifest's model with `not-a-gemini-model`. `validate_config` accepts it; `GeminiClient` rejects it in its constructor. The constructor probe uses a deliberately non-secret placeholder and sends no request.

Required change: share model-ID validation between the manifest and transport, and validate run-order inputs and compatible budget ranges before credentials, artifact allocation, provisioning, or paid requests. Local format validation should not be described as proof of provider availability.

Acceptance: invalid IDs fail at the manifest boundary with zero provisioning/model calls; valid manifests remain accepted. Add this case to the existing pre-provisioning regression tests.

## Evidence and impact

- Re-ran `make test lint`: **576 tests passed; Ruff passed**. Two existing upstream deprecation warnings remain. The existing suite does not exercise the reproduced cases.
- Recomputed scores from all **28 original pilot trials** with the current scorer: **zero mismatches**. None of the original terminal claims exhibits the newer-failed-verification/older-success-citation pattern in F1. The pilot outcomes remain unchanged.
- Review probes made **zero provider requests and zero cluster mutations**. The HTTP checks used an actual loopback server; the scoring contradiction was explicitly authored; the checkpoint probe copied actual retained evidence. No new benchmark outcome is claimed.
- The prior **17 real Kubernetes acceptance checks** remain evidence for their recorded source, `9004ed5`. They were not rerun during this review. The later checkpoint corrections have separate recorded regression evidence.
- Reviewed the broker's conditional update, identity/version checks, operation ownership, reservation accounting and no-blind-retry paths. This pass did not substantiate another defect there. That is a scoped review result, not proof of universal execution safety.

[Portable probe results](validation/adversarial-review.json) record measured outputs and source hashes without raw model histories, credentials or private application artifacts. The local reproduction driver is `.state/audits/adversarial_review.py`; it depends on retained local pilot artifacts and is not a clean-clone regression suite. F1–F4 need permanent regression coverage when fixed.

## Unpassed architecture and experiment gates

These are incomplete requirements or evidence limits, separate from the reproduced defects above.

| Gate | Current evidence and gap | Evidence required to close it |
|---|---|---|
| Runtime recovery | The basic/structured pilot pauses cooperatively, reloads agent/tool files, and calls `run_agent` again in the same Python process, retaining the broker and client objects. Broker SIGKILL acceptance exists; equivalent live-agent process/container-death coverage does not. AX/Substrate preparation compiled and rendered, but no runtime suspend/resume ran. | Fresh-process/container restoration and actual pinned-runtime suspend/resume. Kill at model-response, tool-dispatch, checkpoint-save and terminal-report boundaries; preserve uncertainty, usage and journal ownership. |
| Isolation and least privilege | The fixed model tools have no arbitrary shell/URL. Broker and verifier have scoped Kubernetes identities. However, agent/controller/broker/verifier orchestration shares trusted local Python, and `ObservationTools` receives the controller's admin Kubernetes object at `experiments.py:231`. No agent isolation or enforced network policy is demonstrated. | Separate processes/identities; a read-only observation identity; deny access to controller credentials, scenario labels, fixtures and broker storage. Attempt forbidden file reads and network calls from the actual agent runtime and record enforcement. |
| Independent execution attribution | `api-mutations.jsonl` is written by the requesting client, not the API server. The scorer correctly leaves `unsafe_executions` unassessed. | Independent server audit with distinct actor identities, correlated against operation IDs and protected-state checks. Exercise acknowledgement loss and controller interference without relying solely on the actor's own logs. |
| Immutable execution | `release_manifest` hashes source/configuration at the start, but execution continues from a mutable working tree; fixtures and build inputs are subsequently read from disk. The recorded pilot was deliberately frozen, but the runner does not enforce that discipline. | Execute a packaged immutable release or isolated read-only snapshot, pin its images, and bind checkpoints/artifacts to it. Demonstrate that later working-tree changes cannot alter a running release. |
| Scenario strength | Seven families have one development instance each. Concurrent change currently means an external repair. Adversarial evidence uses a blunt instruction in a visibly lab-generated event. | Add changed dependencies that make an old repair inappropriate, stronger operationally plausible instruction attacks, and distinct cases reserved before tuning. Keep injection provenance private while retaining honest controller records. |
| Comparative conclusions | Runbook **6/7**, basic **5/7**, structured **2/7**. Seven model trials stopped on token budgets. One run per case gives no reliable superiority or failure-rate estimate. Structured also changes a prompt/internal tool while retaining full history. | Explain failures; declare one intervention; run matched regression cases and fresh held-out cases. Freeze budget, deadlines, run order, instances, exclusions and primary measures before execution. An ablation is needed for claims specifically about state representation. |
| Cloud operation | The runnable application environment is local kind. There is no validated GCP deployment, cloud IAM/secret boundary, remote durable artifact path, or controller-independent resource janitor. | A scoped cloud deployment with tested identity/network restrictions, durable operation/evidence storage, explicit spending/resource limits and cleanup after controller death. Pass the same acceptance gates in that environment. |

The present results do **not** support choosing the structured agent over the runbook. More orchestration or additional agents would introduce another treatment; neither is a demonstrated remedy for the current budget failures.

## What remains, in execution order

1. **Correctness patch:** fix F1–F4 with focused regressions and bounded real HTTP tests. Review the final changed source with Fable, record finding dispositions and exact hashes, then run the appropriate acceptance checks. Fable has not reviewed the final prior checkpoint corrections or this new review's eventual fixes.
2. **Repository and PR gates:** create/connect the intended GitHub repository, push the reviewable branch, and open the PR. Run tests/lint and the actual Kubernetes acceptance job in GitHub; require their results and reviewer approval before merging execution changes. The current acceptance workflow runs only on `workflow_dispatch`; branch protection is not configured. Fable is a local review workflow, not an installed automatic PR reviewer. Choose repository visibility/license deliberately and publish only allowlisted evidence, never raw artifacts or kubeconfigs.
3. **Finish the runtime boundary:** close isolation, checkpoint identity, fresh-process crash recovery, independent audit and immutable-release gates. Execute the prepared AX/Substrate spike or explicitly select and validate another runtime. Preparation scripts currently under ignored `.state/ax-spike/` must be made reproducible from the repository before claiming that a new checkout can run that spike.
4. **One targeted improvement:** inspect the seven budget stops and the runbook's concurrent-change miss; choose and document a specific change. Preserve the original runs and their budgets. Do not relabel the original comparison after tuning. Test the changed behavior on matched cases before spending on a larger matrix.
5. **A defensible comparison:** reserve fresh cases, prerecord the experiment contract, and run enough matched conditions to answer the chosen question with explicit uncertainty. The plan's 140-trial matrix is a planning suggestion, not an automatically justified sample size. M6 still needs an evidence-backed intervention or a reported null result.
6. **GCP deployment:** deploy only once the execution boundary is concrete; then validate cloud-specific persistence, permissions, isolation, deadlines, auditing and cleanup. Cloud hosting alone does not close the earlier gates.

Milestone assessment: M1 has substantial real-system evidence; M2's local broker core has substantial evidence. M0 remains incomplete for runtime/isolation; M3 remains incomplete for attribution and scenario breadth; M4 remains incomplete for runtime recovery and immutable releases. A 28-trial development slice of M5 is complete; a held-out comparison and M6 are not.
