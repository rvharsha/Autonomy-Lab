"""Authored lifecycle failure tests, not cloud experiment observations."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from autonomy_lab import experiments
from autonomy_lab.harness import save

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('service_experiment', ROOT / 'scripts/service_experiment.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    monkeypatch.setattr(service, 'release_manifest', lambda config: {'files': {'source': 'frozen'}})
    monkeypatch.setattr(service, 'process_identity', lambda pid: 'test-process')
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/service_experiment.py').write_text('# Authored source identity fixture\n')
    config = {'runtime': 'isolated-docker', 'scenarios': ['healthy', 'routing'],
              'variants': ['runbook_fallback'], 'repetitions': 2, 'window_seconds': 30,
              'expected_behavior': {'healthy': 'healthy', 'routing': 'repair'}}
    manifest = tmp_path / 'manifest.yaml'
    manifest.write_text(yaml.safe_dump(config))
    directory = service.prepare(manifest)
    record, run_dir = service.load_job(directory)
    monkeypatch.setenv('SERVICE_RESULT', 'signal')
    return directory, record, run_dir


def attempted(run_dir, plan, index=1, *, success=None):
    path = run_dir / f'trial-{index:03d}'
    path.mkdir(parents=True)
    value = {**plan[index - 1], 'status': 'running', 'private_thinking': 'NEVER_EXPORT'}
    if success is not None:
        value.update(status='recorded', score={'task_success': success})
    save(path / 'trial.json', value)
    return value


def test_restart_cannot_reenter_experiment_even_if_first_invocation_failed(job, monkeypatch):
    directory, _, _ = job
    entered = []
    def fail(*args, **kwargs):
        entered.append(kwargs['run_id'])
        raise RuntimeError('Interrupted attempt')
    monkeypatch.setattr(service, 'run_experiment', fail)
    with pytest.raises(RuntimeError):
        service.run(directory)
    original = (directory / 'controller-result.json').read_bytes()
    with pytest.raises(FileExistsError):
        service.run(directory)
    assert len(entered) == 1
    assert (directory / 'controller-result.json').read_bytes() == original


def test_torn_launch_claim_fails_closed_before_any_work(job, monkeypatch):
    directory, _, _ = job
    (directory / 'launch-claim.json').touch()
    monkeypatch.setattr(service, 'run_experiment', lambda *a, **k: pytest.fail('Replay'))
    with pytest.raises(FileExistsError):
        service.run(directory)


def test_partial_worker_success_cannot_be_promoted_to_final_result(job):
    _, record, run_dir = job
    first = attempted(run_dir, record['plan'], success=True)
    save(run_dir / 'results.json', [first])
    attempted(run_dir, record['plan'], 2, success=True)
    original = (run_dir / 'trial-002/trial.json').read_bytes()
    report = service.accounting(record, run_dir)
    assert (report['planned'], report['controller_recorded'], report['attempted'],
            report['unassessed_attempts'], report['unrun']) == (4, 1, 2, 1, 2)
    assert report['trials'][1]['task_success'] is None
    assert report['trials'][1]['audit_assessed'] is None
    assert report['trials'][2]['disposition'] == 'unrun'
    assert not report['controller_final_accounting_available']
    assert (run_dir / 'trial-002/trial.json').read_bytes() == original
    assert 'NEVER_EXPORT' not in json.dumps(report)


def test_stop_before_manifest_accounts_all_unrun(job):
    _, record, run_dir = job
    report = service.accounting(record, run_dir)
    assert report['unrun'] == 4 and report['attempted'] == 0


@pytest.mark.parametrize('fault', ['out_of_order', 'hole', 'wrong_worker', 'running_result'])
def test_rejects_conflicting_evidence_instead_of_inventing_accounting(job, fault):
    _, record, run_dir = job
    value = attempted(run_dir, record['plan'], 2 if fault == 'hole' else 1)
    if fault == 'wrong_worker':
        value['variant'] = 'basic'
        save(run_dir / 'trial-001/trial.json', value)
    elif fault == 'out_of_order':
        save(run_dir / 'results.json', [{**record['plan'][1], 'status': 'recorded'}])
    elif fault == 'running_result':
        save(run_dir / 'results.json', [value])
    with pytest.raises(ValueError):
        service.accounting(record, run_dir)


def test_accounting_error_does_not_skip_cleanup_and_receipt_survives_restart(job, monkeypatch):
    directory, record, run_dir = job
    run_dir.mkdir()
    save(run_dir / 'service-owner.json', {'owner_token': record['owner_token']})
    save(run_dir / 'environment.json', {'cluster': 'autolab-' + record['run_id']})
    (run_dir / 'results.json').write_text('torn')
    cleaned = []
    def cleanup(path, lease):
        cleaned.append(lease['cluster'])
        save(path / 'janitor-result.json', {'status': 'deleted'})
    monkeypatch.setattr(service, 'cleanup', cleanup)
    monkeypatch.setattr(service, 'remaining_resources', lambda *a: {'cluster_nodes': [], 'registered_agents': []})
    result = service.finalize(directory)
    assert result['status'] == 'failed' and result['cleanup'] == 'deleted'
    assert result['errors'][0]['stage'] == 'accounting'
    assert result['credential_removed']
    original = (directory / 'post-stop.json').read_bytes()
    assert service.finalize(directory) == result
    assert len(cleaned) == 1 and (directory / 'post-stop.json').read_bytes() == original


def test_alive_controller_blocks_cleanup(job, monkeypatch):
    directory, _, _ = job
    save(directory / 'launch-claim.json', {'pid': 123, 'identity': 'original'})
    monkeypatch.setattr(service, 'process_identity', lambda pid: 'original')
    monkeypatch.setattr(service, 'cleanup', lambda *a: pytest.fail('Killed live job'))
    with pytest.raises(RuntimeError, match='still alive'):
        service.finalize(directory)


def test_finalize_requires_host_post_stop_phase(job, monkeypatch):
    directory, _, _ = job
    monkeypatch.delenv('SERVICE_RESULT')
    with pytest.raises(RuntimeError, match='post-stop'):
        service.finalize(directory)


def test_cleanup_failure_stays_failed(job, monkeypatch):
    directory, _, _ = job
    monkeypatch.setattr(service, 'remaining_resources', lambda *a: {'cluster_nodes': ['owned-node'], 'registered_agents': []})
    result = service.finalize(directory)
    assert result['status'] == 'failed' and result['cleanup'] == 'failed'
    assert result['remaining']['cluster_nodes'] == ['owned-node']


def test_credential_removed_before_cleanup_can_block(job, monkeypatch, tmp_path):
    directory, record, run_dir = job
    run_dir.mkdir()
    save(run_dir / 'service-owner.json', {'owner_token': record['owner_token']})
    save(run_dir / 'environment.json', {'cluster': 'autolab-' + record['run_id']})
    credential = tmp_path / 'authored-credential-fixture'
    credential.write_text('authored test input; not a live credential')
    monkeypatch.setattr(service, 'credential_path', lambda value: credential)
    def blocked(*args):
        assert not credential.exists()
        assert service.read(directory / 'post-stop-started.json')['credential_removed']
        raise TimeoutError('Authored cleanup stall')
    monkeypatch.setattr(service, 'cleanup', blocked)
    result = service.finalize(directory)
    assert result['status'] == 'failed' and result['credential_removed']


def test_colliding_preexisting_run_is_never_adopted_or_deleted(job, monkeypatch):
    directory, record, run_dir = job
    run_dir.mkdir()
    save(run_dir / 'environment.json', {'cluster': 'autolab-' + record['run_id']})
    monkeypatch.setattr(service, 'cleanup', lambda *a: pytest.fail('Deleted unowned environment'))
    result = service.finalize(directory)
    assert result['status'] == 'failed' and result['cleanup'] == 'unknown'
    assert result['errors'][0]['stage'] == 'ownership'
    assert result['credential_removed']


def test_wrapper_source_is_frozen_at_preparation(job, monkeypatch):
    directory, _, _ = job
    (service.ROOT / 'scripts/service_experiment.py').write_text('changed wrapper')
    monkeypatch.setattr(service, 'run_experiment', lambda *a, **k: pytest.fail('Changed source executed'))
    with pytest.raises(ValueError, match='Source changed'):
        service.run(directory)


@pytest.mark.parametrize('path', ['~/Dev/.env', '/tmp/provider.env', '/run/autonomy-lab/../other/provider.env', '/run/autonomy-lab/keys'])
def test_rejects_nontransient_credentials(path):
    with pytest.raises(ValueError):
        service.credential_path(path)


@pytest.mark.parametrize('run_id', ['../existing', '1234567', 'not-hex!', 12345678])
def test_invalid_reserved_identity_rejected_before_runtime(job, run_id):
    _, record, _ = job
    with pytest.raises(ValueError, match='identity'):
        experiments.run_experiment(record['config'], run_id=run_id)


def test_reserved_identity_passes_through_freeze(job, monkeypatch):
    _, record, _ = job
    from autonomy_lab import frozen_experiment
    seen = []
    monkeypatch.setattr(frozen_experiment, 'freeze', lambda *a, **k: seen.append(k['run_id']))
    experiments.run_experiment(record['config'], run_id=record['run_id'])
    assert seen == [record['run_id']]
