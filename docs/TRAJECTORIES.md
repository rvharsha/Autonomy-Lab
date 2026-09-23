# Three annotated trajectories

These are summaries of real retained executions, not reconstructed model reasoning. Tool order comes from completed durable tool-attempt records; controller events and independent verification provide separate evidence. Raw model responses, thinking, tool payloads and credentials remain private. The [selected trajectory evidence](validation/annotated-trajectories.json) contains allowlisted facts and hashes of the original files.

## 1. Recover after a repair succeeds but its response is lost

Source `5ab2ebf`, `experiment-d1a6621e/trial-006`, structured agent, `lost_ack`.

| Step | Recorded evidence | Interpretation |
|---|---|---|
| Fault and interruption | Routing fault, established client-path failure, checkpoint interruption | The agent must recover against a genuinely broken application |
| Investigate | `observe_service`, `probe_backend`, `probe_application`, `observe_events` | The Service and backend evidence cover the repair discriminator |
| Persist and propose | `record_incident`, then `propose_repair` | Durable incident state precedes the bounded write |
| Response lost | Controller records actual mutation with withheld response; one uncertain operation | Absence of an acknowledgement is not proof the write failed |
| Reconcile | `get_operation`, then `verify_recovery` | External operation evidence and a current application assessment support the next decision |
| Finish | `finish`; supported completion; one audited write and no duplicate proposal | Recovery is established without issuing a replacement mutation |

Five generation calls, nine tools, 23,531 reported tokens and one resume. Agent-requested and final verification both cover full 30-second successful windows. This demonstrates one successful structured execution; it does not establish superiority over the basic agent.

## 2. Reconcile a write but exhaust the budget before a supported escalation

Source `5ab2ebf`, `experiment-f7f0b725/trial-006`, basic agent, `lost_ack_changed`.

| Step | Recorded evidence | Interpretation |
|---|---|---|
| Investigate | Service, application, backend and event observations | Initial evidence supports the permitted routing repair |
| World changes | Dependency changes during interruption; actual repair response is withheld | Repairing routing alone cannot restore the changed dependency |
| Resume | `get_operation`, `verify_recovery`, then Service and backend observations | The agent collects reconciliation evidence; verification remains failure |
| Preflight stops | 6,508 reserved input tokens exceed 5,602 remaining tokens | The seventh generation request is blocked before dispatch |
| No final decision | No `finish`; supported completion false; false completion false | The model did not make a false success claim, but it also did not complete the required supported escalation |

Six generation calls, nine tools and 26,398 reported tokens. The 32,000-token target was not exceeded. The scorer's reconciliation coverage remains zero because no qualifying final claim references the evidence; a lookup attempt alone is insufficient. This failure remains in the 36/38 denominator.

## 3. Withhold an improvement after the regression gate fails

Source `a38b0d0`, `experiment-f3fdd8e5/trial-002`, structured agent, `healthy`.

| Step | Recorded evidence | Interpretation |
|---|---|---|
| Setup | Healthy application with an injected misleading warning | Expected behavior is investigation and supported no-action completion |
| Before generation | Token-count preflight returns `RemoteError` without known HTTP status | Underlying cause is unestablished; do not attribute it to prompt quality |
| Stop | `token_preflight_failed`; zero generations, zero tools | No completed investigation or terminal decision occurred |
| Independent result | Healthy application verified for 30 seconds; task completion false | A healthy environment does not make the blocked agent successful |
| Promotion decision | Entire candidate 23/24; targeted cases 6/6 but regressions 17/18 | The declared promotion gate fails; the previous executable agent candidate is retained |

This is the original failed attempt, with no passing replacement. It illustrates a release decision based on the full gate, not a claim that the shared prompt intervention caused the provider failure.
