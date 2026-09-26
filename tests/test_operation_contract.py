"""Authored counterexamples for gate logic; these are not Kubernetes evidence."""

import copy
import fnmatch
import runpy

import pytest
import yaml

from autonomy_lab.broker import ActionBroker, BrokerPolicy, Proposal
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.operation_contract import (
    ARMS,
    AUTHORITY,
    CASES,
    HEARTBEAT,
    SCRATCH,
    assess,
    intervention_patch,
    repair_patch,
)


def resource(uid='authored-uid', version='10'):
    return {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {
        'namespace': 'autonomy-lab', 'name': 'inventory', 'uid': uid, 'resourceVersion': version,
        'annotations': {HEARTBEAT: 'tick-0', AUTHORITY: 'enabled'}, 'creationTimestamp': 'authored'},
        'spec': {'selector': {'app': 'inventory'}, 'ports': [
            {'name': 'http', 'port': 80, 'targetPort': 9999, 'protocol': 'TCP'}]}, 'status': {}}


def test_ci_reruns_for_every_receipted_input_and_transport_dependency():
    runner = runpy.run_path(str(ROOT / 'scripts/check_operation_contract.py'))
    workflow = yaml.load((ROOT / '.github/workflows/operation-contract.yml').read_text(),
                         Loader=yaml.BaseLoader)
    patterns = workflow['on']['pull_request']['paths']
    required = {*runner['source_receipt'](), 'src/autonomy_lab/broker.py',
                'src/autonomy_lab/bounded_http.py', 'Dockerfile', 'fixtures/expectations.json',
                'pyproject.toml', 'uv.lock', 'tests/test_operation_contract.py',
                '.github/workflows/operation-contract.yml'}
    assert all(any(fnmatch.fnmatch(path, pattern) for pattern in patterns) for path in required)


def test_comparator_is_current_broker_patch(tmp_path):
    service = resource()
    policy = BrokerPolicy('authored-run', 'autonomy-lab', 'inventory', 'authored-uid')
    broker = ActionBroker(tmp_path / 'journal.sqlite', policy, None)
    proposal = Proposal(run_id='authored-run', operation_id='authored-op', namespace='autonomy-lab',
                        service_name='inventory', service_uid='authored-uid', resource_version='10',
                        expected_target_port=9999, target_port=8080, evidence_ids=['authored'])
    patch, reason = broker._construct_patch(proposal, service)
    assert reason is None
    assert patch == repair_patch(service, 'version')


def test_patch_owns_its_snapshot_and_retains_unknown_metadata():
    service = resource()
    service['metadata']['annotations']['unknown.example/permission'] = 'deny'
    original = copy.deepcopy(service)
    patch = repair_patch(service, 'contract')
    service['spec']['selector']['app'] = 'different'
    guarded = next(p['value'] for p in patch if p['path'] == '/metadata' and p['op'] == 'test')
    assert guarded['annotations']['unknown.example/permission'] == 'deny'
    assert guarded['uid'] == original['metadata']['uid']
    assert next(p['value'] for p in patch if p['path'] == '/spec')['selector'] == {'app': 'inventory'}
    assert original['metadata']['annotations'][HEARTBEAT] == 'tick-0'


@pytest.mark.parametrize('defect', ['heartbeat', 'scope', 'target', 'scratch', 'authority', 'status'])
def test_incomplete_or_out_of_scope_snapshot_is_refused(defect):
    service = resource()
    if defect == 'heartbeat':
        del service['metadata']['annotations'][HEARTBEAT]
    elif defect == 'scope':
        service['metadata']['namespace'] = 'production'
    elif defect == 'target':
        service['spec']['ports'][0]['targetPort'] = 8080
    elif defect == 'scratch':
        service[SCRATCH] = {}
    elif defect == 'authority':
        service['metadata']['annotations'][AUTHORITY] = 'disabled'
    else:
        del service['status']
    with pytest.raises(ValueError):
        repair_patch(service, 'contract')


def authored_change(before, case):
    value = copy.deepcopy(before)
    for change in intervention_patch(case, 'authored-owner'):
        parts = [p.replace('~1', '/').replace('~0', '~') for p in change['path'].split('/')[1:]]
        parent = value
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = parts[-1]
        if change['op'] == 'remove':
            del parent[key]
        elif key == '-':
            parent.append(copy.deepcopy(change['value']))
        else:
            parent[key] = copy.deepcopy(change['value'])
    if case != 'unchanged':
        value['metadata']['resourceVersion'] = '11'
    if case == 'recreated':
        value['metadata']['uid'] = 'authored-replacement'
    return value


