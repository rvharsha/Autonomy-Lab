"""Authored admission-boundary fixtures, not workload or benchmark evidence."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from autonomy_lab import procedures as p
from autonomy_lab.audit import assess
from autonomy_lab.experiments import planned_trials, release_manifest
from autonomy_lab.harness import save
from autonomy_lab.scoring import score_trial
from autonomy_lab.verifier import load_expectations


def authored_verification():
    expectations = load_expectations()
    snapshot = {
        'quote_control': {'kind': 'response', 'status_code': 200},
        'inventory_control': {'kind': 'response', 'status_code': 200},
        'database': {'kind': 'rows', 'rows': expectations['products']},
        'service': {'kind': 'resource', 'resource': {'metadata': {'name': 'inventory'}, 'spec': {
            'selector': {'app': 'inventory'},
            'ports': [{'name': 'http', 'port': 80, 'protocol': 'TCP', 'targetPort': 8080}]}}},
        'quotes': [{'case_id': case['id'], 'kind': 'response', 'status_code': case['status_code'],
                    'body': case.get('body')} for case in expectations['quotes']],
    }
    return {'verdict': 'verified_success', 'reasons': [], 'window_seconds': 30,
            'expectation_version': expectations['version'],
            'counts': {'total': 2, 'verified_success': 2, 'verified_failure': 0, 'indeterminate': 0},
            'probes': [{'index': i, 'observations': copy.deepcopy(snapshot), 'offset_seconds': offset,
                        'verdict': 'verified_success', 'reasons': []} for i, offset in enumerate([0, 30])]}


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    # A reduced protocol keeps these corruption tests small. The live gate uses
    # the complete immutable eight-scenario protocol, with no scorer mocks.
    config = p.calibration_config()
    config['scenarios'] = ['healthy', 'observer_outage']
    config['expected_behavior'] = {s: 'healthy' for s in config['scenarios']}
    monkeypatch.setattr(p, 'calibration_config', lambda: copy.deepcopy(config))
    declared = {**config, 'agent_image_id': 'sha256:' + 'a' * 64}
    release = release_manifest(declared)
    plan = planned_trials(config)
    run = tmp_path / 'authored'
    run.mkdir()
    save(run / 'release.json', release)
    save(run / 'manifest.json', {**declared, 'planned_trials': plan, 'frozen_at': 'authored'})
    save(run / 'cleanup.json', {'status': 'deleted'})
    save(run / 'accounting.json', {'planned': len(plan), 'recorded': len(plan),
                                   'status_counts': {'recorded': len(plan)}, 'unrun': []})
    results = []
    for index, item in enumerate(plan, 1):
        trial = run / f'trial-{index:03d}'
        trial.mkdir()
        verification = authored_verification()
        claim = {'outcome': 'healthy', 'reason': 'Authored test', 'evidence_ids': ['check']}
        if item['variant'] == 'runbook' and item['scenario'] == 'observer_outage':
            claim['outcome'] = 'escalated'
        observations = [
            {'observation_id': 'check', 'run_id': str(index), 'timestamp': '2026-09-25T00:00:01+00:00',
             'source': 'verify_recovery', 'payload': verification},
            {'observation_id': 'finish', 'run_id': str(index), 'timestamp': '2026-09-25T00:00:02+00:00',
             'source': 'finish', 'payload': claim},
        ]
        if item['variant'] == 'no_agent':
            claim, observations = None, []
        start, end = '2026-09-25T00:00:00+00:00', '2026-09-25T00:00:03+00:00'
        audit = assess([{'auditID': 'authored-read', 'verb': 'get',
                         'objectRef': {'namespace': 'autonomy-lab'}, 'requestReceivedTimestamp': start}],
                       [], started_at=start, finished_at=end)
        result = {'trial_id': str(index), 'scenario': item['scenario'], 'variant': item['variant'],
                  'status': 'recorded', 'agent': {'terminal': claim}, 'started_at': start, 'finished_at': end,
                  'protected_state_damage': [], 'execution_audit': {k: v for k, v in audit.items() if k != 'events'},
                  'score': score_trial('healthy', item['variant'], claim, verification, [], observations)}
        save(trial / 'trial.json', result)
        save(trial / 'worker-request.json', {'release_id': release['release_id'], 'config': declared,
                                            'scenario': item['scenario'], 'variant': item['variant']})
        save(trial / 'operations.json', [])
        save(trial / 'final-verification.json', verification)
        save(trial / 'server-audit.json', audit)
        (trial / 'evidence.jsonl').write_text(''.join(json.dumps(o) + '\n' for o in observations))
        results.append({**item, **result})
    save(run / 'results.json', results)
    return run


def test_actual_protocol_preserves_full_regression_and_controls():
    config = p.calibration_config()
    assert len(config['scenarios']) == 8
    assert set(config['variants']) == {'runbook', 'runbook_fallback', 'no_agent'}
    assert len(planned_trials(config)) == 24
    assert config['window_seconds'] == 30


def test_admission_uses_reproduced_behavior_and_distinct_versions(evidence):
    original = p.evaluate(evidence, 'runbook')
    fallback = p.evaluate(evidence, 'runbook_fallback')
    assert original['eligible'] is False and fallback['eligible'] is True
    assert original['version'] != fallback['version']
    assert {o['scenario'] for o in original['outcomes'] if not o['task_success']} == {'observer_outage'}
    assert fallback == p.evaluate(evidence, 'runbook_fallback')
    assert 'trial-001/final-verification.json' in fallback['evidence_sha256']


@pytest.mark.parametrize('corruption', ['source', 'protocol', 'image', 'manifest', 'missing', 'unrun',
                                      'reorder', 'duplicate', 'cleanup', 'summary', 'score', 'audit',
                                      'worker', 'protected', 'verification', 'target_port', 'raw_probe',
                                      'short_window', 'empty_probes'])
def test_corrupt_evidence_cannot_promote(evidence, tmp_path, corruption):
    def change(name, operation):
        path = evidence / name
        value = json.loads(path.read_text())
        operation(value)
        save(path, value)

    if corruption == 'source':
        change('release.json', lambda r: r['files'].update({'src/autonomy_lab/runbook.py': 'different'}))
    elif corruption == 'protocol':
        change('release.json', lambda r: r['configuration'].update(window_seconds=1))
    elif corruption == 'image':
        change('release.json', lambda r: r['configuration'].pop('agent_image_id'))
    elif corruption == 'manifest':
        change('manifest.json', lambda r: r['planned_trials'].pop())
    elif corruption == 'missing':
        (evidence / 'trial-001/server-audit.json').unlink()
    elif corruption == 'unrun':
        change('accounting.json', lambda r: r.update(unrun=[{'scenario': 'healthy'}]))
    elif corruption == 'reorder':
        change('results.json', lambda r: r.reverse())
    elif corruption == 'duplicate':
        change('results.json', lambda r: r[1].update(trial_id=r[0]['trial_id']))
    elif corruption == 'cleanup':
        change('cleanup.json', lambda r: r.update(status='failed'))
    elif corruption in {'summary', 'score'}:
        change('results.json', lambda r: r[0]['score'].update(task_success='true'))
        if corruption == 'score':
            change('trial-001/trial.json', lambda r: r['score'].update(task_success='true'))
    elif corruption == 'audit':
        change('trial-001/server-audit.json', lambda r: r.update(malformed_lines=1))
    elif corruption == 'worker':
        change('trial-001/worker-request.json', lambda r: r.update(release_id='other'))
    elif corruption == 'protected':
        change('trial-001/final-verification.json', lambda r: r.update(reasons=['protected rows differ']))
    elif corruption == 'target_port':
        change('trial-001/final-verification.json',
               lambda r: r.update(reasons=['service: protected targetPort differs (expected 8080)']))
    elif corruption == 'raw_probe':
        change('trial-001/final-verification.json',
               lambda r: r['probes'][0]['observations']['database'].update(rows=[]))
    elif corruption == 'short_window':
        change('trial-001/final-verification.json', lambda r: r['probes'][-1].update(offset_seconds=1))
    elif corruption == 'empty_probes':
        change('trial-001/final-verification.json', lambda r: r.update(probes=[]))
    else:
        change('trial-001/final-verification.json', lambda r: r.update(verdict='indeterminate'))
    registry = p.Registry(tmp_path / 'registry.sqlite')
    with pytest.raises((p.Refused, OSError)):
        registry.promote(evidence, 'runbook_fallback', expected_revision=0)
    assert registry.state() == {'revision': 0, 'active': None}
    with closing(sqlite3.connect(registry.path)) as db:
        refusals = db.execute('SELECT details FROM refusals').fetchall()
    assert len(refusals) == 1
    assert json.loads(refusals[0][0])['expected_revision'] == 0
    with pytest.raises(p.Refused):
        registry.pin('unadmitted')


def test_withdrawal_is_durable_and_does_not_rebind_existing_work(evidence, tmp_path):
    path = tmp_path / 'registry.sqlite'
    registry = p.Registry(path)
    assert registry.promote(evidence, 'runbook', expected_revision=0)['kind'] == 'rejected'
    assert registry.state() == {'revision': 1, 'active': None}
    accepted = registry.promote(evidence, 'runbook_fallback', expected_revision=1)
    assert accepted['kind'] == 'promoted'
    original = registry.pin('in-flight')
    assert original['version'] == accepted['version']
    registry = p.Registry(path)
    with pytest.raises(p.Refused, match='Stale'):
        registry.withdraw(expected_revision=1)
    assert registry.pin('in-flight') == original
    assert registry.withdraw(expected_revision=2)['revision'] == 3
    registry = p.Registry(path)
    assert registry.pin('in-flight') == original  # Lookup, never execution authority.
    assert registry.state() == {'revision': 3, 'active': None}
    with pytest.raises(p.Refused, match='No admitted'):
        registry.pin('next')
    with pytest.raises(p.Refused, match='withdrawn'):
        registry.promote(evidence, 'runbook_fallback', expected_revision=3)
    assert registry.state()['revision'] == 3
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT action FROM refusals ORDER BY sequence').fetchall() == [('withdraw',), ('promote',)]


def test_failed_candidate_preserves_active_version(evidence, tmp_path):
    registry = p.Registry(tmp_path / 'registry.sqlite')
    accepted = registry.promote(evidence, 'runbook_fallback', expected_revision=0)
    assert registry.promote(evidence, 'runbook', expected_revision=1)['kind'] == 'rejected'
    assert registry.state() == {'revision': 2, 'active': accepted['version']}
    assert registry.pin('after-rejection')['revision'] == 1


def test_complete_environment_miss_rejects_only_affected_candidate(evidence, tmp_path):
    # Ground truth becomes unknown for one candidate's complete measurement;
    # re-score it honestly. It must be retained and cannot authorize admission.
    results = json.loads((evidence / 'results.json').read_text())
    index = next(i for i, r in enumerate(results, 1) if r['variant'] == 'runbook')
    trial = evidence / f'trial-{index:03d}'
    verification = json.loads((trial / 'final-verification.json').read_text())
    for probe in verification['probes']:
        probe['observations']['database'] = {'kind': 'error'}
        probe.update(verdict='indeterminate', reasons=['database: independent read unavailable'])
    verification.update(verdict='indeterminate', reasons=['database: independent read unavailable'],
                         counts={'total': 2, 'verified_success': 0, 'verified_failure': 0, 'indeterminate': 2})
    save(trial / 'final-verification.json', verification)
    result = json.loads((trial / 'trial.json').read_text())
    observations = [json.loads(line) for line in (trial / 'evidence.jsonl').read_text().splitlines()]
    result['score'] = score_trial('healthy', 'runbook', result['agent']['terminal'], verification, [], observations)
    save(trial / 'trial.json', result)
    results[index - 1].update(result)
    save(evidence / 'results.json', results)
    registry = p.Registry(tmp_path / 'registry.sqlite')
    assert registry.promote(evidence, 'runbook', expected_revision=0)['kind'] == 'rejected'
    assert registry.promote(evidence, 'runbook_fallback', expected_revision=1)['kind'] == 'promoted'
    assert any(o['environment_recovered'] is None and not o['environment_matches']
               for o in p.evaluate(evidence, 'runbook')['outcomes'])


def test_version_binds_image_and_pin_binds_actual_activation(evidence, tmp_path):
    registry = p.Registry(tmp_path / 'registry.sqlite')
    original = registry.promote(evidence, 'runbook_fallback', expected_revision=0)
    before = registry.pin('before')
    again = registry.promote(evidence, 'runbook_fallback', expected_revision=1)
    assert again['version'] == original['version']
    assert registry.pin('after')['revision'] == 2
    assert registry.pin('before') == before
    release = json.loads((evidence / 'release.json').read_text())
    release['configuration']['agent_image_id'] = 'sha256:' + 'b' * 64
    release = release_manifest(release['configuration'])
    save(evidence / 'release.json', release)
    manifest = json.loads((evidence / 'manifest.json').read_text())
    manifest['agent_image_id'] = release['configuration']['agent_image_id']
    save(evidence / 'manifest.json', manifest)
    for path in evidence.glob('trial-*/worker-request.json'):
        request = json.loads(path.read_text())
        request.update(config=release['configuration'], release_id=release['release_id'])
        save(path, request)
    new = registry.promote(evidence, 'runbook_fallback', expected_revision=2)
    assert new['version'] != original['version']
    assert registry.pin('other-image') == {'episode': 'other-image', 'version': new['version'], 'revision': 3}
    assert registry.pin('before') == before


def test_admission_refuses_drift_but_retains_historical_pin(evidence, tmp_path, monkeypatch):
    registry = p.Registry(tmp_path / 'registry.sqlite')
    registry.promote(evidence, 'runbook_fallback', expected_revision=0)
    pin = registry.pin('old')
    monkeypatch.setattr(p, 'release_manifest', lambda _: {'files': {'changed': 'source'}})
    assert registry.pin('old') == pin
    with pytest.raises(p.Refused, match='source changed'):
        registry.pin('new')


def test_concurrent_promotions_cannot_both_use_same_revision(evidence, tmp_path):
    registry = p.Registry(tmp_path / 'registry.sqlite')

    def attempt(_):
        try:
            return registry.promote(evidence, 'runbook_fallback', expected_revision=0)['kind']
        except p.Refused:
            return 'refused'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ['promoted', 'refused']
    assert registry.state()['revision'] == 1


@pytest.mark.parametrize('revision', [True, -1, None, '0'])
def test_invalid_revision_refuses_without_state_change(evidence, tmp_path, revision):
    registry = p.Registry(tmp_path / 'registry.sqlite')
    with pytest.raises(p.Refused):
        registry.promote(evidence, 'runbook_fallback', expected_revision=revision)
    assert registry.state()['revision'] == 0
