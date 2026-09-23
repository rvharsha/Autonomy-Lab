# Follow-up development contract

Declared while the original 44-trial bounded-context comparison is still running,
before inspecting its held-out model outcomes. This candidate uses only the
original routing/lost-ack development traces. Those show that the structured
agent spends a separate generation recording incident state before submitting
a repair whose arguments are already known. Both structured lost-ack treatment
trials failed to finish within the intended budget.

After the original comparison finishes, test one minimal change: explicitly ask
the structured agent to emit `record_incident`, then `propose_repair`, in the
same response when existing observations support every repair argument. The
existing queue executes and checkpoints calls in order. A rejected incident
record must prevent a later repair in that response, including after restart.
This does not batch verification with a completion decision that needs its
unseen result, omit any public evidence, fabricate an acknowledgement, relax
the scorer, or increase a trial budget.

Keep Gemini 3.8 Flash, isolated Docker execution, the recent-exchanges policy,
12 turns, 32,000 intended total tokens, requested output limit 2,048, 900-second
trial deadline, and full 30-second verification windows. The observed provider
output-limit discrepancy remains a limitation, not a reason to raise limits.

Freeze source before eight new development trials: routing/lost_ack ×
basic/structured × two repetitions, seed 2026092306. Retain all eight results,
including infrastructure/provider failures, with no retries or replacements.
The candidate gate requires both structured lost-ack repetitions to complete
with incident state persisted before the repair, one independently audited
write, reconciliation, current verification, and cleanup. Stop immediately on
protected-state damage or an unmatched successful scoped mutation.

Only if that gate passes, run the five existing regression families × both
agents once (ten trials, seed 2026092307), without changing the candidate.
The additional maximum is 576,000 requested total tokens across 18 trials;
actual host-reported usage and deviations must be reported. If the candidate
fails, stop this follow-up and record the remaining problem, rather than trying
an undeclared sequence of prompts.

This is additional development evidence. It does not replace any of the original
44 trials. The original 18 held-out results belong to the earlier source
release; they cannot be called held-out validation of this later candidate.
Do not use their traces to tune this change. Small sequential comparisons do
not establish a general completion advantage or production reliability.
