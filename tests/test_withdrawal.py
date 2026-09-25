"""Authored provenance counterexamples, not live campaign evidence."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_procedures import authored_verification
from test_procedures import evidence as evidence

from autonomy_lab.withdrawal import binding_checks, episode_evidence, finished_after_release


def authored_binding():
    receipt = {'version': 'authored-version', 'eligible': True,
               'definition': {'variant': 'runbook_fallback', 'source_files': {
                   'src/autonomy_lab/authored.py': 'hash', 'infra/toolchain.json': 'authored-toolchain'}}}
    pin = {'episode': 'authored-episode', 'version': receipt['version'], 'revision': 1}
    selected = {**pin, 'variant': 'runbook_fallback'}
    admission = {
        'state': [{'id': 1, 'revision': 2, 'active': None, 'active_revision': None}],
        'versions': [{'version': receipt['version'], 'withdrawn': 1,
                      'definition': json.dumps(receipt['definition'], sort_keys=True)}],
        'decisions': [{'revision': 1, 'kind': 'promoted', 'receipt': json.dumps(receipt, sort_keys=True)},
                      {'revision': 2, 'kind': 'withdrawn', 'receipt': json.dumps({'version': receipt['version']}, sort_keys=True)}],
        'pins': [pin], 'refusals': [],
    }
    def stamp(t):
        return datetime.fromtimestamp(t, UTC).isoformat()
    return {
        'card': {'source_sha256': dict(receipt['definition']['source_files']), 'operations': [
            {'operation_id': 'authored-operation', 'created_at': stamp(103)}]},
        'record': {'admission': {'revision': 1, 'kind': 'promoted', 'version': receipt['version']},
                   'withdrawal': {'requested_at': 110,
                                  'decision': {'revision': 2, 'kind': 'withdrawn', 'version': receipt['version']}}},
        'admission': admission, 'receipt': receipt,
        'episodes': [{'id': pin['episode'], 'attempt': {'started_at': 100}, 'procedure': {**selected, 'at': 101},
                      'evidence': [{'timestamp': stamp(102)}]}],
        'bindings': [{'operation_id': 'authored-operation', 'pin': selected, 'at': 104}],
    }


def test_authored_original_pin_and_operation_survive_terminal_withdrawal():
    assert all(binding_checks(**authored_binding()).values())


@pytest.mark.parametrize('defect', [
    'old_source', 'missing_source', 'partial_source', 'ineligible', 'active_after_withdrawal', 'forgotten_withdrawal',
    'erased_receipt', 'different_receipt', 'wrong_withdrawal', 'different_activation', 'missing_pin',
    'new_version', 'late_pin', 'tool_before_pin', 'empty_evidence', 'wrong_variant',
    'missing_binding', 'different_operation', 'relabelled_binding', 'binding_before_pin', 'duplicate_binding',
])
def test_provenance_contradictions_cannot_pass(defect):
    data = authored_binding()
    if defect == 'old_source':
        data['card']['source_sha256']['src/autonomy_lab/authored.py'] = 'changed'
    elif defect == 'missing_source':
        data['card']['source_sha256'] = {}
    elif defect == 'partial_source':
        data['card']['source_sha256'].pop('infra/toolchain.json')
    elif defect == 'ineligible':
        data['receipt']['eligible'] = False
    elif defect == 'active_after_withdrawal':
        data['admission']['state'][0]['active'] = 'authored-version'
    elif defect == 'forgotten_withdrawal':
        data['admission']['versions'][0]['withdrawn'] = 0
    elif defect == 'erased_receipt':
        data['admission']['decisions'].pop()
    elif defect == 'different_receipt':
        data['admission']['decisions'][0]['receipt'] = '{}'
    elif defect == 'wrong_withdrawal':
        data['record']['withdrawal']['decision']['version'] = 'other'
    elif defect == 'different_activation':
        data['episodes'][0]['procedure']['revision'] = 2
    elif defect == 'missing_pin':
        data['admission']['pins'] = []
    elif defect == 'new_version':
        data['episodes'][0]['procedure']['version'] = 'other'
    elif defect == 'late_pin':
        data['episodes'][0]['procedure']['at'] = 111
    elif defect == 'tool_before_pin':
        data['episodes'][0]['procedure']['at'] = 102.5
    elif defect == 'empty_evidence':
        data['episodes'][0]['evidence'] = []
    elif defect == 'wrong_variant':
        data['episodes'][0]['procedure']['variant'] = 'runbook'
    elif defect == 'missing_binding':
        data['bindings'] = []
    elif defect == 'different_operation':
        data['bindings'][0]['operation_id'] = 'replacement-operation'
    elif defect == 'relabelled_binding':
        data['bindings'][0]['pin']['revision'] = 2
    elif defect == 'binding_before_pin':
        data['bindings'][0]['at'] = 100
    elif defect == 'duplicate_binding':
        data['bindings'].append(data['bindings'][0])
    assert not all(binding_checks(**data).values())


@pytest.mark.parametrize('defect', [None, 'stale_claim', 'different_claim', 'uncommitted', 'missing_finish', 'late_evidence'])
def test_drain_claim_requires_the_actual_post_release_terminal_evidence(defect):
    claim = {'kind': 'claim', 'outcome': 'healthy'}
    episode = {'outcome': {'finished_at': 120, 'claim': dict(claim)},
               'evidence': [{'source': 'finish', 'payload': dict(claim),
                             'timestamp': datetime.fromtimestamp(115, UTC).isoformat()}]}
    if defect == 'stale_claim':
        episode['evidence'][0]['timestamp'] = datetime.fromtimestamp(105, UTC).isoformat()
    elif defect == 'different_claim':
        episode['evidence'][0]['payload']['outcome'] = 'escalated'
    elif defect == 'uncommitted':
        episode['outcome'] = None
    elif defect == 'missing_finish':
        episode['evidence'][0]['source'] = 'verify_recovery'
    elif defect == 'late_evidence':
        episode['evidence'][0]['timestamp'] = datetime.fromtimestamp(121, UTC).isoformat()
    assert finished_after_release(episode, 110) is (defect is None)


@pytest.mark.parametrize('case', ['healthy', 'uncertain'])
@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_early_failure_exports_after_teardown_even_when_cleanup_fails(tmp_path, monkeypatch, case, cleanup_fails):
    import importlib

    from autonomy_lab.harness import save
    from autonomy_lab.withdrawal import declaration

    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'scripts'))
    checker = importlib.import_module('check_withdrawal' if case == 'healthy' else 'check_ambiguity')
    directory = tmp_path / 'campaign'
    (directory / 'workers/operator-authored').mkdir(parents=True)
    save(directory / 'window.json', {'start': 1000, 'end': 1120})
    save(directory / 'owner.json', {'run_id': 'authored'})
    save(directory / 'environment.json', {'cluster': 'autolab-00000000', 'status': 'running'})
    order = []

    def await_file(path, deadline):
        if path.name == 'window.json':
            return json.loads(path.read_text())
        raise TimeoutError('authored controller failure')

    def finalize(*args):
        order.append('cleanup')
        if cleanup_fails:
            raise RuntimeError('authored cleanup failure')

    def export(gate):
        assert order == ['cleanup']
        order.append('export')
        return {'status': 'failed'}

    monkeypatch.setattr(checker.subprocess, 'Popen', Mock())
    monkeypatch.setattr(checker, 'await_file', await_file)
    monkeypatch.setattr(checker, 'wait_until', Mock(side_effect=TimeoutError('authored controller failure')))
    monkeypatch.setattr(checker, 'finalize_gate', finalize)
    monkeypatch.setattr(checker, 'scorecard', lambda _: {})
    spec = declaration(case, 'authored')
    with pytest.raises(RuntimeError if cleanup_fails else TimeoutError):
        if case == 'healthy':
            monkeypatch.setattr(checker, 'captured_evaluate', export)
            checker.healthy_case(tmp_path, spec, tmp_path / 'authored')
        else:
            checker.run_case(tmp_path, spec, evaluator=export)
    assert order == ['cleanup', 'export']
    result = json.loads((tmp_path / 'result.json').read_text())
    assert result['status'] == 'failed' and result['error_type'] == 'TimeoutError'


@pytest.mark.parametrize('artifact', ['evidence', 'outcome', 'operation', 'attempt_only'])
def test_unpinned_execution_cannot_disappear_from_the_audit(tmp_path, artifact):
    from autonomy_lab.harness import save

    path = tmp_path / 'workers/operator-authored/episode-authored'
    path.mkdir(parents=True)
    episode = {'id': path.name, 'outcome': None}
    if artifact == 'evidence':
        (path / 'evidence.jsonl').write_text('{}\n')
    elif artifact == 'outcome':
        episode['outcome'] = {'claim': {'outcome': 'healthy'}}
    elif artifact == 'operation':
        save(path / 'operation.json', {'operation_id': 'authored'})
    episodes, _, unpinned = episode_evidence(tmp_path, [{'id': 'operator-authored', 'episodes': [episode]}])
    assert episodes == []
    assert unpinned == ([] if artifact == 'attempt_only' else [path.name])


@pytest.mark.parametrize('study', ['withdrawal', 'ambiguity'])
@pytest.mark.parametrize('error', [KeyboardInterrupt, SystemExit])
def test_aborted_study_closes_ledger_and_distinguishes_attempted_case(tmp_path, monkeypatch, study, error):
    import importlib

    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'scripts'))
    checker = importlib.import_module('check_' + study)
    monkeypatch.setattr(checker, 'ROOT', tmp_path)
    monkeypatch.setattr(checker, 'healthy_case' if study == 'withdrawal' else 'run_case', Mock(side_effect=error))
    with pytest.raises(error):
        if study == 'withdrawal':
            checker.run(tmp_path / 'artifacts/authored-calibration')
        else:
            checker.run()
    result = json.loads(next((tmp_path / 'artifacts').glob('*-gate-*/result.json')).read_text())
    assert result['status'] == 'failed' and 'finished_at' in result
    assert result['error_type'] == error.__name__
    first, second = checker.CASES
    assert result['cases'][first] == {'status': 'failed', 'error_type': error.__name__}
    assert result['cases'][second] == {'status': 'unrun'}


@pytest.mark.parametrize('defect', [None, 'unpinned_execution', 'stale_terminal_claim'])
def test_full_healthy_evaluator_reproduces_authored_evidence(evidence, tmp_path, defect):
    from autonomy_lab.campaign import Contract
    from autonomy_lab.harness import save
    from autonomy_lab.kubernetes import ROOT
    from autonomy_lab.procedures import Registry
    from autonomy_lab.procedures import evaluate as calibration_receipt
    from autonomy_lab.withdrawal import declaration, evaluate

    gate = tmp_path / 'authored-study/healthy'
    directory = gate / 'campaign'
    directory.mkdir(parents=True)
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        save(path, value)
    def stamp(t):
        return datetime.fromtimestamp(t, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    spec = declaration('healthy', evidence.name)
    write(gate / 'declaration.json', spec)
    contract = Contract.model_validate(json.loads((ROOT / 'scenarios/campaign-withdrawal-healthy.json').read_text())).model_dump()
    write(directory / 'contract.json', contract)
    write(directory / 'window.json', {'start': 1000, 'end': 1120})
    sources = calibration_receipt(evidence, 'runbook_fallback')['definition']['source_files']
    write(directory / 'source.json', {p: v for p, v in sources.items() if p.startswith('src/autonomy_lab/') or p in {
        'fixtures/expectations.json', 'fixtures/database.sql', 'infra/toolchain.json'}})
    identities = {f'authored-resource-{i}': f'authored-uid-{i}' for i in range(11)}
    write(directory / 'identities-before.json', identities)
    write(directory / 'identities-after.json', identities)
    write(directory / 'finished.json', {})
    write(directory / 'finalization.json', {'status': 'finished'})
    write(directory / 'cleanup.json', {'status': 'deleted'})
    registry = Registry(directory / 'admission.sqlite')
    promotion = registry.promote(evidence, 'runbook_fallback', expected_revision=0)
    pin = registry.start_episode('episode-authored')
    withdrawal = registry.withdraw(expected_revision=1)
    with pytest.raises(ValueError):
        registry.start_episode('episode-refused')
    write(gate / 'record.json', {'initial_worker': 'operator-authored', 'admission': promotion,
        'withdrawal': {'requested_at': 1020, 'finished_at': 1020.5, 'decision': withdrawal}, 'released_at': 1021})
    worker = directory / 'workers/operator-authored'
    write(worker / 'finished.json', {'at': 1028})
    write(worker / 'finish-barrier.json', {'episode': pin['episode'], 'at': 1002})
    write(worker / 'escalation.json', {'reason': 'procedure_admission_refused', 'detail': 'No admitted procedure',
                                      'episode': 'episode-refused', 'at': 1027})
    episode = worker / pin['episode']
    write(episode / 'attempt.json', {'started_at': 1000})
    write(episode / 'procedure.json', {**pin, 'at': 1001})
    claim = {'kind': 'claim', 'outcome': 'healthy'}
    write(episode / 'outcome.json', {'claim': claim, 'finished_at': 1022})
    (episode / 'evidence.jsonl').write_text(json.dumps({'source': 'finish', 'payload': claim,
        'timestamp': stamp(1010 if defect == 'stale_terminal_claim' else 1021.5)}) + '\n')
    write(worker / 'episode-refused/attempt.json', {'started_at': 1027})
    if defect == 'unpinned_execution':
        (worker / 'episode-refused/evidence.jsonl').write_text('{}\n')
    (directory / 'workers/observer-authored').mkdir()
    for slot in range(12):
        verification = authored_verification()
        verification['window_seconds'] = 1
        verification['probes'][1]['offset_seconds'] = 1
        start = 1000 + slot * 10
        write(directory / f'samples/{slot:04d}.json', {'slot': slot, 'scheduled_at': start,
            'started_at': start, 'finished_at': start + 2, 'verification': verification})
    write(gate / 'server-audit.json', {'collection_closed': True, 'malformed_lines': 0, 'events': [{
        'auditID': 'authored-read', 'verb': 'get', 'requestReceivedTimestamp': stamp(1001),
        'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services'}}]})
    result = evaluate(gate)
    assert result['status'] == ('passed' if defect is None else 'failed'), result['checks']
    assert result == evaluate(gate)
