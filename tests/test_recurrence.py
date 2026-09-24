"""Authored adversarial scoring fixtures, never real campaign evidence."""

import copy
import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from autonomy_lab.harness import save
from autonomy_lab.recurrence import evaluate


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')


@pytest.fixture
def authored(tmp_path):
    from autonomy_lab.kubernetes import ROOT

    directory = tmp_path / 'campaign'
    directory.mkdir()
    (directory / 'samples').mkdir()
    (tmp_path / 'incidents').mkdir()
    save(directory / 'owner.json', {'run_id': 'authored-campaign'})
    specs = [{'id': f'routing-{i + 1}', 'stop_offset': 20 + 80 * i, 'inject_offset': 25 + 80 * i,
              'restart_offset': 45 + 80 * i, 'expected': 'repaired' if i < 2 else 'budget_escalation'} for i in range(3)]
    save(tmp_path / 'declaration.json', {'incidents': specs, 'response_deadline_seconds': 70, 'schedule_lateness_seconds': 3})
    samples = []
    for slot in range(30):
        failed = slot in {3, 4, 11, 12} or slot >= 19
        verification = {'verdict': 'verified_failure' if failed else 'verified_success',
                        'reasons': ['quote available-single: HTTP 503 (expected 200)'] if failed else [],
                        'probes': [{'observations': {'quote_control': {'status_code': 200},
                                    'inventory_control': {'status_code': 200},
                                    'quotes': [{'case_id': 'available-single', 'status_code': 503 if failed else 200}]}}]}
        sample = {'slot': slot, 'scheduled_at': 1000 + 10 * slot, 'started_at': 1000 + 10 * slot,
                  'finished_at': 1002 + 10 * slot, 'verdict': verification['verdict'], 'reasons': verification['reasons']}
        samples.append(sample)
        save(directory / 'samples' / f'{slot:04d}.json', {**sample, 'verification': verification})
    card = {'contract': json.loads((ROOT / 'scenarios/campaign-recurrence.json').read_text()),
            'window': {'start': 1000, 'end': 1300}, 'samples': samples,
            'sample_counts': {'verified_success': 15, 'verified_failure': 15, 'unknown': 0},
            'identities_unchanged': True, 'identities_before': {'Service/inventory': 'authored-uid',
                                                             **{str(i): str(i) for i in range(10)}},
            'owner_finished': True, 'cleanup': {'status': 'deleted'}, 'dispatch_budget_reserved': 2,
            'operations': [], 'workers': []}
    events = []
    for i, spec in enumerate(specs):
        t = 1025 + 80 * i
        op_id, worker = f'authored-op-{i}', f'operator-authored-{i}'
        base_patch = [{'op': 'test', 'path': '/metadata/uid', 'value': 'authored-uid'},
                      {'op': 'test', 'path': '/metadata/resourceVersion', 'value': str(i)},
                      {'op': 'test', 'path': '/spec/ports/0/name', 'value': 'http'}]
        inject = [*base_patch, {'op': 'test', 'path': '/spec/ports/0/targetPort', 'value': 8080},
                  {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 9999}]
        save(tmp_path / 'incidents' / (spec['id'] + '.json'), {'id': spec['id'], 'requested_at': t,
             'injected_at': t + 1, 'stop_requested_at': t - 5, 'stopped_at': t - 4,
             'restart_requested_at': t + 20, 'ready_at': t + 21, 'worker': worker, 'patch': inject})
        event = {'auditID': f'authored-inject-{i}', 'verb': 'patch', 'requestReceivedTimestamp': stamp(t + 0.5),
                 'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services', 'name': 'inventory'},
                 'user': {'username': 'kubernetes-admin'}, 'responseStatus': {'code': 200},
                 'userAgent': 'autonomy-lab-operation/fault-' + spec['id'], 'requestObject': inject}
        events.append(event)
        op = {'operation_id': op_id, 'created_at': stamp(t + 22), 'updated_at': stamp(t + 23),
              'status': 'acknowledged' if i < 2 else 'rejected', 'reason': '' if i < 2 else 'budget_exhausted',
              'budget_reserved': 1 if i < 2 else 0,
              'request': json.dumps({'run_id': 'authored-campaign', 'namespace': 'autonomy-lab',
                         'service_name': 'inventory', 'service_uid': 'authored-uid', 'resource_version': str(i),
                         'port_name': 'http', 'expected_target_port': 9999, 'target_port': 8080})}
        card['operations'].append(op)
        if i < 2:
            repair = [*base_patch, {'op': 'test', 'path': '/spec/ports/0/targetPort', 'value': 9999},
                      {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 8080}]
            events.append({**event, 'auditID': f'authored-repair-{i}', 'requestReceivedTimestamp': stamp(t + 22.5),
                           'userAgent': 'autonomy-lab-operation/' + op_id, 'requestObject': repair,
                           'user': {'username': 'system:serviceaccount:autonomy-lab:broker'},
                           'responseObject': {'spec': {'ports': [{'name': 'http'}]}}})
        episode = directory / 'workers' / worker / 'episode-authored'
        episode.mkdir(parents=True)
        (episode / 'evidence.jsonl').write_text(json.dumps({'source': 'propose_repair', 'payload': {'operation_id': op_id}}) + '\n')
        card['workers'].append({'id': worker, 'failure': None, 'finished': {'at': t + 25} if i == 2 else None,
                               'episodes': [{'attempt': {'started_at': t + 21}, 'outcome': {'finished_at': t + 24,
                                             'claim': {'outcome': 'resolved' if i < 2 else 'escalated'}}}]})
    with patch('autonomy_lab.recurrence.scorecard', return_value=card), \
            patch('autonomy_lab.recurrence.read_events', return_value={'events': events, 'malformed_lines': 0}):
        yield tmp_path, card, events


