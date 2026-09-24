# Corrected research release validation

Target release: **v0.1.1**. This release includes the previously reviewed native Linux audit-permission correction, reproducible handoff tools, selected trajectory evidence and a consolidated findings document. It retains the selected agent behavior; the unpromoted reconciliation prompt is not included.

## Declared completion gates

- Tests and lint pass on the release candidate.
- Fable findings on the suite runner/exporter are checked and dispositioned.
- A fresh CI checkout passes the 17 real Kubernetes acceptance checks and the separate four-trial model-free handoff manifest.
- The handoff experiment preserves its negative control, has clean scoped audits and deleted resources, and produces byte-identical selected reports on repeat export.
- Committed evidence regenerates reliability 36/38 and reconciliation 23/24 tables without accessing private raw model responses.
- The corrected tag and installed GCP checkout identify the released source; runtime files match the validated deployment implementation.

The [executed validation record](validation/handoff-validation.json) records source `75bd50b` and [successful clean-checkout CI](https://github.com/rvharsha/Autonomy-Lab/actions/runs/35930987050): **710 tests, lint, 17 real acceptance checks and all four handoff trials**. Both runbook cases completed; the two no-agent controls remain unscored. Routing stayed broken in its no-agent control, and the other three environments were healthy. All four scoped audits were clean, cleanup deleted the cluster, and repeated report export was byte-identical. No model generation calls occurred.

Offline export from the original private artifacts also matched every selected per-trial field regenerated from the committed reliability (38 trials) and reconciliation (24 trials) evidence. The report counters retain the original 36/38 and 23/24 outcomes. Historical Gemini experiments remain separate.

Four completed [Fable reviews and checked dispositions](validation/handoff-reviews.json) cover the handoff tools. Verified findings corrected contradictory usage handling and interrupted-phase provenance. The final reviewed file hashes match; conditional findings contradicted by the called implementation are retained with their rationale. The existing restricted credential-parser format is explicitly documented.

Subsequent release-record edits do not change the validated runtime or handoff scripts. The final PR head still requires its own CI checks before merge. The [v0.1.1 release](https://github.com/rvharsha/Autonomy-Lab/releases/tag/v0.1.1) publishes `release-receipt.json` with the exact reviewed/tagged source, final CI, archive digest and verified GCP installation. That receipt, rather than a mutable branch name, identifies the installed release. All 30 runtime Python files are unchanged from the previously validated GCP audit correction `a5e1912`.

## Review and trust boundaries

Fable is an additional source reviewer through direct Anthropic calls, with unchanged component token/cost bounds. The owner checks findings before accepting or rejecting them. The GitHub workflow performs a clean-checkout execution; cloud installation checks the archive and runtime hashes. The Docker host/controller remains trusted.

The suite wrapper intentionally leaves `run_directory_unknown: true` if the underlying experiment raises before returning a path. Its phase is marked interrupted, later phases remain unrun, original evidence remains in `artifacts/experiment-*`, and no automatic retry or successful completion is inferred. Full crash-resumable suite orchestration is outside this handoff; the existing trial deadlines and detached cleanup remain in force.

For actual research limitations and deferred experiments, use [FINDINGS.md](FINDINGS.md).
