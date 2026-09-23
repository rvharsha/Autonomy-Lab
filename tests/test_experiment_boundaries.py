"""Isolated harness regression tests; these are not real-system trial results."""

import json
from types import SimpleNamespace

import pytest

from autonomy_lab import experiments
from autonomy_lab.experiments import run_experiment, run_trial
from autonomy_lab.harness import client_path_failed


def measurement(status, control=200):
    return {
        "verdict": "verified_failure",
        "probes": [
            {
                "observations": {
                    "quote_control": {"status_code": control},
                    "inventory_control": {"status_code": 200},
                    "quotes": [{"case_id": "available-single", "status_code": status}],
                }
            }
        ],
    }


def test_configuration_failure_alone_does_not_establish_client_failure():
    assert not client_path_failed(measurement(200))
    assert client_path_failed(measurement(503))
    assert not client_path_failed(measurement(503, control=503))
    assert not client_path_failed({"probes": []})


def test_latest_probe_must_still_show_client_failure():
    result = measurement(503)
    result["probes"].extend(measurement(200)["probes"])
    assert not client_path_failed(result)


def test_identity_failure_is_recorded_as_attempted_trial(monkeypatch, tmp_path):
    def fail_identity(*args):
        raise RuntimeError("private credentials must never be copied to trial errors")

    monkeypatch.setattr("autonomy_lab.experiments.service_identity", fail_identity)
    run_dir = tmp_path / "trial"
    result = run_trial(SimpleNamespace(), run_dir, "routing", "basic", {})
    recorded = json.loads((run_dir / "trial.json").read_text())
    assert result["status"] == recorded["status"] == "infrastructure_error"
    assert recorded["error_type"] == "RuntimeError"
    assert recorded["failed_stage"] == "identities"
    assert "private credentials" not in json.dumps(recorded)
    assert recorded["finished_at"]


def test_interrupted_trial_is_persisted_and_counted_before_cleanup(monkeypatch, tmp_path):
    def interrupt_identity(*args):
        raise KeyboardInterrupt

    def provision(run_dir, run_id):
        (run_dir / "environment.json").write_text("{}")
        return SimpleNamespace()

    cleanup = []
    monkeypatch.setattr(experiments, "ROOT", tmp_path)
    monkeypatch.setattr(experiments, "release_manifest", lambda config: {})
    monkeypatch.setattr(experiments, "provision", provision)
    monkeypatch.setattr(experiments, "teardown", lambda path: cleanup.append(path))
    monkeypatch.setattr(experiments, "service_identity", interrupt_identity)
    config = {
        "scenarios": ["routing", "healthy"],
        "variants": ["no_agent"],
        "repetitions": 1,
        "window_seconds": 30,
        "expected_behavior": {"routing": "repair", "healthy": "healthy"},
    }

    with pytest.raises(KeyboardInterrupt):
        run_experiment(config)

    run_dir = next((tmp_path / "artifacts").iterdir())
    trial = json.loads((run_dir / "trial-001/trial.json").read_text())
    results = json.loads((run_dir / "results.json").read_text())
    accounting = json.loads((run_dir / "accounting.json").read_text())
    assert trial["status"] == "interrupted"
    assert trial["finished_at"]
    assert results[0]["trial_id"] == trial["trial_id"]
    assert accounting == {
        "planned": 2,
        "recorded": 1,
        "status_counts": {"interrupted": 1},
        "unrun": [{"scenario": "healthy", "variant": "no_agent", "repetition": 0}],
    }
    assert cleanup == [run_dir]
    assert "interrupted" in (run_dir / "REPORT.md").read_text()


@pytest.mark.parametrize(
    "field,value",
    [
        ("window_seconds", None),
        ("window_seconds", float("inf")),
        ("window_seconds", -1),
        ("window_seconds", True),
        ("model", None),
        ("max_tokens", None),
        ("max_tokens", True),
        ("max_turns", 0),
        ("max_output_tokens", "2048"),
        ("expected_behavior", {}),
        ("expected_behavior", {"routing": "unknown"}),
        ("scenarios", []),
        ("scenarios", ["routing", "routing"]),
        ("variants", ["unsupported"]),
        ("repetitions", -1),
    ],
)
def test_invalid_contract_stops_before_credentials_or_provision(monkeypatch, field, value):
    config = {
        "scenarios": ["routing"],
        "variants": ["basic"],
        "repetitions": 1,
        "window_seconds": 30,
        "expected_behavior": {"routing": "repair"},
        "model": "gemini-3.8-flash",
        "max_turns": 12,
        "max_tokens": 32000,
        "max_output_tokens": 2048,
    }
    if value is None:
        config.pop(field)
    else:
        config[field] = value

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid experiment attempted credentials or provisioning")

    monkeypatch.setattr(experiments, "gemini_key", unexpected)
    monkeypatch.setattr(experiments, "provision", unexpected)
    with pytest.raises(ValueError, match="Manifest"):
        run_experiment(config)
