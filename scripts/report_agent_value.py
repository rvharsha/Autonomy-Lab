"""Regenerate allowlisted comparison tables from one finalized real experiment."""

import argparse
import hashlib
import json
import math
import re
import statistics
from itertools import product
from pathlib import Path

from export_report import boolean, choice, number, raw_run

ACTORS = ("runbook", "basic", "structured", "no_agent")
SCENARIOS = ("routing", "healthy", "lost_ack", "quote_arithmetic", "quote_upstream", "observer_outage")


def elapsed(value):
    if value is None:
        return None
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid elapsed time")
    return value


def tool_count(path):
    if not path.exists():
        return None
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        return None
    try:
        items = [json.loads(line) for line in data.splitlines()]
        return len(items) if all(isinstance(item, dict) for item in items) else None
    except ValueError:
        return None


def build(run):
    selected = raw_run(run)
    results = json.loads((run / "results.json").read_text()) if (run / "results.json").exists() else []
    manifest = json.loads((run / "manifest.json").read_text())
    release = json.loads((run / "release.json").read_text())
    release_id = release["release_id"]
    if not isinstance(release_id, str) or re.fullmatch(r"[a-f0-9]{64}", release_id) is None:
        raise ValueError("Invalid release identifier")
    name = choice(manifest["name"], {"agent-value-comparison", "agent-value-injection-gates"})
    scenarios, actors, repetitions = ((SCENARIOS, ACTORS, range(2)) if name == "agent-value-comparison"
                                      else (SCENARIOS[3:], ("runbook", "no_agent"), range(1)))
    plan = manifest["planned_trials"]
    if {(p["scenario"], p["variant"], p["repetition"]) for p in plan} != set(product(scenarios, actors, repetitions)):
        raise ValueError("Plan differs from the declared comparison")
    trials = []
    for index, (safe, original) in enumerate(zip(selected["trials"], results, strict=True), 1):
        score = original.get("score") or {}
        audit = original.get("execution_audit") or {}
        directory = run / f"trial-{index:03d}"
        damage = original.get("protected_state_damage")
        if damage is not None and not isinstance(damage, list):
            raise ValueError("Invalid protected-state assessment")
        row = {**safe, "index": index, "elapsed_seconds": elapsed(original.get("elapsed_seconds")),
               "status": choice(original["status"], {"recorded", "infrastructure_error", "timed_out", "interrupted"}),
               "external_tool_calls": tool_count(directory / "evidence.jsonl"),
               "audit_assessed": audit.get("status") == "assessed",
               "unmatched_successful_mutations": number(audit.get("successful_unmatched_mutations")),
               "protected_state_damage": bool(damage) if damage is not None else None,
               "original_trial_sha256": hashlib.sha256((directory / "trial.json").read_bytes()).hexdigest()}
        for key in ("false_completion", "unsupported_completion", "appropriate_escalation", "correct_restraint"):
            row[key] = boolean(score.get(key))
        for key in ("unsafe_proposals", "stale_proposals", "duplicate_proposals", "dispatched_or_potentially_dispatched_operations"):
            row[key] = number(score.get(key))
        # Exposure is factual only when the actual observation record contains an error.
        evidence = directory / "evidence.jsonl"
        row["backend_error_observed"] = None
        if row["external_tool_calls"] is not None:
            observations = [json.loads(line) for line in evidence.read_bytes().splitlines()]
            if any(not isinstance(o.get("payload"), dict) for o in observations):
                raise ValueError("Invalid observation payload")
            row["backend_error_observed"] = any(o.get("source") == "probe_backend" and
                o["payload"].get("kind") == "error" for o in observations)
        trials.append(row)
    return {"schema_version": 1, "name": name, "release_id": release_id,
            "evidence_sha256": selected["evidence_sha256"], "planned": selected["planned"],
            "recorded": selected["recorded"], "unrun": selected["unrun"], "cleanup": selected["cleanup"],
            "plan": [{k: item[k] for k in ("scenario", "variant", "repetition")} for item in manifest["planned_trials"]],
            "trials": trials,
            "limitations": "Descriptive complete-actor comparison on designed scenarios, not a causal representation ablation or production reliability estimate. Time includes trial setup/final verification but excludes cluster provision and between-trial reset. No-agent controls have no task-success score. Tokens are not an invoice."}


def distribution(values):
    known = [value for value in values if value is not None]
    if not known:
        return "unknown"
    text = f"{statistics.median(known):.1f} [{min(known):.1f}, {max(known):.1f}]"
    return text + (f"; {len(values) - len(known)} unknown" if len(known) != len(values) else "")


def render(report):
    lines = ["# Automation and agent comparison", "",
             f"Release `{report['release_id']}`. Recorded {report['recorded']}/{report['planned']}; cleanup: {report['cleanup']}.",
             "", "Supported completions / planned trials. Controls show independently healthy environments / planned trials.", "",
             "| Scenario | Runbook | Basic | Structured | No-agent healthy |", "|---|---:|---:|---:|---:|"]
    for scenario in SCENARIOS:
        if not any(p["scenario"] == scenario for p in report["plan"]):
            continue
        cells = []
        for actor in ACTORS:
            planned = sum(p["scenario"] == scenario and p["variant"] == actor for p in report["plan"])
            rows = [t for t in report["trials"] if t["scenario"] == scenario and t["variant"] == actor]
            metric = "environment_recovered" if actor == "no_agent" else "task_success"
            cells.append(f"{sum(t[metric] is True for t in rows)}/{planned}" if planned else "—")
        lines.append(f"| {scenario} | " + " | ".join(cells) + " |")
    lines += ["", "## Recorded usage and duration", "",
              "Medians [minimum, maximum] include successful and unsuccessful recorded attempts; missing values are explicit. Unrun trials have no measured duration or usage.", "",
              "| Variant | Recorded | Known tokens | Trials with unknown tokens | Unknown provider outcome (true / unassessed) | Trial seconds | External tool calls |",
              "|---|---:|---:|---:|---|---|---|"]
    for actor in ACTORS:
        rows = [t for t in report["trials"] if t["variant"] == actor]
        if rows:
            lines.append(f"| {actor} | {len(rows)} | {sum(t['known_tokens'] or 0 for t in rows)} | {sum(t['known_tokens'] is None for t in rows)} | {sum(t['unknown_provider_outcome'] is True for t in rows)} / {sum(t['unknown_provider_outcome'] is None for t in rows)} | {distribution([t['elapsed_seconds'] for t in rows])} | {distribution([t['external_tool_calls'] for t in rows])} |")
    lines += ["", "## Integrity", "",
              f"Assessed scoped audits: {sum(t['audit_assessed'] for t in report['trials'])}/{report['recorded']}. Unrun trials: {len(report['unrun'])}."]
    for key in ("false_completion", "unsupported_completion", "unsafe_proposals", "stale_proposals", "duplicate_proposals", "unmatched_successful_mutations", "protected_state_damage"):
        values = [t[key] for t in report["trials"]]
        lines.append(f"- {key}: {sum(v for v in values if v is not None)} recorded; {sum(v is None for v in values)} unassessed.")
    lines += ["", report["limitations"], ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.run)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.output / "REPORT.md").write_text(render(report))
    print(args.output / "REPORT.md")


if __name__ == "__main__":
    main()
