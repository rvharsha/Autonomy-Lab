# Validation record

The latest execution-boundary work is tracked in [the runtime work record](RUNTIME_ISOLATION_WORK.md),
with [selected real runtime evidence](validation/runtime-gates.json) and
[CI results for the frozen comparison release](validation/runtime-ci.json).
The entries below preserve earlier releases and must not be reassigned to later
source or described as AX integration evidence.

## Real-system acceptance

Run `demo-cc5ea868` passed **8 application/verifier checks and 9 broker checks** on a fresh local kind cluster. Recovery checks used 30-second sampled windows. The cluster was removed after the run. The portable, credential-free result summary is [acceptance-cc5ea868.json](validation/acceptance-cc5ea868.json).

Application/verifier checks: healthy operation, observed client-path routing failure, ineffective no-op repair, scripted recovery, incorrect HTTP-200 totals, changed protected data, verifier outage, and final recovery.

Broker checks: wrong target, stale proposal, duplicate acknowledgement without redispatch, operation-ID/content binding, a real applied mutation whose response is lost, journal reopening/reconciliation without redispatch, a concurrent mutation between read and write, and actual process `SIGKILL` after durable intent and after a real mutation.

These results use real HTTP traffic, PostgreSQL reads/writes by the scenario controller, Kubernetes mutations, and separate broker/verifier identities. API dispatch logs are instrumentation at the client; they are not independent API-server audit records.

After the initial Fable fixes to broker reservations, acknowledgement handling, and crash-worker monitoring, `demo-61f9c892` again passed all 8 application/verifier checks and 9 broker checks with 30-second recovery windows. Its cluster was removed. The [result summary](validation/acceptance-61f9c892.json) retains the actual SIGKILL outcomes and original-result hash. Further changes require their own validation; this result is not silently reassigned to a later release.

At implementation commit `9004ed5`, `demo-43a4b5e6` passed the same 17 checks, including the observable routing-failure barrier and actual SIGKILL recovery. Recovery windows were 30 seconds, and cleanup removed the cluster. Its [portable summary](validation/acceptance-43a4b5e6.json) binds the result to that commit and the original artifact hash. The deterministic suite at that commit passed 543 tests; Ruff and whitespace checks passed.

## Development failures retained

- `demo-61c6b4e9`: kind could not import Docker Desktop's multi-platform PostgreSQL archive. Kubernetes now pulls the pinned PostgreSQL digest directly.
- `demo-c858d065`: a real API rejection was misclassified by parsing kubectl's human-readable error. Mutation transport now reads structured HTTP status codes.
- `demo-34377798`: its checks passed, but later review showed that configuration failure could coexist with a working client path through an existing keep-alive connection. This run is superseded for routing-fault validation. Quote now uses fresh upstream connections, and acceptance requires an observed client-path failure.
- `experiment-6e4564bb`: initial Gemini development smoke runs used the earlier setup without a required broken-client-path barrier, so they are not valid comparative evidence. They did reveal a budget-enforcement defect: the next request's input context could exceed remaining tokens. The implementation now counts input tokens before generation and reserves them with the bounded output allowance.

Raw local records remain in the ignored `artifacts/` directory. They are not committed because they include local kubeconfigs. No failed run has been rewritten as a successful run.

## Live Gemini routing smoke

Run `experiment-ea63fad3` recorded both planned trials using Gemini 3.8 Flash, the corrected fault barrier, and the then-current input-token preflight. Its declared smoke verification windows were three seconds, shorter than the acceptance and pilot windows. The cluster was removed. The [portable result](validation/routing-smoke-ea63fad3.json) includes configuration, source hashes, accounting, and scores. Later inspection found that the preflight omitted preserved thinking tokens, so this run does not validate a strict budget upper bound.

| Variant | Agent result | Environment recovered | Task completed | Total model tokens |
|---|---|---|---|---|
| Basic | Completed | Yes | Yes | 17,522 |
| Structured | Budget exhausted | Yes | No | 26,662 |

The structured agent repaired the environment but could not afford its next request under the shared 32,000-token limit, so it never produced a terminal claim. This is an incomplete task, not a successful agent outcome. One trial per variant cannot establish a reliable difference between the designs.

## Stopped development pilot

`experiment-0db726fd` was stopped deliberately after seven completed trial records and during the eighth trial's final verification. Twenty trials had not started. Inspection showed that each billed prompt included prior thinking tokens absent from the corresponding `countTokens` response. No recorded model run exceeded 32,000 tokens, but its next-call reservation could underestimate usage. The cluster was removed.

