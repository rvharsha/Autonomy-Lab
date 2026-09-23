"""Real process termination plus explicitly authored partial-record unit cases."""

import json
import subprocess
import sys
import time

import pytest

from autonomy_lab import experiments
from autonomy_lab.kubernetes import Kubernetes
from autonomy_lab.supervisor import supervise


@pytest.mark.parametrize("parent_exits", [False, True])
def test_supervisor_reaps_owned_descendants(tmp_path, parent_exits):
    heartbeat = tmp_path / "heartbeat"
    child = "import pathlib,time; p=pathlib.Path('heartbeat');\nwhile True:\n p.write_text(str(time.monotonic())); time.sleep(.01)"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}], cwd={str(tmp_path)!r})\n"
        f"time.sleep({0.2 if parent_exits else 30})\n"
    )
    result = supervise([sys.executable, str(worker)], timeout=0.7, log_path=tmp_path / "worker.log")
    assert result["timed_out"] is not parent_exits
    assert result["elapsed_seconds"] < 2
    assert heartbeat.exists()
    before = heartbeat.read_bytes()
    time.sleep(0.1)
    assert heartbeat.read_bytes() == before


def test_supervisor_does_not_kill_unrelated_process(tmp_path):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        supervise([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1, log_path=tmp_path / "worker.log")
        assert other.poll() is None
    finally:
        other.kill()
        other.wait(timeout=2)


@pytest.mark.parametrize("partial", ['{"truncated":', '{"status":"running","trial_id":"test-trial","scenario":"routing","variant":"basic"}'])
def test_dead_worker_keeps_partial_record_and_does_not_receive_success(tmp_path, monkeypatch, partial):
    def timeout(command, *, timeout, log_path):
        (log_path.parent / "trial.json").write_text(partial)
        return {"timed_out": True, "exit_code": -9, "elapsed_seconds": timeout}

    monkeypatch.setattr(experiments, "supervise", timeout)
    kube = Kubernetes(tmp_path / "kubeconfig", "autolab-12345678")
    result = experiments.supervise_trial(kube, tmp_path / "trial", "routing", "basic",
                                        {"trial_timeout_seconds": 1}, release_id="1" * 64)
    assert result["status"] == "timed_out" and "score" not in result
    assert (tmp_path / "trial/trial-worker-partial.json").read_text() == partial
    assert json.loads((tmp_path / "trial/trial.json").read_text()) == result


def test_controller_cancellation_records_interrupted_trial(tmp_path, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(experiments, "supervise", interrupt)
    kube = Kubernetes(tmp_path / "kubeconfig", "autolab-12345678")
    with pytest.raises(KeyboardInterrupt):
        experiments.supervise_trial(kube, tmp_path / "trial", "routing", "basic",
                                    {"trial_timeout_seconds": 1}, release_id="1" * 64)
    assert json.loads((tmp_path / "trial/trial.json").read_text())["status"] == "interrupted"


def test_worker_launch_failure_is_an_accounted_attempt(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("private launch details")

    monkeypatch.setattr(experiments, "supervise", fail)
    result = experiments.supervise_trial(Kubernetes(tmp_path / "kubeconfig", "autolab-12345678"),
                                        tmp_path / "trial", "routing", "basic",
                                        {"trial_timeout_seconds": 1}, release_id="1" * 64)
    assert result["status"] == "infrastructure_error"
    assert result["supervisor"]["error_type"] == "OSError"
    assert "private launch" not in json.dumps(result)


def test_actual_trial_worker_rejects_release_drift_before_infrastructure(tmp_path):
    request = tmp_path / "worker-request.json"
    request.write_text(json.dumps({
        "config": {"scenarios": ["routing"], "variants": ["no_agent"], "repetitions": 1,
                   "window_seconds": 1, "expected_behavior": {"routing": "repair"}},
        "release_id": "0" * 64,
    }))
    result = supervise([sys.executable, "-m", "autonomy_lab.trial_worker", str(request)],
                       timeout=10, log_path=tmp_path / "worker.log")
    assert result["exit_code"] == 1
    assert json.loads((tmp_path / "worker.log").read_text()) == {"worker_error_type": "ValueError"}
    assert not (tmp_path / "trial.json").exists()
    assert not (tmp_path / "broker-kubeconfig").exists()


def test_actual_worker_enters_trial_with_supervisor_prepared_directory(tmp_path):
    # A deliberately nonexistent explicit kubeconfig forces an identity-setup
    # failure. This tests process startup/accounting, not Kubernetes acceptance.
    config = {"scenarios": ["routing"], "variants": ["no_agent"], "repetitions": 1,
              "window_seconds": 1, "expected_behavior": {"routing": "repair"},
              "trial_timeout_seconds": 10}
    kube = Kubernetes(tmp_path / "nonexistent-kubeconfig", "autolab-12345678")
    result = experiments.supervise_trial(kube, tmp_path / "trial", "routing", "no_agent", config,
                                        release_id=experiments.release_manifest(config)["release_id"])
    assert result["status"] == "infrastructure_error"
    assert result["failed_stage"] == "identities"
    assert json.loads((tmp_path / "trial/supervisor.json").read_text())["exit_code"] == 0


def test_prepared_worker_cannot_overwrite_prior_trial(tmp_path):
    directory = tmp_path / "trial"
    directory.mkdir()
    original = '{"status":"recorded"}'
    (directory / "trial.json").write_text(original)
    with pytest.raises(ValueError, match="overwrite"):
        experiments.run_trial(None, directory, "routing", "basic", {}, workspace_prepared=True)
    assert (directory / "trial.json").read_text() == original