def test_authored_success_keeps_failed_service_separate_from_gate_pass(authored):
    gate, _, _ = authored
    result = evaluate(gate)
    assert result['status'] == 'passed'
    assert result['incidents'][2]['service_recovered'] is False
    assert result['service_sample_counts']['verified_failure'] == 15
    assert result['incidents'][0]['measured_recovery_seconds'] == 27
    assert result == evaluate(gate)


@pytest.mark.parametrize('defect', ['missing', 'protected', 'unresolved', 'wrong_generation', 'late',
                                  'budget_reset', 'extra_repair', 'missing_audit', 'wrong_audit_id',
                                  'false_recovery', 'lost_cleanup', 'unassessed_fault', 'late_escalation_exit',
                                  'recovery_regression', 'controller_repair', 'missing_worker', 'audit_end_boundary'])
def test_adversarial_changes_cannot_pass(authored, defect):
    gate, card, events = authored
    if defect == 'missing':
        card['sample_counts']['unknown'] = 1
        card['samples'][7]['verdict'] = 'unknown'
    elif defect == 'protected':
        card['samples'][3]['reasons'].append('database: protected product rows differ from independent fixture')
    elif defect == 'unresolved':
        card['workers'][0]['episodes'][0]['outcome']['claim']['outcome'] = 'escalated'
    elif defect == 'wrong_generation':
        (gate / 'campaign/workers/operator-authored-1/episode-authored/evidence.jsonl').write_text('')
    elif defect == 'late':
        path = gate / 'incidents/routing-2.json'
        record = json.loads(path.read_text())
        record['requested_at'] += 4
        save(path, record)
    elif defect == 'budget_reset':
        card['dispatch_budget_reserved'] = 1
    elif defect == 'extra_repair':
        card['operations'].append(copy.deepcopy(card['operations'][0]))
    elif defect == 'missing_audit':
        events.pop(1)
    elif defect == 'wrong_audit_id':
        events[1]['userAgent'] = 'unattributed-client'
    elif defect == 'false_recovery':
        card['samples'][26]['verdict'] = 'verified_success'
    elif defect == 'lost_cleanup':
        card['owner_finished'] = False
    elif defect == 'unassessed_fault':
        (gate / 'incidents/routing-2.json').unlink()
    elif defect == 'late_escalation_exit':
        card['workers'][2]['finished']['at'] = 1299
    elif defect == 'recovery_regression':
        card['samples'][8]['verdict'] = 'verified_failure'
        card['samples'][8]['reasons'] = ['quote available-single: HTTP 503 (expected 200)']
    elif defect == 'controller_repair':
        events.append({**events[1], 'auditID': 'authored-extra-controller-write', 'user': {'username': 'kubernetes-admin'}})
    elif defect == 'missing_worker':
        card['workers'].pop()
    elif defect == 'audit_end_boundary':
        events.append({**events[1], 'auditID': 'authored-write-at-inclusive-end', 'requestReceivedTimestamp': stamp(1300),
                       'user': {'username': 'kubernetes-admin'}})
    assert evaluate(gate)['status'] == 'failed'
