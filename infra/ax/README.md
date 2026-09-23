# AX data-resume compatibility patch

`cold-boot.patch` applies to `google/ax` commit
`d8ed0fe38bceb7842d3c47817d53d16ccdfcb601`. The accompanying manifest records
the original, patched and patch-file SHA-256 values. Apply it only to that
verified source and rebuild the controller; an existing controller image
does not acquire the policy by changing this file.

Use a fresh isolated deployment for this experiment. AX returns an existing
ActorTemplate without updating its policy; rebuilding the controller does not
migrate existing templates from GOLDEN to COLD_BOOT.

The lab's recovery contract is a new command process reading restored durable
files. Pinned Substrate documents `RESUME_SOURCE_COLD_BOOT` as starting fresh
containers from the OCI image with durable directories populated from the
snapshot. The patch selects that policy for AX's DATA snapshots. It preserves
DATA snapshot capture and `/workspace` restoration. It does not change
Substrate's FULL snapshot behavior, authorization, or verification criteria.

The unmodified controller's first real data resume failed because its required
golden snapshot was not yet available. The snapshot appeared later, but AX
had already acknowledged the failed event and did not retry it. Cold boot
also avoids depending on the point at which a template's running process was
captured when testing application-level checkpoint reconstruction.

This is an explicit lab compatibility variant, not an upstream fix or a
claim that unmodified AX passed. The [runtime record](../../docs/AX_RUNTIME_STATUS.md)
retains both failed attempts and the separately identified patched attempt.
The patched attempt also failed its three-cycle gate: one cycle restored the
durable records into a fresh command process, then the second resume failed
with no free worker available. This patch alone is insufficient for reliable
AX lifecycle recovery and is not enabled in the application runtime.
The patch received a [funded Fable source review](../../docs/FUNDED_REVIEW.md);
that review does not change its failed runtime result.
The local preparation/launch scripts are not yet a supported clean-clone
installer; runtime lifecycle, isolation and agent/broker integration have
separate validation gates.
