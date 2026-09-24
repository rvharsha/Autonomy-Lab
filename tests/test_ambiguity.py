"""Authored adversarial fixtures, never counted as Kubernetes experiment evidence."""

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from autonomy_lab.ambiguity import assess_case, declaration, evaluate
from autonomy_lab.campaign import dispatch_barrier, read
from autonomy_lab.harness import save


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def authored(case):
    spec = declaration(case)
    external = case == 'external_change'
    target = 9998 if external else 8080
    recon = {'observed_at': stamp(1080), 'service_uid': 'authored-uid', 'resource_version': '4' if external else '3',
             'target_port': target, 'identity_matches': True, 'attribution': 'not_established', 'recovery': 'not_verified',
             'observation': 'desired_state_not_observed' if external else 'desired_state_observed'}
    request = {'run_id': 'authored-run', 'namespace': 'autonomy-lab', 'service_name': 'inventory',
               'service_uid': 'authored-uid', 'resource_version': '2', 'port_name': 'http',
               'expected_target_port': 9999, 'target_port': 8080}
    prior = {'operation_id': 'authored-op', 'request': json.dumps(request), 'status': 'dispatching',
             'owner': 'authored-owner', 'result': None, 'reconciliation': None, 'budget_reserved': 1}
    operation = {**prior, 'status': 'uncertain', 'reason': 'dispatch_outcome_unrecorded',
                 'reconciliation': json.dumps(recon), 'created_at': stamp(1047)}
    record = {'run_id': 'authored-run', 'initial_stop_requested_at': 1020, 'initial_stopped_at': 1021,
              'repair_requested_at': 1045, 'repair_ready_at': 1046, 'repair_worker': 'operator-repair',
              'kill_requested_at': 1049, 'stopped_at': 1049.1, 'restart_requested_at': 1079.1,
              'resumed_ready_at': 1079.5, 'resumed_worker': 'operator-resumed'}
    events = []

    def action(name, at, old, new, version, user, op_id):
        mutations = [{'op': 'test', 'path': '/metadata/uid', 'value': 'authored-uid'},
                     {'op': 'test', 'path': '/metadata/resourceVersion', 'value': version},
                     {'op': 'test', 'path': '/spec/ports/0/name', 'value': 'http'},
                     {'op': 'test', 'path': '/spec/ports/0/targetPort', 'value': old},
                     {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': new}]
        record[name] = {'requested_at': at, 'finished_at': at + 0.5, 'patch': mutations,
                        'old_target_port': old, 'new_target_port': new, 'resource_version': str(int(version) + 1)}
        events.append({'auditID': 'authored-' + name, 'verb': 'patch', 'requestReceivedTimestamp': stamp(at + 0.1),
                       'stageTimestamp': stamp(at + 0.3), 'responseStatus': {'code': 200},
                       'userAgent': 'autonomy-lab-operation/' + op_id, 'user': {'username': user},
                       'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services', 'name': 'inventory'},
                       'requestObject': mutations, 'responseObject': {'metadata': {'resourceVersion': str(int(version) + 1)},
                                                                    'spec': {'ports': [{'name': 'http', 'targetPort': new}]}}})
    action('fault', 1025, 8080, 9999, '1', 'kubernetes-admin', 'ambiguity-fault')
    action('repair', 1047, 9999, 8080, '2', 'system:serviceaccount:autonomy-lab:broker', 'authored-op')
    if external:
        action('external', 1061.1, 8080, 9998, '3', 'kubernetes-admin', 'ambiguity-external')
    raw, samples = {}, []
    for slot in range(15):
        failed = slot in {3, 4} or (external and slot >= 7)
        verdict = 'verified_failure' if failed else 'verified_success'
        reasons = ['quote available-single: HTTP 503 (expected 200)'] if failed else []
        row = {'slot': slot, 'scheduled_at': 1000 + 10 * slot, 'started_at': 1000 + 10 * slot,
               'finished_at': 1002 + 10 * slot, 'verdict': verdict, 'reasons': reasons}
        samples.append(row)
        raw[slot] = {'verification': {'verdict': verdict, 'reasons': reasons, 'probes': [{'observations': {
            'quote_control': {'status_code': 200}, 'inventory_control': {'status_code': 200},
            'quotes': [{'case_id': 'available-single', 'status_code': 503 if failed else 200}]}}]}}
    card = {'window': {'start': 1000, 'end': 1150}, 'operations': [operation], 'samples': samples,
            'sample_counts': {v: sum(s['verdict'] == v for s in samples) for v in ['verified_success', 'verified_failure', 'unknown']},
            'contract': {'max_dispatches': 2, 'max_restart_downtime_seconds': 45}, 'dispatch_budget_reserved': 1,
            'identities_unchanged': True, 'identities_before': {'Service/inventory': 'authored-uid', **{str(i): str(i) for i in range(10)}},
            'owner_finished': True, 'cleanup': {'status': 'deleted'}, 'workers': [
                {'id': 'observer-original'}, {'id': 'operator-original'},
                {'id': 'operator-repair', 'finished': None, 'failure': None, 'episodes': [{'outcome': None}]},
                {'id': 'operator-resumed', 'finished': {'at': 1081}, 'failure': None, 'episodes': [],
                 'escalation': {'reason': 'unresolved_prior_operations', 'operation_ids': ['authored-op']}}]}
    journal = [{'event': name, 'operation_id': 'authored-op'} for name in ['prepared', 'dispatching', 'reconciled']]
    return {'card': card, 'spec': spec, 'record': record, 'before': [prior], 'barrier': {'at': 1048, 'operation_id': 'authored-op'},
            'journal': journal, 'captured': {'events': events, 'malformed_lines': 0}, 'raw_samples': raw}


@pytest.mark.parametrize('case', ['unchanged', 'external_change'])
def test_authored_cases_separate_operator_uncertainty_from_measured_health(case):
    inputs = authored(case)
    result = assess_case(**inputs)
    assert result['status'] == 'passed', result['checks']
    assert result['operation']['service_recovered'] is (case == 'unchanged')
    assert result['operation']['reconciliation']['attribution'] == 'not_established'
    assert result == assess_case(**inputs)


@pytest.mark.parametrize('defect', [
    'unknown', 'protected_damage', 'missing_audit', 'late_api_response', 'wrong_audit_id', 'duplicate_write',
    'extra_controller_write', 'extra_operation', 'budget_exhausted', 'before_already_acknowledged',
    'before_already_reconciled', 'before_wrong_request', 'barrier_wrong_operation', 'hidden_acknowledgement',
    'lost_escalation', 'resumed_new_episode', 'committed_interrupted_episode', 'late_kill', 'late_restart',
    'late_exit', 'wrong_uid', 'wrong_current_version', 'false_attribution', 'false_recovery', 'unexpected_health',
    'lost_cleanup', 'observer_restarted', 'malformed_audit', 'audit_end_boundary', 'initial_unknown',
    'unobserved_external_fault', 'external_after_restart', 'late_external_change', 'missing_worker'])
def test_adversarial_evidence_cannot_pass(defect):
    inputs = authored('external_change')
    card, record = inputs['card'], inputs['record']
    events, op = inputs['captured']['events'], card['operations'][0]
    if defect == 'unknown':
        card['sample_counts']['unknown'] = 1
    elif defect == 'protected_damage':
        card['samples'][3]['reasons'].append('database: protected rows differ')
    elif defect == 'missing_audit':
        events.pop(1)
    elif defect == 'late_api_response':
        events[1]['stageTimestamp'] = stamp(1050)
    elif defect == 'wrong_audit_id':
        events[1]['userAgent'] = 'unattributed-client'
    elif defect in {'duplicate_write', 'extra_controller_write', 'audit_end_boundary'}:
        extra = copy.deepcopy(events[1])
        extra['auditID'] = 'authored-extra'
        if defect != 'duplicate_write':
            extra['user']['username'] = 'kubernetes-admin'
        if defect == 'audit_end_boundary':
            extra['requestReceivedTimestamp'] = stamp(1150)
        events.append(extra)
    elif defect == 'extra_operation':
        card['operations'].append(copy.deepcopy(op))
    elif defect == 'budget_exhausted':
        card['contract']['max_dispatches'] = 1
    elif defect == 'before_already_acknowledged':
        inputs['before'][0]['status'] = 'acknowledged'
    elif defect == 'before_already_reconciled':
        inputs['before'][0]['reconciliation'] = '{}'
    elif defect == 'before_wrong_request':
        inputs['before'][0]['request'] = '{}'
    elif defect == 'barrier_wrong_operation':
        inputs['barrier']['operation_id'] = 'another-op'
    elif defect == 'hidden_acknowledgement':
        inputs['journal'].insert(2, {'event': 'acknowledged', 'operation_id': 'authored-op'})
    elif defect == 'lost_escalation':
        card['workers'][3]['escalation'] = None
    elif defect == 'resumed_new_episode':
        card['workers'][3]['episodes'] = [{'outcome': None}]
    elif defect == 'committed_interrupted_episode':
        card['workers'][2]['episodes'][0]['outcome'] = {'claim': {'outcome': 'resolved'}}
    elif defect == 'late_kill':
        record['kill_requested_at'] = 1055
    elif defect == 'late_restart':
        record['restart_requested_at'] = 1099
    elif defect == 'late_exit':
        card['workers'][3]['finished']['at'] = 1110
    elif defect in {'wrong_uid', 'wrong_current_version', 'false_attribution', 'false_recovery'}:
        recon = json.loads(op['reconciliation'])
        key = {'wrong_uid': 'service_uid', 'wrong_current_version': 'resource_version',
               'false_attribution': 'attribution', 'false_recovery': 'recovery'}[defect]
        recon[key] = 'incorrect-value'
        op['reconciliation'] = json.dumps(recon)
    elif defect == 'unexpected_health':
        card['samples'][12]['verdict'] = 'verified_success'
    elif defect == 'lost_cleanup':
        card['owner_finished'] = False
    elif defect == 'observer_restarted':
        card['workers'].append({'id': 'observer-new'})
    elif defect == 'malformed_audit':
        inputs['captured']['malformed_lines'] = 1
    elif defect == 'initial_unknown':
        card['samples'][0]['verdict'] = 'unknown'
    elif defect == 'unobserved_external_fault':
        inputs['raw_samples'][7]['verification']['probes'] = []
    elif defect == 'external_after_restart':
        record['external']['finished_at'] = 1082
    elif defect == 'late_external_change':
        record['external']['requested_at'] += 4
    elif defect == 'missing_worker':
        card['workers'].pop()
    assert assess_case(**inputs)['status'] == 'failed'


def test_dispatch_barrier_never_releases_into_acknowledgement(tmp_path):
    broker = SimpleNamespace(owner='authored-owner')
    row = {'status': 'dispatching', 'owner': broker.owner, 'operation_id': 'authored-op'}
    with patch('autonomy_lab.campaign.operation_rows', return_value=[row]), \
            patch('autonomy_lab.campaign.active', side_effect=RuntimeError('window closed')):
        dispatch_barrier('before_dispatch', tmp_path, tmp_path, broker)
        assert not (tmp_path / 'dispatch-barrier.json').exists()
        with pytest.raises(RuntimeError, match='window closed'):
            dispatch_barrier('after_dispatch', tmp_path, tmp_path, broker)
        assert read(tmp_path / 'dispatch-barrier.json')['operation_id'] == 'authored-op'


def test_dispatch_barrier_refuses_unattributable_operation(tmp_path):
    with patch('autonomy_lab.campaign.operation_rows', return_value=[]):
        with pytest.raises(RuntimeError, match='identify'):
            dispatch_barrier('after_dispatch', tmp_path, tmp_path, SimpleNamespace(owner='authored'))
        assert not (tmp_path / 'dispatch-barrier.json').exists()


@pytest.mark.parametrize('missing', ['run_id', 'initial_stop_requested_at', 'repair_requested_at', 'barrier_at', 'fault_requested_at'])
def test_missing_controller_fields_produce_a_failed_assessment(missing):
    inputs = authored('unchanged')
    if missing == 'barrier_at':
        del inputs['barrier']['at']
    elif missing == 'fault_requested_at':
        del inputs['record']['fault']['requested_at']
    else:
        del inputs['record'][missing]
    assert assess_case(**inputs)['status'] == 'failed'


def test_partial_attempt_exports_failed_evaluation_without_a_barrier_or_journal(tmp_path):
    inputs = authored('unchanged')
    save(tmp_path / 'declaration.json', inputs['spec'])
    (tmp_path / 'campaign/samples').mkdir(parents=True)
    inputs['card']['owner_finished'] = False
    inputs['card']['cleanup'] = None
    inputs['card']['operations'] = []
    with patch('autonomy_lab.ambiguity.scorecard', return_value=inputs['card']):
        result = evaluate(tmp_path)
        assert result['status'] == 'failed'
        assert result['checks']['controller_completed'] is False
        assert result == evaluate(tmp_path)
