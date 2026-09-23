# Runtime review and dispositions

Twenty-one additional **Claude Fable 5.1** component reviews completed through the direct Anthropic API. Three oversized scopes stopped at token preflight without generation; smaller scopes covered their components. One final context request returned `refusal` and remains incomplete; it was not continued or counted as approval. Reported usage implies **$7.65572** at the recorded rates, including that incomplete request, not an invoice.

The [selected ledger](validation/runtime-review-ledger.json) contains every attempt, final finding text, source hashes, usage, limits and status. Raw responses, private thinking and credentials are excluded. Reviews inspect source snapshots and do not execute tests. Findings were checked against the surrounding implementation and real evidence. Small subsequent remediation changes are validated locally; the individual snapshot hashes delimit Fable coverage.

| Component / finding | Disposition |
|---|---|
| Partial RPC frames and backpressure could outlive the local deadline | Added nonblocking pipe readers/writers with absolute deadlines; real pipe tests exercise partial input and blocked output. |
| Authority responses lacked correlation after a timeout | Added request IDs; deadline/correlation failures close the channel permanently. |
| Worker cleanup accepted empty identities; fixed leases could expire during long plans | Require a matching nonempty identity, tolerate already-exited processes, and size the lease from the declared plan. |
| AX result unlink and restart RPC budget | Tolerate an absent result file and persist the RPC budget across boots. The host independently gates requests and records provider usage; observed provider overruns prevent claiming a strict billing cap. |
| Context ledger drift and lost original task | Derive historical evidence from verified original model/function-response exchanges; retain the original task verbatim. |
| Context fails after a text-only model response | Not applicable to this runner: such a response already terminates as `model_returned_no_tool_call`, before another context request. |
| Tail evidence duplicated in compacted context | The ledger now covers only dropped exchanges; the last two complete signed exchanges appear once. |
| Terminal result could depend on a reconstructed toolbox | Persist the terminal in the agent checkpoint and honor both checkpoint and independent toolbox terminal before more model/tool calls. Real terminal SIGKILL recovery completed without another generation. |
| Redispatched reads consume another tool call | Retained: the budget measures dispatch attempts. Added durable attempt records and explicit recovery events so ambiguity and reconciliation remain visible. No invented tool result or acknowledgement. |
| AX stale mailbox requests and crash during a transition | Bind requests to the current boot; journal transition intent before side effects. An incomplete transition stops indeterminate instead of blindly repeating it. |
| AX filename and embedded request ID could differ | Validate both before dispatch or charging a request. |
| AX should use `namespace` rather than `atespace` | Rejected: `atespace` is the pinned AX API/CLI spelling, exercised by the real lifecycle gate. |
| Janitor timezone mismatch and transient watch errors | Normalize `ps` to UTC/C locale, retry transient metadata/process-read errors within the absolute lease, and publish deletion metadata atomically. |
| Failed worker reap/container cleanup could hide the outcome | Preserve timeout/exit information and record cleanup errors; attempt container removal even if reap times out. |
| Root-hosted workspace ownership and failed runtime status | Assign the workspace to the nonroot container UID when the host is root; failed containers record failure after teardown. |
| Audit truncation or missing acknowledged writes | Retain complete audit events, mark malformed input or missing acknowledged writes incomplete, and withhold the trial score. Duplicate correlated writes are also violations. |
| Generic remote KeyError resembles a journal miss | Only the explicit lookup-miss signal maps to `KeyError`; other worker faults stay remote errors. The broker already classifies post-dispatch exceptions as uncertain. A real child-process test checks the distinction. |
| Verifier restart could reuse result filenames | Authorities are not automatically restarted after failure, but verification filenames are now unique to preserve evidence on explicit reopening too. |
| Agent deadline and frozen release provenance | Reserve verification/export time inside the unchanged overall deadline; recalculate remaining time on restart. Forward and validate the declared release ID. Isolated comparisons execute copied source releases. |
| An unresolved repair at the tool limit looked like an ordinary budget stop | Return `indeterminate` with an explicit unreconciled-mutation reason. No budget exemption was added. Require a lookup tool whenever repair is declared. |
| Audit errors retained a successful score | Remove scores from interrupted/infrastructure-error outcomes; retain the underlying observations and verifier evidence. |
| An early crash could falsely trigger an after-observation scenario change | Only the actual requested checkpoint triggers that scenario mutation; abrupt crash recovery receives its own event. |
| AX host RPC loss was alleged to repeat a repair | The existing shared agent checkpoints the proposal before dispatch and recovers with `get_operation`; the independent broker journals intent before mutation. The claimed forgotten side effect is contradicted by those boundaries. No fake acknowledgement or unbounded replay was added. |
| AX exception handling could lose guest evidence | Exceptions inside `run_agent` already produce a recorded state. Escaping failures now distinguish startup/execution and export surviving guest checkpoints, boot records and boundary checks before teardown. |
| AX exported checkpoint was not atomic | Parse the guest checkpoint and atomically save it only after boot and boundary validation. A failed run remains failed, with separately retained guest evidence. |
| AX recovery charges a redispatched request again | Retained: this ceiling measures dispatch attempts, including reconstruction. Old boot requests are filtered. Charging only after response publication would leave failed dispatches unbounded; no automatic outer retry was added. |
| AX poll raced with the guest boot record | Wait for exactly the expected boot count before dispatching pending requests. Missing initial boot metadata or the previous boot during reconstruction is a bounded wait, not a hard failure or a stale request. |
| Scorer | Fable found no substantiated defect in its reviewed scoring snapshot. The added reconcile/escalate criterion has explicit regression coverage. |

