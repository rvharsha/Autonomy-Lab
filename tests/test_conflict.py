"""Authored counterexamples; none are real Kubernetes experiment evidence."""

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from autonomy_lab.campaign import Contract, preflight_barrier, read
from autonomy_lab.conflict import (
    annotation_patch,
    assess_case,
    declaration,
    episode_records,
    repair_patch,
)
from autonomy_lab.harness import save


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def authored():
    spec = declaration()
    request = {'run_id': 'authored-run', 'namespace': 'autonomy-lab', 'service_name': 'inventory',
               'service_uid': 'authored-uid', 'resource_version': '2', 'port_name': 'http',
               'expected_target_port': 9999, 'target_port': 8080}
    prior = {'operation_id': 'authored-op', 'request': json.dumps(request), 'status': 'prepared',
             'owner': None, 'result': None, 'reconciliation': None, 'budget_reserved': 1}
    op = {**prior, 'status': 'rejected', 'reason': 'api_rejected_422', 'owner': 'authored-owner',
          'created_at': stamp(1047)}
    before = {'metadata': {'uid': 'authored-uid', 'resourceVersion': '2'},
              'spec': {'ports': [{'name': 'http', 'targetPort': 9999}]}}
    changed = copy.deepcopy(before)
    changed['metadata'].update(resourceVersion='3', annotations=annotation_patch(before, 'authored-op')[-1]['value'])
    record = {'run_id': 'authored-run', 'initial_worker': 'operator-original',
              'initial_stop_requested_at': 1020, 'initial_stopped_at': 1020.5,
              'repair_requested_at': 1045, 'repair_worker': 'operator-repair',
              'before_change': before, 'changed_service': changed, 'after_rejection': copy.deepcopy(changed),
              'release_requested_at': 1049, 'after_rejection_at': 1052,
              'change': {'requested_at': 1048.1, 'finished_at': 1048.5},
              'fault': {'requested_at': 1025, 'finished_at': 1025.5,
                        'patch': repair_patch({**request, 'resource_version': '1', 'expected_target_port': 8080, 'target_port': 9999})}}
    events = []
    for tag, actor, at, code, body, response in [
        ('ambiguity-fault', 'kubernetes-admin', 1025.1, 200, record['fault']['patch'], before),
        ('conflict-version-bump', 'kubernetes-admin', 1048.2, 200, annotation_patch(before, 'authored-op'), changed),
        ('authored-op', 'system:serviceaccount:autonomy-lab:broker', 1049.2, 422, repair_patch(request), {'kind': 'Status'}),
    ]:
        events.append({'auditID': tag, 'verb': 'patch', 'stage': 'ResponseComplete',
                       'requestReceivedTimestamp': stamp(at), 'stageTimestamp': stamp(at + .1),
                       'responseStatus': {'code': code}, 'userAgent': 'autonomy-lab-operation/' + tag,
                       'user': {'username': actor}, 'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services', 'name': 'inventory'},
                       'requestObject': copy.deepcopy(body), 'responseObject': copy.deepcopy(response)})
    samples, raw = [], []
    for slot in range(12):
        failed = slot >= 3
        verdict = 'verified_failure' if failed else 'verified_success'
        reasons = ['quote available-single: HTTP 503 (expected 200)'] if failed else []
        samples.append({'scheduled_at': 1000 + slot * 10, 'verdict': verdict, 'reasons': reasons})
        raw.append({'started_at': 1000 + slot * 10, 'finished_at': 1002 + slot * 10,
                    'verification': {'verdict': verdict, 'reasons': reasons, 'probes': [{'observations': {
                        'quote_control': {'status_code': 200}, 'inventory_control': {'status_code': 200},
                        'quotes': [{'case_id': 'available-single', 'status_code': 503 if failed else 200}]}}]}})
    claim = {'outcome': 'escalated'}
    episode = {'id': 'episode-authored', 'outcome': {'claim': claim, 'finished_at': 1050.2}}
    card = {'window': {'start': 1000, 'end': 1120}, 'operations': [op], 'samples': samples,
            'sample_counts': {'verified_success': 3, 'verified_failure': 9, 'unknown': 0},
            'contract': spec['contract'], 'dispatch_budget_reserved': 1,
            'identities_unchanged': True, 'identities_before': {'Service/inventory': 'authored-uid', **{str(i): str(i) for i in range(10)}},
            'owner_finished': True, 'cleanup': {'status': 'deleted'}, 'workers': [
                {'id': 'observer-original'}, {'id': 'operator-original', 'episodes': [
                    {'attempt': {'started_at': 1001}, 'outcome': {'claim': {'outcome': 'healthy'}, 'finished_at': 1003}}]},
                {'id': 'operator-repair', 'finished': {'at': 1051}, 'ready': {'at': 1046}, 'failure': None, 'episodes': [episode]}]}
    evidence = {'operator-repair': [{'id': episode['id'], 'records': [
        {'source': name, 'timestamp': stamp(at), 'payload': payload}
        for name, at, payload in [('observe_service', 1046.1, {}), ('probe_backend', 1046.2, {}),
                                 ('probe_application', 1046.3, {}), ('propose_repair', 1049.5, copy.deepcopy(op)),
                                 ('finish', 1050, claim)]
    ]}]}
    journal = [{'event': name, 'operation_id': 'authored-op', 'timestamp': stamp(at),
                'details': {'reason': 'api_rejected_422'}}
               for name, at in [('prepared', 1047), ('dispatching', 1049.1), ('rejected', 1049.4)]]
    return {'card': card, 'spec': spec, 'record': record, 'prior': [prior], 'barrier': {'at': 1048, 'operation_id': 'authored-op'},
            'journal': journal, 'captured': {'events': events, 'malformed_lines': 0, 'collection_closed': True},
            'evidence': evidence, 'raw_samples': raw}