The [annotated portable summary](validation/stopped-pilot-0db726fd.json) preserves the original accounting alongside its correction: the old interruption handler saved trial-008 as `running` and incorrectly included it among unrun trials. Original files remain unchanged. Future runs explicitly persist interrupted attempts and retain per-status accounting. This partial run is development evidence, not a completed pilot comparison.

## Completed development pilot

`experiment-06ca7c8b` executed all 28 declared trials at commit `9004ed5`, with no unrun trials and successful cluster cleanup. It used seven scenarios, four variants, one repetition, and 30-second verification windows. The [report](PILOT_RESULTS.md) and [portable evidence](validation/pilot-06ca7c8b.json) retain the complete accounting and original source/artifact hashes.

Observed task successes were runbook 6/7, basic 5/7, and structured 2/7. Seven model trials exhausted their budget before a terminal claim; the runbook escalated in the concurrent-change case without meeting its verification criterion. All 78 provider responses fit their input and total-request reservations, and every model trial stayed below 32,000 tokens. Estimated standard paid-tier Gemini token cost was approximately $0.343; this excludes reviews and infrastructure and is not an observed bill.

This complete matrix is development evidence from one repetition. It does not replace repeatability, held-out cases, runtime isolation, or independent execution auditing. Later code fixes retain separate validation rather than inheriting this pilot's execution evidence.

## Post-pilot review fixes

The final agent fixes preserve compatible terminal checkpoints before any resume counter/save and require absent or strict-zero tool-use prompt metadata before deriving missing thinking usage. Existing model/variant compatibility checks remain enforced, but rejection writes a separate error record instead of changing the checkpoint. Load/prepare failures from malformed required resume fields also preserve the original, including when persisting the error sidecar fails. The full deterministic suite passed **576 tests**, and Ruff passed.

Copies of completed basic and structured checkpoints from this pilot were tested with an invalid interruption-tool name, model mismatch, variant mismatch, and a missing resume counter. All eight checks left original and copied bytes/mtime unchanged and made zero token-count, generation, tool-declaration, or tool-dispatch calls. Valid completed states returned unchanged; configuration and shape errors were blocked with separate error records. The [selected regression evidence](validation/terminal-checkpoint-regression.json) records checkpoint and final code hashes without provider content. All 78 original pilot responses omitted `toolUsePromptTokenCount`, so none exercised the newly rejected metadata case. These focused checks do not constitute another live pilot.

The GitHub workflow's public upstream pins were verified. The setup-uv pin was corrected from the v6 annotated tag object to its underlying commit. The repository is now connected and [PR #1](https://github.com/rvharsha/Autonomy-Lab/pull/1) runs tests, lint, and real Kubernetes acceptance. The [correctness follow-up](CORRECTNESS_FIXES.md) records the newer code, regressions, CI evidence and review status separately from the original pilot.

## Completion experiment

The [completion-discipline experiment](COMPLETION_EXPERIMENT.md) adds a declared eight-trial baseline, matching eight-trial prompt intervention and ten development regressions at source `ff9bc5f`. Supported completion rose from 3/8 to 6/8; both structured lost-ack trials still stopped on budget. All ten regressions passed. All 26 trials were retained, all three clusters were deleted, and 120 actual provider responses used 584,630 tokens within their reservations. Its [portable evidence](validation/completion-discipline.json) records the source/usage/score bindings. The 626-test suite and lint passed for that source; Fable review was blocked by credit at that time and subsequently completed in the funded follow-up.

## Funded review follow-up

The [funded Fable round](FUNDED_REVIEW.md) completed 13 source reviews and checked every reported finding. Minimal fixes tighten durable-operation scoring, HTTP header/deadline handling, journal/report persistence and SQLite cleanup. **644 tests and Ruff passed** locally. Offline rescoring of all 54 retained pilot/comparison/regression trials changed no score metrics and left original artifacts untouched. Final-source CI is recorded on the PR.

## Evidence still required

The separate [runtime spike](AX_RUNTIME_STATUS.md) passed one real Substrate counter suspend/resume cycle. AX's three recorded attempts failed the declared three-cycle reconstruction gate; the experimental cold-boot variant completed one cycle before a worker-availability failure. These results do not validate the application's agents under AX.

Broader repeatability, fresh held-out cases, independent execution auditing, reliable AX lifecycle recovery and external broker integration still need their own passing reports. A passing infrastructure suite does not establish agent reliability or production safety.
