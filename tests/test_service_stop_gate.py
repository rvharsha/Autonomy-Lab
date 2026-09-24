"""Authored checks of gate assertions; real Linux runs supply lifecycle evidence."""

import copy
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from autonomy_lab.experiments import planned_trials, validate_config
from autonomy_lab.harness import save

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


service = load('service_experiment')
with patch.dict(sys.modules, {'service_experiment': service}):
    gate = load('check_service_stop')


@pytest.fixture
def mixed(tmp_path):
    plan = gate.gate_plan(True)
    first = {**plan[0], 'status': 'recorded', 'score': {'task_success': True},
             'execution_audit': {'status': 'assessed', 'successful_unmatched_mutations': 0},
             'protected_state_damage': False}
    save(tmp_path / 'results.json', [first])
    (tmp_path / 'trial-001').mkdir()
    save(tmp_path / 'trial-001/trial.json', first)
    (tmp_path / 'trial-002').mkdir()
    # A worker-written success does not authorize the gate to credit trial 2.
    save(tmp_path / 'trial-002/trial.json', {**first, **plan[1]})
    return tmp_path, plan


@pytest.mark.parametrize('committed', [False, True])
def test_gate_manifest_matches_exact_declared_order(committed):
    filename = 'service-mixed-state-gate.yaml' if committed else 'service-stop-gate.yaml'
    config = yaml.safe_load((ROOT / 'scenarios' / filename).read_text())
    validate_config(config)
    assert planned_trials(config) == gate.gate_plan(committed)
    assert config['window_seconds'] == 30
    assert config['variants'] == ['runbook_fallback']


def test_mixed_gate_preserves_prefix_and_rejects_uncommitted_worker_success(mixed):
    root, plan = mixed
    before = gate.committed_evidence(root, plan, 1)
    accounting = service.accounting({'plan': plan}, root)
    gate.check_accounting(accounting, plan, 1)
    assert set(before) == {'results.json', 'trial-001/trial.json'}
    assert accounting['trials'][1]['task_success'] is None
    assert accounting['trials'][2]['disposition'] == 'unrun'
    assert gate.committed_evidence(root, plan, 1) == before


@pytest.mark.parametrize('fault', ['uncommitted', 'advanced', 'failed', 'unknown_audit',
                                  'unmatched_mutation', 'protected_damage', 'identity', 'missing_evidence'])
def test_trigger_refuses_wrong_or_failed_committed_prefix(mixed, fault):
    root, plan = mixed
    results = json.loads((root / 'results.json').read_text())
    if fault == 'uncommitted':
        results = []
    elif fault == 'advanced':
        results += [{**results[0], **plan[1]}]
    elif fault == 'failed':
        results[0]['score']['task_success'] = False
    elif fault == 'unknown_audit':
        results[0]['execution_audit']['status'] = 'unassessed'
    elif fault == 'unmatched_mutation':
        results[0]['execution_audit']['successful_unmatched_mutations'] = 1
    elif fault == 'protected_damage':
        results[0]['protected_state_damage'] = True
    elif fault == 'identity':
        results[0]['repetition'] = 1
    else:
        (root / 'trial-001/trial.json').unlink()
    save(root / 'results.json', results)
    with pytest.raises(RuntimeError):
        gate.committed_evidence(root, plan, 1)


@pytest.mark.parametrize('fault', ['lost_prefix', 'credit_interrupted', 'credit_unrun',
                                  'lost_audit', 'swapped_identity', 'missing_row', 'wrong_disposition'])
def test_gate_rejects_corrupted_recovery_accounting(mixed, fault):
    root, plan = mixed
    report = copy.deepcopy(service.accounting({'plan': plan}, root))
    if fault == 'lost_prefix':
        report['controller_recorded'] = 0
    elif fault == 'credit_interrupted':
        report['trials'][1]['task_success'] = True
    elif fault == 'credit_unrun':
        report['trials'][2]['audit_assessed'] = False
    elif fault == 'lost_audit':
        report['trials'][0]['audit_assessed'] = False
    elif fault == 'swapped_identity':
        report['trials'][0]['repetition'] = 1
    elif fault == 'missing_row':
        report['trials'].pop()
    else:
        report['trials'][1]['disposition'] = 'controller_recorded'
    with pytest.raises(RuntimeError):
        gate.check_accounting(report, plan, 1)


def test_original_zero_committed_gate_still_checks_unknown_and_unrun(tmp_path):
    plan = gate.gate_plan(False)
    (tmp_path / 'trial-001').mkdir()
    save(tmp_path / 'trial-001/trial.json', {**plan[0], 'status': 'running'})
    assert gate.committed_evidence(tmp_path, plan, 0) == {}
    gate.check_accounting(service.accounting({'plan': plan}, tmp_path), plan, 0)


@pytest.mark.parametrize('kind', ['absolute', 'traversal', 'file_symlink', 'directory_symlink',
                                 'root_symlink', 'fifo'])
def test_administrator_evidence_reads_reject_escape_and_nonregular_files(tmp_path, kind):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret').write_text('AUTHORED_PRIVATE_FIXTURE')
    root = tmp_path / 'run'
    root.mkdir()
    name = 'secret'
    if kind == 'absolute':
        name = str(outside / 'secret')
    elif kind == 'traversal':
        name = '../outside/secret'
    elif kind == 'file_symlink':
        (root / name).symlink_to(outside / 'secret')
    elif kind == 'directory_symlink':
        (root / 'alias').symlink_to(outside, target_is_directory=True)
        name = 'alias/secret'
    elif kind == 'root_symlink':
        (root / 'alias').symlink_to(outside, target_is_directory=True)
        root = root / 'alias'
    else:
        os.mkfifo(root / name)
    with pytest.raises((ValueError, OSError)):
        gate.evidence_bytes(root, name)


def test_regular_nested_evidence_has_exact_content_digest(tmp_path):
    path = tmp_path / 'trial-001/trial.json'
    path.parent.mkdir()
    path.write_bytes(b'{"status":"recorded"}\n')
    assert gate.evidence_bytes(tmp_path, 'trial-001/trial.json') == path.read_bytes()
    assert gate.evidence_digest(tmp_path, 'trial-001/trial.json') == service.digest(path)


@pytest.mark.parametrize('uid,mode', [(1001, 0o700), (0, 0o770), (0, 0o707), (0, 0o777)])
def test_privileged_receipts_reject_replaceable_ancestors(uid, mode):
    with pytest.raises(PermissionError):
        gate.require_trusted_directory(SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR | mode))


def test_privileged_receipts_accept_root_owned_nonwritable_ancestors():
    gate.require_trusted_directory(SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755))
    with pytest.raises(PermissionError):
        gate.require_trusted_directory(SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o600))


def test_receipt_path_is_outside_checkout_and_all_components_are_nofollow():
    with patch.object(gate.os, 'open', side_effect=range(10, 15)) as opened, \
            patch.object(gate.os, 'fstat', return_value=SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)), \
            patch.object(gate.os, 'mkdir') as mkdir, patch.object(gate.os, 'close'):
        directory = gate.receipt_directory()
    assert directory.parent == Path('/var/lib/autonomy-lab/service-gates')
    assert all(call.args[1] & os.O_NOFOLLOW for call in opened.call_args_list)
    assert [call.args[0] for call in opened.call_args_list] == ['/', 'var', 'lib', 'autonomy-lab', 'service-gates']
    assert mkdir.call_args.kwargs == {'mode': 0o700, 'dir_fd': 14}
