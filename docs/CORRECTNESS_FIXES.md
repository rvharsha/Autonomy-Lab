# Correctness follow-up

> Historical record for the source named below. See [current findings and readiness](FINDINGS.md) for current deployment status and deferred work.

Main implementation commit: `a18c434b7eeb8debd9a412f56a972b0c2bbba721`; worker-startup correction: `bfbd7a0`, on [draft PR #1](https://github.com/rvharsha/Autonomy-Lab/pull/1). This follows the [adversarial self-review](ADVERSARIAL_REVIEW.md). The four findings have code fixes and focused regression coverage; the later [funded Fable follow-up](FUNDED_REVIEW.md) now records completed reviews and dispositions.

| Finding | Implemented behavior |
|---|---|
| F1: superseded verification | Completion credit requires citing the latest pre-claim verification, which must succeed. A later potentially dispatched proposal invalidates that check. Subsequent controller recovery cannot supply missing support for an earlier claim. |
| F2: unbounded execution | A shared HTTP transport enforces a total request deadline across headers/body and caps response bytes before parsing. Compressed responses are rejected before decompression. Each experiment trial runs in its own session under a controller-owned deadline. A timeout kills the worker and descendants, retains its partial trial record and journals, and counts the attempt as timed out. Launch errors and cancellation are recorded separately. |
| F3: checkpoint identity | Schema 2 binds checkpoints to run identity, release SHA-256, system instructions and external/internal declarations. Compatibility checks precede terminal return and execution. Legacy schema 1 and changed contracts are rejected through a separate error record; primary checkpoint bytes are preserved. Tightening budgets remains allowed. |
| F4: early configuration validation | Manifest and Gemini transport share bare-model-ID validation. Output budgets must fit the provider and total-token limits. Run-order seed and trial deadline validation happen before credentials, provisioning or paid calls. |

The supervisor compares the worker's current release manifest with the controller's declared release before infrastructure access. This detects drift at startup; it is not a read-only filesystem or an immutable packaged release. Within-trial cooperative agent checkpoint reloads remain distinct from full runtime suspend/resume.

## Validation

- **626 tests passed; Ruff and whitespace checks passed.** The added tests include real loopback servers that trickle headers/body, oversized responses, compressed-response refusal, and actual worker/descendant termination. An unrelated process remains alive. Authored record-shape tests are identified separately from real process/HTTP tests.
- The updated scorer reproduced all **28 original pilot scores** without changes. Original artifacts remain untouched.
- Copies of two actual completed schema 1 pilot checkpoints are rejected without changing original or copied bytes; there were no provider calls or tool dispatches.
- [GitHub run 35820406987](https://github.com/rvharsha/Autonomy-Lab/actions/runs/35820406987) passed tests/lint and **all 17 real Kubernetes acceptance checks** at `a18c434`. The acceptance run used 30-second recovery windows and removed its cluster. Its source remains explicit; it does not silently become evidence for later changes.
- Initial smoke `experiment-001ba50d` retained **4/4 infrastructure errors**, zero provider requests, and successful cluster deletion. It exposed a real `FileExistsError`: the supervisor prepared a directory that `run_trial` expected to create. The correction explicitly permits the prepared workspace while refusing existing trial evidence; new subprocess and preservation regressions cover it.
- Follow-up `experiment-cf86d746` recorded **4/4 live Gemini trials** at `bfbd7a0`, using three-second smoke windows and 32,000 tokens maximum per trial. Both routing variants and structured/lost-ack repaired the application but stopped on budget before a terminal claim. Basic/lost-ack completed successfully. Both lost-ack trials reconstructed schema 2 checkpoints once; all checkpoint run/release bindings matched. All 24 provider responses fit their reservations, totaling 106,331 tokens; cluster deletion completed. These are smoke outcomes, not a new comparative pilot or evidence that budget failures are solved.
- [GitHub run 35820688545](https://github.com/rvharsha/Autonomy-Lab/actions/runs/35820688545) passed tests but failed the final-recovery phase after the earlier application and broker checks passed. Its cluster was deleted. The original uploaded summary omitted verifier probe reasons and timing, so the cause cannot be established from that artifact alone. Commit `d65b2d1` adds compact verifier diagnostics to subsequent acceptance reports, with a regression excluding raw observation bodies. [Its CI run](https://github.com/rvharsha/Autonomy-Lab/actions/runs/35821144763) passed tests and all real acceptance checks; the earlier failure remains retained.
- Three declared local broker/recovery sequences in `recovery-diagnostic-bcefeb48` reproduced the failure once. The first window had one initial HTTP-503 probe followed by 26 successful probes; both independent control endpoints were healthy and the observed Service already targeted 8080. The second and third windows passed; cleanup deleted the cluster. This establishes a short client-path readiness delay after restoration. The precise internal network cause was not instrumented, and the original CI failure cannot be proved identical from its limited artifact.

The acceptance harness now declares a 30-second readiness allowance before its scripted/final recovery windows. It retains every readiness result, allows only client-path HTTP 503s to settle, and then requires the original complete clean verification window. Other failures, indeterminate measurements and readiness completed after the deadline fail. This changes the harness's startup criterion, not the verifier's verdict or any agent score; it does not discard failed probes. Current-source CI remains visible on the PR.

[Selected portable evidence](validation/correctness-followup.json) includes source hashes, original-pilot rescoring, checkpoint preservation, CI results, failed-run accounting and blocked review attempts. Private artifacts remain local.

## Fable review status

The earlier five component requests (`agent`, `scoring`, `verification`, `bounded_transport`, `experiments`) stopped at token preflight with HTTP 400: the Anthropic API reported insufficient credits. **Zero review generation requests were sent.** Those attempts remain recorded without a generation or approval. After funding, the [follow-up review round](FUNDED_REVIEW.md) completed 13 bounded reviews, addressed substantiated defects and retained rejected findings with their evidence. The credit blocker is resolved.

## Remaining limits

The supervisor requires a live controller and POSIX process groups. It does not provide a janitor after controller death, AX/Substrate restore, untrusted-code isolation or independent Kubernetes server auditing. HTTP calls require the worker's main thread and refuse an existing process alarm; future threaded/async embedding needs another explicitly bounded adapter. The new trial deadline is an execution bound including setup, not a claim about time to application recovery.

Cloud deployment, complete runtime lifecycle validation, a held-out comparison, and a justified improvement over the runbook remain separate gates. The original one-repetition pilot and its budget stops are not relabeled as outcomes of these changes.