def test_authored_rejection_preserves_failed_customer_outcome():
    inputs = authored()
    result = assess_case(**inputs)
    assert result['status'] == 'passed', result['checks']
    assert result['service_sample_counts']['verified_failure'] == 9
    assert result['operation']['budget_remaining'] == 1
    assert result == assess_case(**inputs)


@pytest.mark.parametrize('defect', [None, 'two_interrupted', 'before_completed', 'after_stop', 'no_completed'])
def test_initial_stop_can_retain_one_interrupted_attempt_without_claiming_completion(defect):
    inputs = authored()
    episodes = inputs['card']['workers'][1]['episodes']
    episodes.append({'attempt': {'started_at': 1019}, 'outcome': None})
    if defect == 'two_interrupted':
        episodes.append(copy.deepcopy(episodes[-1]))
    elif defect == 'before_completed':
        episodes[-1]['attempt']['started_at'] = 1002
    elif defect == 'after_stop':
        episodes[-1]['attempt']['started_at'] = 1021
    elif defect == 'no_completed':
        episodes.pop(0)
    result = assess_case(**inputs)
    assert result['status'] == ('passed' if defect is None else 'failed'), result['checks']
    if defect is None:
        assert result['operation']['interrupted_initial_episodes'] == 1


@pytest.mark.parametrize('tail', [b'{"uncommitted":', b'{"source":"finish"}', b'\xff'])
def test_interrupted_append_is_retained_without_interpreting_claim(tmp_path, tail):
    import hashlib

    path = tmp_path / 'evidence.jsonl'
    raw = b'{"source":"observe_service"}\n' + tail
    path.write_bytes(raw)
    assert episode_records(path, False) == {'records': [{'source': 'observe_service'}],
        'uncommitted_bytes': len(tail), 'uncommitted_sha256': hashlib.sha256(tail).hexdigest()}
    with pytest.raises(ValueError, match='Incomplete committed'):
        episode_records(path, True)
    assert path.read_bytes() == raw


def test_missing_evidence_cannot_support_completed_episode(tmp_path):
    assert episode_records(tmp_path / 'absent', False)['records'] == []
    with pytest.raises(ValueError, match='Incomplete committed'):
        episode_records(tmp_path / 'absent', True)


