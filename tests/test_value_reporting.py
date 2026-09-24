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


def fixture_run(path, name="agent-value-comparison"):
    scenarios, actors, repetitions = reporter.STUDIES[name]
    plan = [dict(scenario=s, variant=v, repetition=r) for s, v, r in
            product(scenarios, actors, repetitions)]
    rows = [{**p, "status": "recorded", "score": {"task_success": False, "environment_recovered": False},
             "protected_state_damage": [], "elapsed_seconds": 10} for p in plan[:3]]
    rows[2]["status"] = "infrastructure_error"
    rows[2].pop("score")
    rows[2].pop("protected_state_damage")
    for index, row in enumerate(rows, 1):
        directory = path / f"trial-{index:03d}"
        directory.mkdir()
        write(directory / "trial.json", row)
    write(path / "manifest.json", {"name": name, "planned_trials": plan})
    write(path / "release.json", {"release_id": "a" * 64})
    write(path / "results.json", rows)
    write(path / "accounting.json", {"planned": len(plan), "recorded": 3, "unrun": plan[3:]})
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


def test_separate_fallback_validation_keeps_its_own_denominator(tmp_path):
    fixture_run(tmp_path, 'runbook-fallback-validation')
    report = reporter.build(tmp_path)
    assert report['planned'] == 32 and report['recorded'] == 3 and len(report['unrun']) == 29
    assert set(p['variant'] for p in report['plan']) == {'runbook_fallback', 'no_agent'}
    assert report['trials'][2]['task_success'] is None
    text = reporter.render(report)
    assert '| Scenario | Fallback | No-agent healthy |' in text
    assert 'Separate runbook fallback validation' in text


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


@pytest.mark.parametrize("accounting", [None, {"known_tokens": 120, "generation_requests": 2, "recorded_responses": 1}])
def test_missing_or_unfinished_accounting_labels_tokens_as_partial(tmp_path, accounting):
    rows = fixture_run(tmp_path)
    rows[2]["model_accounting"] = accounting
    write(tmp_path / "results.json", rows)
    rendered = reporter.render(reporter.build(tmp_path))
    assert f"| basic | 1 | ≥{120 if accounting else 0} (partial) |" in rendered


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


def test_fallback_plan_keeps_original_and_treatment_and_unknown_verification(tmp_path):
    rows = fixture_run(tmp_path, "runbook-fallback-comparison")
    rows[0]["score"]["verification_verdict"] = "verified_success"
    write(tmp_path / "results.json", rows)
    (tmp_path / "trial-001/evidence.jsonl").write_text(json.dumps({
        "source": "verify_recovery", "payload": {"verdict": "indeterminate", "private": "NOT_EXPORTED"}}) + "\n")
    r = reporter.build(tmp_path)
    assert (r["planned"], r["recorded"], len(r["unrun"])) == (80, 3, 77)
    assert r["trials"][0]["final_verification_verdict"] == "verified_success"
    assert r["trials"][0]["actor_verification_verdicts"] == ["indeterminate"]
    assert r["trials"][2]["actor_verification_verdicts"] is None
    assert r["trials"][2]["known_tokens"] == 0  # Explicit model-free treatment.
    assert "| Scenario | Runbook | Fallback | Basic | Structured | No-agent healthy |" in reporter.render(r)
    assert "NOT_EXPORTED" not in json.dumps(r)


@pytest.mark.parametrize("source,table", [("agent-value-comparison.json", "AGENT_VALUE_MEASUREMENTS.md"),
                                         ("agent-value-gates.json", "AGENT_VALUE_GATES.md")])
def test_historical_published_tables_are_unchanged(source, table):
    docs = SCRIPTS.parent / "docs"
    assert reporter.render(json.loads((docs / "validation" / source).read_text())) == (docs / table).read_text()
