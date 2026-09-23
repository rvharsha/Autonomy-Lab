# Corrected research release validation

Target release: **v0.1.1**. This release includes the previously reviewed native Linux audit-permission correction, reproducible handoff tools, selected trajectory evidence and a consolidated findings document. It retains the selected agent behavior; the unpromoted reconciliation prompt is not included.

## Declared completion gates

- Tests and lint pass on the release candidate.
- Fable findings on the suite runner/exporter are checked and dispositioned.
- A fresh CI checkout passes the 17 real Kubernetes acceptance checks and the separate four-trial model-free handoff manifest.
- The handoff experiment preserves its negative control, has clean scoped audits and deleted resources, and produces byte-identical selected reports on repeat export.
- Committed evidence regenerates reliability 36/38 and reconciliation 23/24 tables without accessing private raw model responses.
- The corrected tag and installed GCP checkout identify the released source; runtime files match the validated deployment implementation.

Execution receipts will be added below as these gates finish. This declaration does not itself claim the checks passed. Historical Gemini experiments remain separate; the handoff gate does not make new model calls.

## Review and trust boundaries

Fable is an additional source reviewer through direct Anthropic calls, with unchanged component token/cost bounds. The owner checks findings before accepting or rejecting them. The GitHub workflow performs a clean-checkout execution; cloud installation checks the archive and runtime hashes. The Docker host/controller remains trusted.

The suite wrapper intentionally leaves `run_directory_unknown: true` if the underlying experiment raises before returning a path. Its phase is marked interrupted, later phases remain unrun, original evidence remains in `artifacts/experiment-*`, and no automatic retry or successful completion is inferred. Full crash-resumable suite orchestration is outside this handoff; the existing trial deadlines and detached cleanup remain in force.

For actual research limitations and deferred experiments, use [FINDINGS.md](FINDINGS.md).