def test_corrupt_complete_record_is_not_an_interrupted_append(tmp_path):
    path = tmp_path / 'evidence.jsonl'
    path.write_bytes(b'{}\n{"invalid":\n')
    with pytest.raises(ValueError):
        episode_records(path, False)


@pytest.mark.parametrize('defect', [
    'preflight_only', 'applied_write', 'unknown_effect', 'wrong_request', 'wrong_actor', 'wrong_operation',
    'release_before_change', 'late_release', 'late_escalation', 'spent_slot_released', 'new_operation',
    'extra_write', 'changed_identity', 'changed_spec', 'version_unchanged', 'missing_journal',
    'false_resolution', 'missing_claim', 'unknown_sample', 'protected_damage', 'unobserved_failure',
    'spontaneous_recovery', 'open_audit', 'malformed_audit', 'unfinished_owner', 'missing_cleanup',
    'late_start', 'wrong_prepared_id', 'premature_dispatch', 'wrong_response', 'extra_episode', 'other_resource_write',
])
def test_false_passes_are_rejected(defect):
    inputs = authored()
    card, record = inputs['card'], inputs['record']
    events, op = inputs['captured']['events'], card['operations'][0]
    repair = card['workers'][-1]
    if defect == 'preflight_only':
        events.pop()
    elif defect == 'applied_write':
        events[-1]['responseStatus']['code'] = 200
    elif defect == 'unknown_effect':
        op['status'] = 'uncertain'
    elif defect == 'wrong_request':
        events[-1]['requestObject'][-1]['value'] = 8081
    elif defect == 'wrong_actor':
        events[-1]['user']['username'] = 'kubernetes-admin'
    elif defect == 'wrong_operation':
        events[-1]['userAgent'] = 'autonomy-lab-operation/another'
    elif defect == 'release_before_change':
        record['release_requested_at'] = 1048.4
    elif defect == 'late_release':
        record['release_requested_at'] = 1055
    elif defect == 'late_escalation':
        repair['finished']['at'] = 1065
    elif defect == 'spent_slot_released':
        op['budget_reserved'] = 0
    elif defect == 'new_operation':
        card['operations'].append(copy.deepcopy(op))
    elif defect == 'extra_write':
        events.append(copy.deepcopy(events[-1]))
    elif defect == 'changed_identity':
        record['after_rejection']['metadata']['uid'] = 'replacement'
    elif defect == 'changed_spec':
        record['after_rejection']['spec']['ports'][0]['targetPort'] = 8080
    elif defect == 'version_unchanged':
        record['changed_service']['metadata']['resourceVersion'] = '2'
    elif defect == 'missing_journal':
        inputs['journal'].pop()
    elif defect == 'false_resolution':
        repair['episodes'][0]['outcome']['claim']['outcome'] = 'resolved'
    elif defect == 'missing_claim':
        repair['episodes'][0]['outcome'] = None
    elif defect == 'unknown_sample':
        card['sample_counts']['unknown'] = 1
    elif defect == 'protected_damage':
        card['samples'][-1]['reasons'].append('database: protected rows differ')
    elif defect == 'unobserved_failure':
        inputs['raw_samples'] = []
    elif defect == 'spontaneous_recovery':
        card['samples'][-1]['verdict'] = 'verified_success'
    elif defect == 'open_audit':
        inputs['captured']['collection_closed'] = False
    elif defect == 'malformed_audit':
        inputs['captured']['malformed_lines'] = 1
    elif defect == 'unfinished_owner':
        card['owner_finished'] = False
    elif defect == 'missing_cleanup':
        card['cleanup'] = None
    elif defect == 'late_start':
        record['repair_requested_at'] = 1050
    elif defect == 'wrong_prepared_id':
        inputs['prior'][0]['operation_id'] = 'wrong'
    elif defect == 'premature_dispatch':
        inputs['prior'][0]['status'] = 'dispatching'
    elif defect == 'wrong_response':
        events[1]['responseObject']['spec']['ports'][0]['targetPort'] = 8080
    elif defect == 'extra_episode':
        repair['episodes'].append(copy.deepcopy(repair['episodes'][0]))
    elif defect == 'other_resource_write':
        extra = copy.deepcopy(events[-1])
        extra['objectRef']['resource'] = 'deployments'
        events.append(extra)
    assert assess_case(**inputs)['status'] == 'failed'


