"""Offline, allowlisted experiment summaries; never copy arbitrary artifact strings.

Raw export requires finalized accounting. Published mode regenerates tables from
the selected reliability/reconciliation evidence already committed to the repo.
Neither mode re-scores trials or establishes authenticity of supplied evidence.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

SCENARIOS = {"routing", "distraction", "healthy", "out_of_authority", "lost_ack",
             "concurrent_change", "adversarial", "dependency_changed", "adversarial_ack",
             "lost_ack_changed"}
VARIANTS = {"basic", "structured", "runbook", "no_agent"}


def number(value):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer or unknown")
    return value


def boolean(value):
    if value is not None and type(value) is not bool:
        raise ValueError("Expected a boolean or unknown")
    return value


def choice(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("Unsupported categorical value")
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def identity(item):
    repetition = number(item["repetition"])
    if repetition is None:
        raise ValueError("Missing repetition")
    return {"scenario": choice(item["scenario"], SCENARIOS),
            "variant": choice(item["variant"], VARIANTS), "repetition": repetition}


def trial(item, *, published=False):
    output = identity(item)
    score = item.get("score") or {}
    if published:
        accounting = {"known_tokens": item.get("known_tokens"), "generation_requests": item.get("model_calls"),
                      "recorded_responses": item.get("recorded_responses")}
        if item.get("host_accounting_available") is False and output["variant"] in {"basic", "structured"}:
            # Older selected reports used zero placeholders when relay evidence was absent.
            if any(number(value) not in (None, 0) for value in accounting.values()):
                raise ValueError("Unavailable accounting contradicts recorded usage")
            accounting = {}
    else:
        accounting = item.get("model_accounting") or {}
    if output["variant"] in {"runbook", "no_agent"}:
        if any(number(accounting.get(key)) not in (None, 0) for key in
               ("known_tokens", "generation_requests", "recorded_responses")):
            raise ValueError("Model-free control contains generation usage")
        accounting = {"known_tokens": 0, "generation_requests": 0, "recorded_responses": 0}
    output.update(task_success=boolean(item.get("task_success") if published else score.get("task_success")),
                  environment_recovered=boolean(score.get("environment_recovered")),
                  known_tokens=number(accounting.get("known_tokens")),
                  generation_requests=number(accounting.get("generation_requests")),
                  recorded_responses=number(accounting.get("recorded_responses")))
    requests, responses = output["generation_requests"], output["recorded_responses"]
    if requests is not None and responses is not None and responses > requests:
        raise ValueError("More responses than requests")
    output["unknown_provider_outcome"] = None if requests is None or responses is None else requests > responses
    return output


def phase(manifest, items, cleanup, *, published=False):
    plan = [identity(item) for item in manifest["planned_trials"]]
    if len({json.dumps(item, sort_keys=True) for item in plan}) != len(plan):
        raise ValueError("Duplicate planned trial")
    selected = [trial(item, published=published) for item in items]
    if [identity(item) for item in selected] != plan[:len(selected)]:
        raise ValueError("Recorded trials do not match the ordered plan")
    return {"planned": len(plan), "recorded": len(selected), "unrun": plan[len(selected):],
            "cleanup": choice(cleanup["status"], {"deleted", "kept", "failed", "not_provisioned"}),
            "trials": selected}


def raw_run(directory):
    manifest = load(directory / "manifest.json")
    accounting = load(directory / "accounting.json")
    items = load(directory / "results.json") if (directory / "results.json").exists() else []
    result = phase(manifest, items, load(directory / "cleanup.json"))
    if (accounting["planned"] != result["planned"] or accounting["recorded"] != result["recorded"]
            or accounting["unrun"] != result["unrun"]):
        raise ValueError("Final accounting does not match evidence")
    result["evidence_sha256"] = {name: digest(directory / name) for name in
                                 ("manifest.json", "release.json", "accounting.json", "cleanup.json")}
    if (directory / "results.json").exists():
        result["evidence_sha256"]["results.json"] = digest(directory / "results.json")
    return result


def published_report(path):
    report = load(path)
    commit = report["source_commit"]
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("Invalid source commit")
    phases = [phase(p["manifest"], p["trials"], p["cleanup"], published=True) for p in report["phases"]]
    if (report["planned_trials"] != sum(p["planned"] for p in phases)
            or report["recorded_trials"] != sum(p["recorded"] for p in phases)):
        raise ValueError("Published accounting does not match evidence")
    return {"schema_version": 1, "source_commit": commit,
            "published_evidence_sha256": digest(path), "phases": phases}


def render(report):
    lines = ["# Selected experiment report", "",
             "Recorded outcomes, including failures and unscored attempts; no re-scoring or retries.",
             "Phases and source candidates must remain separate. Small samples do not establish production reliability.",
             "Model-free controls have zero generation usage; unavailable model accounting remains unknown.", "",
             "| Phase | Planned | Recorded | Supported completions | Unrun | Reported tokens* | Cleanup |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for index, p in enumerate(report["phases"], 1):
        tokens = [t["known_tokens"] for t in p["trials"]]
        total = str(sum(tokens)) if all(t is not None for t in tokens) else "unknown"
        lines.append(f"| {index} | {p['planned']} | {p['recorded']} | {sum(t['task_success'] is True for t in p['trials'])} | {len(p['unrun'])} | {total} | {p['cleanup']} |")
    lines += ["", "*Provider-reported usage is not an invoice or a strict billing cap.", "",
              "The companion JSON retains per-trial outcomes and source-evidence hashes. Raw model content, credentials, tool arguments, and arbitrary diagnostic strings are excluded.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", type=Path, nargs="+")
    source.add_argument("--published", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New directory; existing output is never overwritten")
    args = parser.parse_args()
    report = published_report(args.published) if args.published else {
        "schema_version": 1, "phases": [raw_run(path) for path in args.run]}
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.output / "REPORT.md").write_text(render(report))
    print(args.output / "REPORT.md")


if __name__ == "__main__":
    main()
