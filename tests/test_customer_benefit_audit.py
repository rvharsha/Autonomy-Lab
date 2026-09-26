"""Authored measurement and controller-boundary tests; no live outcomes."""

import copy
from collections import Counter

import pytest

from autonomy_lab.customer_benefit import complete_verification
from autonomy_lab.customer_benefit_audit import controller_patch, expected_effect
from autonomy_lab.operation_contract import AUTHORITY, HEARTBEAT
from autonomy_lab.procedures import Refused
from autonomy_lab.verifier import evaluate_snapshot, load_expectations


def measurement(*, healthy=False):
    expectations = load_expectations()
    snapshot = {'quote_control': {'kind': 'response', 'status_code': 200},
        'inventory_control': {'kind': 'response', 'status_code': 200},
        'database': {'kind': 'rows', 'rows': copy.deepcopy(expectations['products'])},
        'service': {'kind': 'resource', 'resource': {'metadata': {'name': 'inventory'},
            'spec': {'selector': {'app': 'inventory'}, 'ports': [
                {'name': 'http', 'port': 80, 'protocol': 'TCP', 'targetPort': 8080 if healthy else 9999}]}}},
        'quotes': [{'case_id': c['id'], 'kind': 'response', 'status_code': c['status_code'] if healthy else 503,
                    **({'body': c['body']} if healthy and 'body' in c else {})} for c in expectations['quotes']]}
    return {'window_seconds': 1, 'expectation_version': expectations['version'],
        'started_at': '2026-09-26T00:00:00Z', 'finished_at': '2026-09-26T00:00:02Z',
        'probes': [{'index': index, 'offset_seconds': offset, 'observations': copy.deepcopy(snapshot)}
                   for index, offset in enumerate((0, 1))]}


def summarize(value):
    for p in value['probes']:
        p.update(evaluate_snapshot(p['observations'], load_expectations()))
    counts = Counter(p['verdict'] for p in value['probes'])
    value.update(verdict='verified_failure' if counts['verified_failure'] else 'indeterminate' if counts['indeterminate'] else 'verified_success',
        reasons=list(dict.fromkeys(r for p in value['probes'] for r in p['reasons'])),
        counts={'total': len(value['probes']), **{k: counts[k] for k in ('verified_success', 'verified_failure', 'indeterminate')}})
    return value


@pytest.mark.parametrize('healthy', [True, False])
def test_complete_health_and_complete_routing_failure_are_both_measurable(healthy):
    assert complete_verification(summarize(measurement(healthy=healthy)))['probes'] == 2


@pytest.mark.parametrize('defect', ['database', 'corpus', 'controls', 'damage', 'summary', 'window'])
def test_known_customer_failure_never_masks_unavailable_or_damaged_evidence(defect):
    value = measurement()
    for p in value['probes']:
        snapshot = p['observations']
        if defect == 'database':
            snapshot['database'] = {'kind': 'error'}
        elif defect == 'corpus':
            snapshot['quotes'].pop()
        elif defect == 'controls':
            snapshot.pop('inventory_control')
        elif defect == 'damage':
            snapshot['database']['rows'][0]['stock'] += 1
    summarize(value)
    assert value['verdict'] == 'verified_failure'
    if defect == 'summary':
        value['counts']['total'] += 1
    elif defect == 'window':
        value['finished_at'] = value['started_at']
    with pytest.raises(Refused):
        complete_verification(value)


def test_controller_metadata_changes_preserve_other_fields_and_require_original_version():
    before = {'metadata': {'uid': 'authored', 'resourceVersion': '10', 'name': 'inventory',
        'annotations': {'unrelated': 'kept'}, 'labels': {'app': 'inventory'}},
        'spec': {'ports': [{'name': 'http', 'targetPort': 8080}]}}
    original = copy.deepcopy(before)
    fixture = controller_patch(before, 'fixture')
    assert fixture[:2] == [{'op': 'test', 'path': '/metadata/uid', 'value': 'authored'},
                          {'op': 'test', 'path': '/metadata/resourceVersion', 'value': '10'}]
    assert fixture[-1]['value'] == {'unrelated': 'kept', HEARTBEAT: 'initial', AUTHORITY: 'enabled'}
    for kind in ('fixture', 'heartbeat', 'protected'):
        value = expected_effect({**before, 'metadata': {**before['metadata'], 'annotations': fixture[-1]['value']}}, kind)
        assert value['spec'] == before['spec'] and value['metadata']['annotations']['unrelated'] == 'kept'
    assert before == original
    with pytest.raises(Refused):
        controller_patch(before, 'external_restore')
