"""Adversarial exporter fixtures only; these are not measured experiment outcomes."""

import importlib.util
import json
import sys
from itertools import product
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("export_report", SCRIPTS / "export_report.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
sys.modules.setdefault("export_report", exporter)
spec = importlib.util.spec_from_file_location("report_agent_value", SCRIPTS / "report_agent_value.py")
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def write(path, value):
    path.write_text(json.dumps(value))


def fixture_run(path):
    plan = [dict(scenario=s, variant=v, repetition=r) for s, v, r in
            product(reporter.SCENARIOS, reporter.ACTORS, range(2))]
    rows = [{**p, "status": "recorded", "score": {"task_success": False, "environment_recovered": False},
             "protected_state_damage": [], "elapsed_seconds": 10} for p in plan[:3]]
    rows[2]["status"] = "infrastructure_error"
    rows[2].pop("score")
    rows[2].pop("protected_state_damage")
    for index, row in enumerate(rows, 1):
        directory = path / f"trial-{index:03d}"
        directory.mkdir()
        write(directory / "trial.json", row)
    write(path / "manifest.json", {"name": "agent-value-comparison", "planned_trials": plan})
    write(path / "release.json", {"release_id": "a" * 64})
    write(path / "results.json", rows)
    write(path / "accounting.json", {"planned": 48, "recorded": 3, "unrun": plan[3:]})
    write(path / "cleanup.json", {"status": "deleted"})
    return rows


def test_failed_unscored_and_unrun_trials_remain_in_denominator(tmp_path):
    fixture_run(tmp_path)
    report = reporter.build(tmp_path)
    assert (report["planned"], report["recorded"], len(report["unrun"])) == (48, 3, 45)
    assert report["trials"][2]["task_success"] is None
    assert report["trials"][2]["protected_state_damage"] is None
    assert report["trials"][2]["known_tokens"] is None
    assert "| routing | 0/2 | 0/2 | 0/2 | 0/2 |" in reporter.render(report)


def test_private_payloads_excluded_and_actual_observer_error_selected(tmp_path):
    rows = fixture_run(tmp_path)
    marker = "DO_NOT_EXPORT_PRIVATE_TEXT"
    rows[0].update(reason=marker, model_responses=[marker])
    rows[0]["protected_state_damage"] = [marker]
    write(tmp_path / "results.json", rows)
    (tmp_path / "trial-001/evidence.jsonl").write_text(json.dumps({
        "source": "probe_backend", "payload": {"kind": "error", "private": marker}}) + "\n")
    report = reporter.build(tmp_path)
    assert report["trials"][0]["backend_error_observed"] is True
    assert report["trials"][0]["external_tool_calls"] == 1
    assert marker not in json.dumps(report) + reporter.render(report)


def test_torn_observation_is_unknown_not_zero_or_success(tmp_path):
    fixture_run(tmp_path)
    (tmp_path / "trial-001/evidence.jsonl").write_text('{"source":')
    row = reporter.build(tmp_path)["trials"][0]
    assert row["external_tool_calls"] is None and row["backend_error_observed"] is None


@pytest.mark.parametrize("field,value", [("elapsed_seconds", -1), ("elapsed_seconds", float("nan")),
                                        ("status", "SECRET"), ("protected_state_damage", "false")])
def test_malformed_measurements_rejected(tmp_path, field, value):
    rows = fixture_run(tmp_path)
    rows[0][field] = value
    write(tmp_path / "results.json", rows)
    with pytest.raises(ValueError):
        reporter.build(tmp_path)


def test_other_valid_scenario_cannot_be_silently_omitted(tmp_path):
    fixture_run(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["planned_trials"][-1]["scenario"] = "adversarial"
    write(tmp_path / "manifest.json", manifest)
    accounting = json.loads((tmp_path / "accounting.json").read_text())
    accounting["unrun"][-1]["scenario"] = "adversarial"
    write(tmp_path / "accounting.json", accounting)
    with pytest.raises(ValueError, match="declared comparison"):
        reporter.build(tmp_path)
