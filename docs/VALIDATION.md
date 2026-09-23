# Validation record

## Real-system acceptance

Run `demo-cc5ea868` passed **8 application/verifier checks and 9 broker checks** on a fresh local kind cluster. Recovery checks used 30-second sampled windows. The cluster was removed after the run. The portable, credential-free result summary is [acceptance-cc5ea868.json](validation/acceptance-cc5ea868.json).

Application/verifier checks: healthy operation, observed client-path routing failure, ineffective no-op repair, scripted recovery, incorrect HTTP-200 totals, changed protected data, verifier outage, and final recovery.

Broker checks: wrong target, stale proposal, duplicate acknowledgement without redispatch, operation-ID/content binding, a real applied mutation whose response is lost, journal reopening/reconciliation without redispatch, a concurrent mutation between read and write, and actual process `SIGKILL` after durable intent and after a real mutation.

These results use real HTTP traffic, PostgreSQL reads/writes by the scenario controller, Kubernetes mutations, and separate broker/verifier identities. API dispatch logs are instrumentation at the client; they are not independent API-server audit records.

After the initial Fable fixes to broker reservations, acknowledgement handling, and crash-worker monitoring, `demo-61f9c892` again passed all 8 application/verifier checks and 9 broker checks with 30-second recovery windows. Its cluster was removed. The [result summary](validation/acceptance-61f9c892.json) retains the actual SIGKILL outcomes and original-result hash. Further changes require their own validation; this result is not silently reassigned to a later release.

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

## Evidence still required

The complete scenario matrix, repeatability across matched trials, fresh held-out cases, and the AX suspend/resume runtime need their own executed reports. A passing infrastructure suite does not establish agent reliability or production safety.
