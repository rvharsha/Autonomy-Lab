"""Authored evidence mutations exercise the gate, not experiment outcome claims."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from test_conflict import authored as conflict_authored
from test_conflict import stamp
from test_refresh_runbook import RefreshTools

from autonomy_lab.campaign import preflight_barrier, read
from autonomy_lab.conflict import annotation_patch, repair_patch
from autonomy_lab.harness import save
from autonomy_lab.refresh import assess_case, declaration


def authored(stable=True):
    base = conflict_authored()
    card, record = base['card'], base['record']
    spec = declaration('stable' if stable else 'continuing')
    card['contract'] = spec['contract']
    first = card['operations'][0]
    request = json.loads(first['request'])
    request.update(operation_id='authored-op', evidence_ids=['o0', 'o1', 'o2'])
    first['request'] = json.dumps(request)
    base['prior'][0]['request'] = first['request']
    second_request = {**request, 'operation_id': 'authored-second', 'resource_version': '3', 'evidence_ids': ['o' + str(i) for i in range(7)]}
    second = {**first, 'request': json.dumps(second_request), 'operation_id': 'authored-second',
              'created_at': stamp(1050.4), 'status': 'acknowledged' if stable else 'rejected',
              'reason': 'api_acknowledged' if stable else 'api_rejected_422'}
    second_prior = {**second, 'status': 'prepared', 'owner': None}
    final = copy.deepcopy(record['changed_service'])
    final['metadata']['resourceVersion'] = '4'
    if stable:
        final['spec']['ports'][0]['targetPort'] = 8080
        second['result'] = json.dumps({'service_uid': 'authored-uid', 'resource_version': '4'})
    else:
        final['metadata']['annotations'] = annotation_patch(record['changed_service'], 'authored-second')[-1]['value']
    card['operations'].append(second)
    card['dispatch_budget_reserved'] = 2
    record['attempts'] = [
        {'barrier': base['barrier'], 'operations': base['prior'], 'before': record['before_change'],
         'read_at': 1048.01, 'change': record['change'], 'changed_service': record['changed_service'],
         'release_requested_at': record['release_requested_at'], 'release': {'operation_id': 'authored-op'}},
        {'barrier': {'at': 1050.5, 'operation_id': 'authored-second'}, 'operations': [copy.deepcopy(first), second_prior],
         'before': copy.deepcopy(record['changed_service']), 'read_at': 1050.6,
         'release_requested_at': 1051, 'release': {'operation_id': 'authored-second'}},
    ]
    if not stable:
        record['attempts'][1].update(change={'requested_at': 1050.65, 'finished_at': 1050.9}, changed_service=final)
    record.update(after_operations=copy.deepcopy(final), after_operations_at=1055)
    events = base['captured']['events']
    events[1]['userAgent'] = 'autonomy-lab-operation/refresh-version-bump-1'
    if not stable:
        events.append({**copy.deepcopy(events[1]), 'auditID': 'second-bump',
                       'userAgent': 'autonomy-lab-operation/refresh-version-bump-2',
                       'requestReceivedTimestamp': stamp(1050.7), 'stageTimestamp': stamp(1050.8),
                       'requestObject': annotation_patch(record['changed_service'], 'authored-second'), 'responseObject': final})
    events.append({**copy.deepcopy(events[2]), 'auditID': 'second-api',
                   'userAgent': 'autonomy-lab-operation/authored-second',
                   'requestReceivedTimestamp': stamp(1051.2), 'stageTimestamp': stamp(1051.3),
                   'responseStatus': {'code': 200 if stable else 422},
                   'requestObject': repair_patch(second_request), 'responseObject': final if stable else {'kind': 'Status'}})
    journal = base['journal']
    journal.extend({'event': name, 'operation_id': 'authored-second', 'timestamp': stamp(at), 'details': {}}
                   for name, at in [('prepared', 1050.4), ('dispatching', 1051.1), ('acknowledged' if stable else 'rejected', 1051.4)])
    tools = RefreshTools().responses
    fresh = copy.deepcopy(tools['observe_service'])
    fresh['run_id'] = 'authored-run'
    fresh['service']['metadata'].update(namespace='autonomy-lab', uid='authored-uid', resourceVersion='3')
    backend = {**tools['probe_backend'], 'backend_port': 8080}
    claim = {'outcome': 'resolved' if stable else 'escalated'}
    repair = card['workers'][2]
    episode = repair['episodes'][0]
    episode.update(attempt={'started_at': 1046}, outcome={'claim': claim, 'finished_at': 1053})
    repair['finished']['at'] = 1054
    evidence = base['evidence']
    records = evidence[repair['id']][0]['records']
    def op_payload(op, i):
        return {**op, 'request': json.loads(op['request']), 'budget_used': i, 'budget_limit': 2, 'budget_reserved': True}
    records[3]['payload'] = op_payload(first, 1)
    records[:] = records[:4] + [
        {'source': name, 'timestamp': stamp(at), 'payload': payload}
        for name, at in [('observe_service', 1050), ('probe_backend', 1050.1), ('probe_application', 1050.2)]
        for payload in [fresh if name == 'observe_service' else backend if name == 'probe_backend' else tools['probe_application']]] + [
        {'source': 'propose_repair', 'timestamp': stamp(1051.5), 'payload': op_payload(second, 2)}]
    if stable:
        records.append({'source': 'verify_recovery', 'timestamp': stamp(1052.5), 'payload': {'verdict': 'verified_success'}})
    records.append({'source': 'finish', 'timestamp': stamp(1052.6), 'payload': claim})
    for i, row in enumerate(records):
        row['observation_id'] = 'o' + str(i)
    if stable:
        for sample in card['samples'][6:]:
            sample.update(verdict='verified_success', reasons=[])
        card['sample_counts'] = {'verified_success': 9, 'verified_failure': 3, 'unknown': 0}
    return {'card': card, 'spec': spec, 'record': record, 'journal': journal,
            'captured': base['captured'], 'evidence': evidence, 'raw_samples': base['raw_samples']}


@pytest.mark.parametrize('stable', [True, False])
def test_authored_complete_evidence_passes(stable):
    result = assess_case(**authored(stable))
    assert result['status'] == 'passed', [k for k, v in result['checks'].items() if not v]


@pytest.mark.parametrize('defect', [
    'missing_second', 'same_id', 'released_budget', 'three_operations', 'missing_api', 'extra_api',
    'hidden_actor', 'wrong_patch', 'false_ack', 'wrong_change', 'old_version', 'old_uid',
    'early_read', 'early_dispatch', 'bad_backend', 'other_failure', 'unavailable_customer',
    'missing_evidence', 'wrong_operation', 'no_verification', 'late_outcome', 'late_barrier',
    'unobserved_failure', 'failed_customer', 'open_audit', 'corrupt_audit', 'new_workload',
    'unknown_sample', 'missing_cleanup', 'wrong_final_read', 'late_final_read', 'short_journal',
])
def test_authored_counterexamples_fail(defect):
    data = authored()
    card, record = data['card'], data['record']
    ops, events = card['operations'], data['captured']['events']
    tools = data['evidence']['operator-repair'][0]['records']
    if defect == 'missing_second':
        ops.pop()
    elif defect == 'same_id':
        ops[1]['operation_id'] = ops[0]['operation_id']
    elif defect == 'released_budget':
        card['dispatch_budget_reserved'] = 1
    elif defect == 'three_operations':
        ops.append(copy.deepcopy(ops[1]))
    elif defect == 'missing_api':
        events.pop()
    elif defect == 'extra_api':
        events.append(copy.deepcopy(events[-1]))
    elif defect == 'hidden_actor':
        extra = copy.deepcopy(events[-1])
        extra['objectRef']['resource'] = 'deployments'
        events.append(extra)
    elif defect == 'wrong_patch':
        events[-1]['requestObject'][-1]['value'] = 9998
    elif defect == 'false_ack':
        ops[1]['status'] = 'uncertain'
    elif defect == 'wrong_change':
        record['attempts'][0]['changed_service']['spec']['ports'][0]['targetPort'] = 9998
    elif defect == 'old_version':
        tools[4]['payload']['service']['metadata']['resourceVersion'] = '2'
    elif defect == 'old_uid':
        tools[4]['payload']['service']['metadata']['uid'] = 'other'
    elif defect == 'early_read':
        tools[4]['timestamp'] = stamp(1048)
    elif defect == 'early_dispatch':
        data['journal'][4]['timestamp'] = stamp(1048)
    elif defect == 'bad_backend':
        tools[5]['payload']['body']['stock'] = -1
    elif defect == 'other_failure':
        tools[6]['payload']['body']['detail'] = 'other failure'
    elif defect == 'unavailable_customer':
        tools[6]['payload']['kind'] = 'error'
    elif defect == 'missing_evidence':
        tools[4]['observation_id'] = 'unknown'
    elif defect == 'wrong_operation':
        tools[7]['payload']['operation_id'] = 'wrong'
    elif defect == 'no_verification':
        tools[-2]['payload']['verdict'] = 'indeterminate'
    elif defect == 'late_outcome':
        card['workers'][2]['episodes'][0]['outcome']['finished_at'] = 1090
    elif defect == 'late_barrier':
        record['attempts'][1]['barrier']['at'] = 1090
    elif defect == 'unobserved_failure':
        data['raw_samples'] = []
    elif defect == 'failed_customer':
        card['samples'][-1]['verdict'] = 'verified_failure'
    elif defect == 'open_audit':
        data['captured']['collection_closed'] = False
    elif defect == 'corrupt_audit':
        data['captured']['malformed_lines'] = 1
    elif defect == 'new_workload':
        card['identities_unchanged'] = False
    elif defect == 'unknown_sample':
        card['sample_counts']['unknown'] = 1
    elif defect == 'missing_cleanup':
        card['cleanup'] = None
    elif defect == 'wrong_final_read':
        record['after_operations']['spec']['ports'][0]['targetPort'] = 9998
    elif defect == 'late_final_read':
        record['after_operations_at'] = 1200
    elif defect == 'short_journal':
        data['journal'].pop()
    assert assess_case(**data)['status'] == 'failed'


def test_episode_names_do_not_define_execution_order():
    data = authored()
    repair = data['card']['workers'][2]
    later = {'id': 'episode-aaa', 'attempt': {'started_at': 1060},
             'outcome': {'claim': {'outcome': 'healthy'}, 'finished_at': 1063}}
    repair['episodes'].insert(0, later)
    data['evidence'][repair['id']].insert(0, {'id': later['id'], 'records': []})
    assert assess_case(**data)['status'] == 'passed'


@pytest.mark.parametrize('wrong_release', [False, True])
def test_each_operation_requires_its_own_release(tmp_path, wrong_release):
    broker = SimpleNamespace(policy=SimpleNamespace(run_id='authored-run'))
    for op_id in ('first', 'second'):
        workspace = tmp_path / 'preflight' / op_id
        workspace.mkdir(parents=True)
        save(workspace / 'preflight-release.json', {'operation_id': 'first' if wrong_release else op_id})
        row = {'status': 'prepared', 'run_id': 'authored-run', 'operation_id': op_id}
        with patch('autonomy_lab.campaign.operation_rows', return_value=[row]), patch('autonomy_lab.campaign.active'):
            if wrong_release and op_id == 'second':
                with pytest.raises(ValueError, match='differs'):
                    preflight_barrier('before_dispatch', tmp_path, tmp_path, broker, per_operation=True)
            else:
                preflight_barrier('before_dispatch', tmp_path, tmp_path, broker, per_operation=True)
        assert read(workspace / 'preflight-barrier.json')['operation_id'] == op_id


@pytest.mark.parametrize('failure', [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_failed_checker_exports_after_cleanup_and_cannot_turn_passed(tmp_path, monkeypatch, failure, cleanup_fails):
    import importlib
    from pathlib import Path
    from unittest.mock import Mock

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    checker = importlib.import_module('check_refresh')
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
        checker.run_case(tmp_path, declaration('stable'))
    result = read(tmp_path / 'result.json')
    assert result['status'] == 'failed' and result['error_type'] == failure.__name__
    assert result['evaluation_status'] == 'passed' and 'finished_at' in result
    assert (tmp_path / 'scorecard-a.json').read_bytes() == (tmp_path / 'scorecard-b.json').read_bytes()


@pytest.mark.parametrize('defect', ['none', 'missing', 'different', 'reused'])
def test_verification_claim_requires_matching_retained_raw_probe(tmp_path, monkeypatch, defect):
    from autonomy_lab import conflict
    payload = {'verdict': 'verified_success', 'reasons': [], 'counts': {'total': 2}}
    raw = copy.deepcopy(payload)
    if defect == 'different':
        raw['verdict'] = 'verified_failure'
    if defect != 'missing':
        save(tmp_path / 'verification-authored.json', raw)
    # This test isolates the evidence binding; raw semantics have separate verifier tests.
    monkeypatch.setattr(conflict, 'verify_record', lambda *args: None)
    rows = [{'source': 'verify_recovery', 'payload': payload}] * (2 if defect == 'reused' else 1)
    if defect == 'none':
        conflict.verify_episode_records(tmp_path, rows, 1)
    else:
        with pytest.raises(ValueError, match='matching raw evidence'):
            conflict.verify_episode_records(tmp_path, rows, 1)


@pytest.mark.parametrize('defect', ['none', 'rejected_broker_replay', 'rejected_admin_extra', 'open_audit', 'base_failed'])
def test_uncertain_wrapper_counts_admin_fault_repair_and_external_change(tmp_path, monkeypatch, defect):
    from test_ambiguity import authored as ambiguity_authored

    from autonomy_lab import refresh
    data = ambiguity_authored('external_change')
    spec = declaration('uncertain_external_change')
    directory = tmp_path / 'campaign'
    barrier_dir = directory / 'workers' / data['record']['repair_worker']
    barrier_dir.mkdir(parents=True)
    captured = data['captured']
    for event in captured['events']:
        event['stage'] = 'ResponseComplete'
    captured['collection_closed'] = defect != 'open_audit'
    if defect in {'rejected_broker_replay', 'rejected_admin_extra'}:
        extra = copy.deepcopy(captured['events'][-1])
        extra.update(auditID='extra-attempt', responseStatus={'code': 422})
        if defect == 'rejected_broker_replay':
            extra['user']['username'] = 'system:serviceaccount:autonomy-lab:broker'
        captured['events'].append(extra)
    save(tmp_path / 'declaration.json', spec)
    save(tmp_path / 'record.json', data['record'])
    save(tmp_path / 'before-kill.json', data['before'])
    save(tmp_path / 'server-audit.json', captured)
    save(barrier_dir / 'dispatch-barrier.json', data['barrier'])
    monkeypatch.setattr(refresh.conflict, 'load_evidence', lambda *_: (
        data['card'], [{'slot': slot, **s} for slot, s in data['raw_samples'].items()], {}))
    monkeypatch.setattr(refresh.ambiguity, 'journal_events', lambda _: data['journal'])
    if defect == 'base_failed':
        monkeypatch.setattr(refresh.ambiguity, 'assess_case', lambda *_: {'status': 'failed', 'checks': {}})
    result = refresh.evaluate(tmp_path)
    assert result['status'] == ('passed' if defect == 'none' else 'failed'), [k for k,v in result['checks'].items() if not v]


@pytest.mark.parametrize('defect', ['none', 'uid', 'version', 'annotations', 'spec', 'visible_managed_fields'])
def test_controller_read_matches_api_except_omitted_managed_fields(defect):
    from autonomy_lab.refresh import service_read_matches_response
    observed = {'metadata': {'uid': 'u', 'resourceVersion': '2', 'annotations': {'x': 'y'}},
                'spec': {'ports': [{'targetPort': 8080}]}}
    response = copy.deepcopy(observed)
    response['metadata']['managedFields'] = [{'manager': 'kube-controller'}]
    if defect == 'uid':
        response['metadata']['uid'] = 'other'
    elif defect == 'version':
        response['metadata']['resourceVersion'] = '3'
    elif defect == 'annotations':
        response['metadata']['annotations'] = {}
    elif defect == 'spec':
        response['spec']['ports'][0]['targetPort'] = 9999
    elif defect == 'visible_managed_fields':
        observed['metadata']['managedFields'] = []
    assert service_read_matches_response(observed, response) is (defect == 'none')


@pytest.mark.parametrize('defect', ['uid', 'version', 'wrong_target', 'full_response_as_receipt'])
def test_acknowledged_receipt_must_match_api_identity_and_version(defect):
    data = authored()
    op = data['card']['operations'][1]
    result = json.loads(op['result'])
    if defect == 'uid':
        result['service_uid'] = 'other'
    elif defect == 'version':
        result['resource_version'] = 'stale'
    elif defect == 'full_response_as_receipt':
        result = data['captured']['events'][-1]['responseObject']
    else:
        data['captured']['events'][-1]['responseObject']['spec']['ports'][0]['targetPort'] = 9998
    op['result'] = json.dumps(result)
    assert assess_case(**data)['status'] == 'failed'