def event(record, *, controller=False):
    accepted = record['outcome'] == 'acknowledged'
    return {'verb': 'patch', 'stage': 'ResponseComplete',
            'user': {'username': 'kubernetes-admin' if controller
                     else 'system:serviceaccount:autonomy-lab:broker'},
            'userAgent': 'autonomy-lab-operation/' + record['operation_id']
                         + ('-intervention' if controller else ''),
            'objectRef': {'namespace': 'autonomy-lab', 'name': 'inventory', 'resource': 'services'},
            'requestObject': record['intervention'] if controller else record['patch'],
            'responseObject': record['changed'] if controller else record['after'] if accepted else {},
            'responseStatus': {'code': 200 if controller or accepted else 422}}


def authored():
    records, events = [], []
    for case in CASES:
        for arm in ARMS:
            before = resource(uid=f'authored-{case}-{arm}')
            changed = authored_change(before, case)
            accepted = case == 'unchanged' or (case == 'heartbeat_value' and arm == 'contract')
            after = copy.deepcopy(changed)
            if accepted:
                after['spec']['ports'][0]['targetPort'] = 8080
                after['metadata']['resourceVersion'] = '12'
            row = {'case': case, 'arm': arm, 'operation_id': f'authored-{case}-{arm}',
                   'owner_uid': 'authored-owner', 'before': before, 'changed': changed, 'after': after,
                   'patch': repair_patch(before, arm), 'intervention': intervention_patch(case, 'authored-owner'),
                   'started_at': 1, 'prepared_at': 2, 'changed_at': 3, 'dispatch_at': 4, 'finished_at': 5,
                   'outcome': 'acknowledged' if accepted else 'rejected', 'reason': 'api_rejected_422'}
            records.append(row)
            events.append(event(row))
            if row['intervention']:
                events.append(event(row, controller=True))
    return records, {'events': events, 'malformed_lines': 0, 'collection_closed': True}


def test_complete_authored_matrix_and_deterministic_assessment():
    records, captured = authored()
    result = assess(records, captured, 'deleted')
    assert result['status'] == 'passed', result
    assert result == assess(records, captured, 'deleted')
    assert len(result['cases']) == 30


@pytest.mark.parametrize('defect', [
    'missing_case', 'missing_audit', 'wrong_actor', 'unmatched_dispatch', 'partial_rejection',
    'heartbeat_clobbered', 'scratch_retained', 'unknown_annotation_accepted', 'missing_intervention',
    'wrong_intervention', 'refusal_unspent_version_changed', 'missing_sequence', 'wrong_request',
    'unknown_response', 'unclosed_audit', 'malformed_audit', 'missing_cleanup', 'reused_uid',
])
def test_missing_or_contradictory_evidence_fails_closed(defect):
    records, captured = copy.deepcopy(authored())
    cleanup = 'deleted'
    if defect == 'missing_case':
        records.pop()
    elif defect == 'missing_audit':
        captured['events'].pop(0)
    elif defect == 'wrong_actor':
        captured['events'][0]['user']['username'] = 'kubernetes-admin'
    elif defect == 'unmatched_dispatch':
        captured['events'].append(copy.deepcopy(captured['events'][0]))
    elif defect == 'partial_rejection':
        records[4]['after']['metadata']['annotations'][HEARTBEAT] = 'oops'
    elif defect == 'heartbeat_clobbered':
        records[3]['after']['metadata']['annotations'][HEARTBEAT] = 'tick-0'
    elif defect == 'scratch_retained':
        records[1]['after'][SCRATCH] = {}
    elif defect == 'unknown_annotation_accepted':
        records[7]['outcome'] = 'acknowledged'
    elif defect == 'missing_intervention':
        captured['events'] = [e for e in captured['events'] if not e['userAgent'].endswith('-intervention')]
    elif defect == 'wrong_intervention':
        records[7]['intervention'] = []
    elif defect == 'refusal_unspent_version_changed':
        records[4]['after']['metadata']['resourceVersion'] = '12'
    elif defect == 'missing_sequence':
        records[0]['prepared_at'] = 10
    elif defect == 'wrong_request':
        captured['events'][0]['requestObject'] = []
    elif defect == 'unknown_response':
        captured['events'][0]['responseStatus']['code'] = 503
    elif defect == 'unclosed_audit':
        captured['collection_closed'] = False
    elif defect == 'malformed_audit':
        captured['malformed_lines'] = 1
    elif defect == 'missing_cleanup':
        cleanup = 'failed'
    else:
        records[-1]['changed']['metadata']['uid'] = records[-1]['before']['metadata']['uid']
    assert assess(records, captured, cleanup)['status'] == 'failed'