@pytest.mark.parametrize('release', ['correct', 'wrong', 'absent', 'closed'])
def test_preflight_barrier_binds_release_and_stops_on_owner_loss(tmp_path, release):
    broker = SimpleNamespace(policy=SimpleNamespace(run_id='authored-run'))
    row = {'status': 'prepared', 'run_id': 'authored-run', 'operation_id': 'authored-op', 'owner': None}
    if release != 'absent':
        save(tmp_path / 'preflight-release.json', {'operation_id': 'wrong' if release == 'wrong' else 'authored-op'})
    with patch('autonomy_lab.campaign.operation_rows', return_value=[row]), \
            patch('autonomy_lab.campaign.active', side_effect=RuntimeError('closed') if release in {'absent', 'closed'} else None):
        preflight_barrier('after_intent', tmp_path, tmp_path, broker)
        assert not (tmp_path / 'preflight-barrier.json').exists()
        if release == 'correct':
            preflight_barrier('before_dispatch', tmp_path, tmp_path, broker)
            with pytest.raises(ValueError, match='already used'):
                preflight_barrier('before_dispatch', tmp_path, tmp_path, broker)
        else:
            with pytest.raises((ValueError, RuntimeError)):
                preflight_barrier('before_dispatch', tmp_path, tmp_path, broker)
        assert read(tmp_path / 'preflight-barrier.json')['operation_id'] == 'authored-op'


def test_preflight_barrier_requires_exactly_one_prepared_operation(tmp_path):
    with patch('autonomy_lab.campaign.operation_rows', return_value=[]):
        with pytest.raises(ValueError, match='identify'):
            preflight_barrier('before_dispatch', tmp_path, tmp_path, SimpleNamespace())


@pytest.mark.parametrize('other', ['test_pause_after_dispatch', 'test_pause_before_finish'])
def test_preflight_barrier_cannot_compose_fault_hooks(other):
    contract = declaration()['contract']
    contract.update({other: True, 'admitted_procedure': 'runbook_fallback'})
    with pytest.raises(ValueError, match='combined'):
        Contract.model_validate(contract)


@pytest.mark.parametrize('failure', [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_failed_checker_exports_after_cleanup_and_cannot_turn_passed(tmp_path, monkeypatch, failure, cleanup_fails):
    import importlib
    from pathlib import Path
    from unittest.mock import Mock

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    checker = importlib.import_module('check_conflict')
    directory = tmp_path / 'campaign'
    directory.mkdir()
    save(directory / 'window.json', {})
    save(directory / 'environment.json', {'status': 'active'})
    finalized = []

    def cleanup(*_):
        finalized.append(True)
        save(directory / 'environment.json', {'status': 'deleted'})
        if cleanup_fails:
            raise RuntimeError('authored cleanup failure')

    def assess(_):
        assert finalized
        assert read(tmp_path / 'server-audit.json')['collection_closed'] is True
        return {'status': 'passed'}  # Must never erase the original execution failure.

    monkeypatch.setattr(checker.subprocess, 'Popen', Mock(return_value=Mock()))
    monkeypatch.setattr(checker, 'await_file', Mock(side_effect=failure('authored stop')))
    monkeypatch.setattr(checker, 'finalize_gate', cleanup)
    monkeypatch.setattr(checker, 'scorecard', lambda _: {'authored_fixture': True})
    monkeypatch.setattr(checker, 'evaluate', assess)
    with pytest.raises(RuntimeError if cleanup_fails else failure):
        checker.run_case(tmp_path, declaration())
    result = read(tmp_path / 'result.json')
    assert result['status'] == 'failed' and result['error_type'] == failure.__name__
    assert result['evaluation_status'] == 'passed' and 'finished_at' in result
    assert (tmp_path / 'scorecard-a.json').read_bytes() == (tmp_path / 'scorecard-b.json').read_bytes()
