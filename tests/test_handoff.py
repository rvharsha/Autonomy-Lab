"""Report integrity checks against retained, real public evidence; no model calls."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reporter = script("export_report")
runner = script("run_evaluation")


def evidence():
    return json.loads((ROOT / "docs/validation/reliability-validation.json").read_text())


def test_regenerates_retained_comparison_without_dropping_failures():
    report = reporter.published_report(ROOT / "docs/validation/reliability-validation.json")
    assert [sum(t["task_success"] is True for t in p["trials"]) for p in report["phases"]] == [12, 8, 16]
    assert sum(t["known_tokens"] for p in report["phases"] for t in p["trials"]) == 546910


def test_unrun_attempts_and_unknown_usage_are_not_success_or_zero():
    p = evidence()["phases"][0]
    items = copy.deepcopy(p["trials"][:2])
    items[0].update(task_success=None, host_accounting_available=False,
                    known_tokens=0, model_calls=0, recorded_responses=0)
    result = reporter.phase(p["manifest"], items, p["cleanup"], published=True)
    assert result["recorded"] == 2 and len(result["unrun"]) == 10
    assert result["trials"][0]["known_tokens"] is None
    assert result["trials"][0]["task_success"] is None
    assert "unknown" in reporter.render({"phases": [result]})


@pytest.mark.parametrize("corruption", ["duplicate", "reorder", "extra", "truthy", "negative", "responses"])
def test_rejects_misleading_accounting(corruption):
    p = evidence()["phases"][0]
    if corruption == "duplicate":
        p["manifest"]["planned_trials"][1] = p["manifest"]["planned_trials"][0]
    elif corruption == "reorder":
        p["trials"].reverse()
    elif corruption == "extra":
        p["trials"].append(p["trials"][0])
    elif corruption == "truthy":
        p["trials"][0]["task_success"] = "true"
    elif corruption == "negative":
        p["trials"][0]["known_tokens"] = -1
    else:
        p["trials"][0]["recorded_responses"] = p["trials"][0]["model_calls"] + 1
    with pytest.raises(ValueError):
        reporter.phase(p["manifest"], p["trials"], p["cleanup"], published=True)


def test_free_text_and_nested_provider_content_never_exported():
    p = evidence()["phases"][0]
    marker = "PRIVATE_CONTENT_MUST_NOT_BE_EXPORTED"
    p["trials"][0].update(reason=marker, usage={"thinking": marker},
                          model_responses=[marker], error_type=marker, trial=marker)
    p["trials"][0]["score"]["task_success_basis"] = marker
    p["cleanup"]["error_message"] = marker
    p["manifest"]["model"] = marker
    result = reporter.phase(p["manifest"], p["trials"], p["cleanup"], published=True)
    assert marker not in json.dumps(result) + reporter.render({"phases": [result]})
    p["trials"][0]["scenario"] = marker
    with pytest.raises(ValueError, match="categorical"):
        reporter.phase(p["manifest"], p["trials"], p["cleanup"], published=True)


@pytest.mark.parametrize("variant", ["runbook", "no_agent"])
def test_control_cannot_hide_recorded_generation_usage(variant):
    item = evidence()["phases"][0]["trials"][0]
    item["variant"] = variant
    with pytest.raises(ValueError, match="Model-free control"):
        reporter.trial(item, published=True)
    raw = {**item, "model_accounting": {"known_tokens": item["known_tokens"],
           "generation_requests": item["model_calls"], "recorded_responses": item["recorded_responses"]}}
    with pytest.raises(ValueError, match="Model-free control"):
        reporter.trial(raw)


def test_unavailable_flag_cannot_erase_recorded_usage():
    item = evidence()["phases"][0]["trials"][0]
    item["host_accounting_available"] = False
    with pytest.raises(ValueError, match="contradicts"):
        reporter.trial(item, published=True)


def test_suite_stops_on_source_change_without_running_next_phase(tmp_path, monkeypatch):
    record = runner.plan([ROOT / "scenarios/handoff-acceptance.yaml"] * 2)
    calls = []
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "accounting.json").write_text('{"recorded": 4}')

    def run(*args, **kwargs):
        calls.append(1)
        monkeypatch.setattr(runner, "release_manifest", lambda _: {"files": {}})
        return run_dir

    monkeypatch.setattr(runner, "run_experiment", run)
    with pytest.raises(RuntimeError, match="Source changed"):
        runner.execute(record, tmp_path / "suite", None)
    saved = json.loads((tmp_path / "suite/evaluation.json").read_text())
    assert calls == [1] and saved["status"] == "stopped"
    assert saved["phases"][1]["status"] == "unrun"


def test_suite_preserves_exception_and_unrun_phases(tmp_path, monkeypatch):
    record = runner.plan([ROOT / "scenarios/handoff-acceptance.yaml"] * 2)

    def stop(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_experiment", stop)
    with pytest.raises(KeyboardInterrupt):
        runner.execute(record, tmp_path / "suite", None)
    saved = json.loads((tmp_path / "suite/evaluation.json").read_text())
    assert saved["status"] == "stopped" and saved["phases"][1]["status"] == "unrun"
    assert saved["phases"][0]["status"] == "interrupted"
    assert saved["phases"][0]["run_directory_unknown"] is True