Self-review and real execution additionally found Docker source permissions, concurrent build-tag replacement, legacy-builder compatibility, AX timestamp serialization, the second-interruption terminal recovery path, and Substrate overlay/durable roots at mode 0700. A later capacity-loss run exposed a stale worker selector and a race with the scheduler registry; the gate now waits for pod deletion and an empty active-worker registry. Real before/after-UID diagnostics established the directory-permission cause; bootstrap now permits traversal without world write access. Each failure remains in its original run directory; corrected attempts are separate. The initial publication commit is `7bdbfef`; final source, execution evidence and CI are reported separately.

The final AX variant grants CHOWN/SETUID/SETGID only to the trusted bootstrap in `autonomy-agents`, because the pinned default lacks those permissions. Both the decision process and controller mailbox helper enter UID 10001. The decision process then installs a syscall filter and checks effective/permitted capabilities, root-escalation denial and network denial before any model request. [Kernel seccomp semantics](https://docs.kernel.org/userspace-api/seccomp_filter.html) and the pinned ARM64 syscall ABI informed this boundary; it is not a claim of complete sandbox security. The scoped Go regression checks that other atespaces receive no capability adjustment.

## Separate batching candidate

The twenty-first review inspected the [follow-up development candidate](BATCHED_TURN_EXPERIMENT.md)
in a separate source copy while the original 44-trial release remained frozen.
It did not inspect held-out model traces. Two findings were assessed:

- A misspelled interruption hook could persist `blocked` over a resumable
  checkpoint. The candidate now validates the hook before saving any execution
  changes and writes only an error sidecar. Tests check byte/mtime preservation,
  zero model/tool requests, and successful continuation after correcting the
  hook, for both variants. Existing completed checkpoints remain untouched.
- An interrupted token-count preflight stops rather than automatically retrying.
  This remains the conservative recovery policy. The failed count is retained
  with its specific reason; it is not reported as a successful task or a lost
  generation. This is an availability limitation. Fable's suggested automatic
  retry would change the declared recovery contract and was not applied.

The additional hook fix followed the reviewed snapshot and passed local
regression tests; Fable coverage is limited to its recorded source hashes.
Candidate unit validation passed 682 tests. Its live performance is reported
separately from the original frozen comparison.
