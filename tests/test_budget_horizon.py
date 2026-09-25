"""Authored counterexamples for the evaluator, never live experiment outcomes."""

import copy
import json
from datetime import UTC, datetime

import pytest

from autonomy_lab.budget_horizon import ARMS, assess_audit, declaration, first_episode_completed_by
from autonomy_lab.conflict import annotation_patch, repair_patch


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


@pytest.fixture
def audit_case():
    record = {'attempts': []}
    events = []
    for index, name in enumerate(('fault', 'external_restore', 'second_fault')):
        before, after = (9999, 8080) if name == 'external_restore' else (8080, 9999)
        patch = repair_patch({'service_uid': 'service-1', 'resource_version': str(index + 1),
                              'expected_target_port': before, 'target_port': after})
        record[name] = {'patch': patch, 'requested_at': 10 + index * 10,
                        'finished_at': 12 + index * 10, 'resource_version': str(index + 2)}
        events.append({'auditID': 'controller-' + name, 'stage': 'ResponseComplete', 'verb': 'patch',
                       'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services', 'name': 'inventory'},
                       'user': {'username': 'kubernetes-admin'},
                       'userAgent': 'autonomy-lab-operation/ambiguity-' + name,
                       'requestObject': patch, 'responseStatus': {'code': 200},
                       'responseObject': {'metadata': {'resourceVersion': str(index + 2)}},
                       'requestReceivedTimestamp': stamp(10.1 + index * 10),
                       'stageTimestamp': stamp(10.2 + index * 10)})
    return ({'window': {'start': 0, 'end': 210}, 'operations': [],
             'identities_before': {'Service/inventory': 'service-1'}},
            {'collection_closed': True, 'malformed_lines': 0, 'events': events}, record)


def test_policies_share_authority_calendar_and_only_declared_choices_differ():
    contracts = [declaration(arm)['contract'] for arm in ARMS]
    policies = [json.loads(c.pop('procedure_program')) for c in contracts]
    assert contracts[0] == contracts[1] == contracts[2]
    assert contracts[0]['max_dispatches'] == 2 and contracts[0]['duration_seconds'] == 210
    assert policies[0] == {**policies[1], 'conditional_rejection': 'refresh'}
    assert policies[2] == {**policies[1], 'repairable_routing': 'escalate'}


def test_control_only_audit_does_not_invent_broker_activity(audit_case):
    assert assess_audit(*audit_case) == []


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'actor', 'verb', 'scope', 'patch', 'late', 'result'])
def test_declared_controller_actions_require_exact_independent_api_evidence(audit_case, change):
    card, audit, record = audit_case
    event = audit['events'][0]
    if change == 'missing':
        audit['events'].pop(0)
    elif change == 'duplicate':
        audit['events'].append(copy.deepcopy(event))
    elif change == 'actor':
        event['user']['username'] = 'unknown'
    elif change == 'verb':
        event['verb'] = 'delete'
    elif change == 'scope':
        event['objectRef']['name'] = 'other'
    elif change == 'patch':
        event['requestObject'] = []
    elif change == 'late':
        event['stageTimestamp'] = stamp(15)
    elif change == 'result':
        event['responseObject']['metadata']['resourceVersion'] = 'unrelated'
    with pytest.raises(ValueError):
        assess_audit(card, audit, record)


def test_tampered_controller_record_cannot_authorize_extra_field_change(audit_case):
    card, audit, record = audit_case
    record['fault']['patch'].append({'op': 'replace', 'path': '/spec/selector', 'value': {}})
    with pytest.raises(ValueError, match='declared routing change'):
        assess_audit(card, audit, record)


@pytest.mark.parametrize('identity,resource,verb,allowed', [
    ('system:serviceaccount:kube-system:endpoint-controller', 'endpoints', 'update', True),
    ('system:serviceaccount:kube-system:endpointslice-controller', 'endpointslices', 'update', True),
    ('system:serviceaccount:kube-system:unknown', 'endpoints', 'update', False),
    ('system:serviceaccount:kube-system:endpoint-controller', 'secrets', 'update', False),
    ('system:serviceaccount:kube-system:endpoint-controller', 'endpoints', 'delete', False),
    ('system:serviceaccount:autonomy-lab:broker', 'endpoints', 'update', False),
])
def test_native_controller_exception_cannot_hide_other_writes(audit_case, identity, resource, verb, allowed):
    card, audit, record = audit_case
    audit['events'].append({'auditID': 'extra', 'verb': verb,
                            'objectRef': {'namespace': 'autonomy-lab', 'resource': resource},
                            'user': {'username': identity}, 'requestReceivedTimestamp': stamp(30)})
    if allowed:
        assert assess_audit(card, audit, record) == []
    else:
        with pytest.raises(ValueError):
            assess_audit(card, audit, record)


@pytest.mark.parametrize('reason,reserved', [('budget_exhausted', 1), ('intent_recorded', 0),
                                          ('dispatch_authorization_refused', 0)])
def test_unmatched_operation_cannot_hide_as_budget_refusal(audit_case, reason, reserved):
    card, audit, record = audit_case
    card['operations'].append({'status': 'rejected', 'reason': reason, 'budget_reserved': reserved,
                               'request': '{}', 'operation_id': 'op-1'})
    with pytest.raises((ValueError, KeyError)):
        assess_audit(card, audit, record)


@pytest.fixture
def rejected_dispatch(audit_case):
    card, audit, record = audit_case
    before = {'metadata': {'uid': 'service-1', 'resourceVersion': '2'},
              'spec': {'ports': [{'name': 'http', 'targetPort': 9999}]}}
    changed = copy.deepcopy(before)
    changed['metadata'].update(resourceVersion='3', annotations={'autonomy-lab/conditional-conflict': 'op-1'})
    change_patch = annotation_patch(before, 'op-1')
    attempt = {'phase': 'first', 'operation_id': 'op-1', 'before': before,
               'barrier': {'at': 13, 'operation_id': 'op-1'}, 'release_requested_at': 13.9,
               'change': {'patch': change_patch, 'requested_at': 13.1, 'finished_at': 13.3},
               'changed_service': changed}
    record['attempts'].append(attempt)
    common = {'stage': 'ResponseComplete', 'verb': 'patch',
              'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services', 'name': 'inventory'}}
    audit['events'].append({**common, 'auditID': 'conflict', 'user': {'username': 'kubernetes-admin'},
                            'userAgent': 'autonomy-lab-operation/horizon-conflict-op-1',
                            'requestObject': change_patch, 'responseStatus': {'code': 200},
                            'responseObject': changed, 'requestReceivedTimestamp': stamp(13.15),
                            'stageTimestamp': stamp(13.2)})
    request = {'operation_id': 'op-1', 'service_uid': 'service-1', 'resource_version': '2',
               'expected_target_port': 9999, 'target_port': 8080}
    op = {'operation_id': 'op-1', 'status': 'rejected', 'reason': 'api_rejected_422',
          'budget_reserved': 1, 'request': json.dumps(request), 'created_at': stamp(12.5),
          'updated_at': stamp(14.9), 'result': 'null', 'reconciliation': None}
    card['operations'].append(op)
    audit['events'].append({**common, 'auditID': 'dispatch',
                            'user': {'username': 'system:serviceaccount:autonomy-lab:broker'},
                            'userAgent': 'autonomy-lab-operation/op-1',
                            'requestObject': repair_patch(request), 'responseStatus': {'code': 422},
                            'requestReceivedTimestamp': stamp(14), 'stageTimestamp': stamp(14.1)})
    return card, audit, record


def test_actual_rejected_dispatch_is_retained_and_spent(rejected_dispatch):
    assert assess_audit(*rejected_dispatch) == rejected_dispatch[0]['operations']


@pytest.mark.parametrize('shift', [-5, 7, 30])
def test_first_incident_contention_cannot_move_outside_its_calendar(rejected_dispatch, shift):
    card, audit, record = rejected_dispatch
    attempt = record['attempts'][0]
    attempt['barrier']['at'] += shift
    attempt['release_requested_at'] += shift
    for key in ('requested_at', 'finished_at'):
        attempt['change'][key] += shift
    for key in ('created_at', 'updated_at'):
        op = card['operations'][0]
        op[key] = stamp(datetime.fromisoformat(op[key]).timestamp() + shift)
    for event in audit['events'][-2:]:
        for key in ('requestReceivedTimestamp', 'stageTimestamp'):
            event[key] = stamp(datetime.fromisoformat(event[key]).timestamp() + shift)
    with pytest.raises(ValueError, match='incident calendar'):
        assess_audit(card, audit, record)


def test_dispatch_response_cannot_cross_controller_recovery(rejected_dispatch):
    card, audit, record = rejected_dispatch
    card['operations'][0]['updated_at'] = stamp(20.1)
    audit['events'][-1]['stageTimestamp'] = stamp(20)
    with pytest.raises(ValueError, match='incident calendar'):
        assess_audit(card, audit, record)


def test_second_phase_label_cannot_exempt_a_first_incident_write_from_contention(rejected_dispatch):
    card, audit, record = rejected_dispatch
    attempt = record['attempts'][0]
    attempt['phase'] = 'second'
    del attempt['change']
    audit['events'].pop(-2)
    with pytest.raises(ValueError, match='incident calendar'):
        assess_audit(card, audit, record)


def test_unknown_incident_phase_cannot_exempt_a_dispatch_from_contention(rejected_dispatch):
    card, audit, record = rejected_dispatch
    record['attempts'][0]['phase'] = 'undeclared'
    with pytest.raises(ValueError, match='Unknown incident phase'):
        assess_audit(card, audit, record)


@pytest.mark.parametrize('change', ['no_api', 'late_conflict', 'late_release', 'wrong_version',
                                   'nonnull_result', 'reconciled', 'duplicate_barrier', 'early_journal'])
def test_false_conditional_rejection_evidence_is_refused(rejected_dispatch, change):
    card, audit, record = rejected_dispatch
    op = card['operations'][0]
    attempt = record['attempts'][0]
    if change == 'no_api':
        audit['events'].pop()
    elif change == 'late_conflict':
        attempt['change']['finished_at'] = 14.01
    elif change == 'late_release':
        attempt['release_requested_at'] = 14.01
    elif change == 'wrong_version':
        attempt['before']['metadata']['resourceVersion'] = 'wrong'
    elif change == 'nonnull_result':
        op['result'] = '{}'
    elif change == 'reconciled':
        op['reconciliation'] = '{}'
    elif change == 'duplicate_barrier':
        record['attempts'].append(copy.deepcopy(attempt))
    elif change == 'early_journal':
        op['updated_at'] = stamp(14.05)
    with pytest.raises(ValueError):
        assess_audit(card, audit, record)


def test_first_episode_deadline_uses_recorded_chronology_not_uuid_filename():
    worker = {'episodes': [
        {'id': 'episode-aaa', 'attempt': {'started_at': 50}, 'outcome': {'finished_at': 55}},
        {'id': 'episode-zzz', 'attempt': {'started_at': 10}, 'outcome': {'finished_at': 15}},
    ]}
    assert first_episode_completed_by(worker, 20)


@pytest.mark.parametrize('first_outcome', [None, {'finished_at': 21}])
def test_a_later_episode_cannot_hide_a_missing_or_late_first_completion(first_outcome):
    worker = {'episodes': [
        {'id': 'episode-aaa', 'attempt': {'started_at': 12}, 'outcome': {'finished_at': 14}},
        {'id': 'episode-zzz', 'attempt': {'started_at': 10}, 'outcome': first_outcome},
    ]}
    assert not first_episode_completed_by(worker, 20)


def test_empty_episode_population_cannot_satisfy_a_response_deadline():
    assert not first_episode_completed_by({'episodes': []}, 20)


@pytest.mark.parametrize('outcome', [None, {'finished_at': 21}])
def test_tied_earliest_attempts_cannot_depend_on_filename_order(outcome):
    episodes = [
        {'attempt': {'started_at': 10}, 'outcome': {'finished_at': 15}},
        {'attempt': {'started_at': 10}, 'outcome': outcome},
    ]
    assert not first_episode_completed_by({'episodes': episodes}, 20)
    assert not first_episode_completed_by({'episodes': episodes[::-1]}, 20)


def test_tied_earliest_attempts_must_all_complete_by_deadline():
    assert first_episode_completed_by({'episodes': [
        {'attempt': {'started_at': 10}, 'outcome': {'finished_at': 15}},
        {'attempt': {'started_at': 10}, 'outcome': {'finished_at': 20}},
    ]}, 20)


@pytest.mark.parametrize('value', [None, True, '10', float('nan'), float('inf')])
@pytest.mark.parametrize('field', ['start', 'finish', 'deadline'])
def test_malformed_single_episode_chronology_never_qualifies(value, field):
    episode = {'attempt': {'started_at': 10}, 'outcome': {'finished_at': 15}}
    deadline = 20
    if field == 'start':
        episode['attempt']['started_at'] = value
    elif field == 'finish':
        episode['outcome']['finished_at'] = value
    else:
        deadline = value
    with pytest.raises(ValueError):
        first_episode_completed_by({'episodes': [episode]}, deadline)


def test_completion_cannot_predate_its_attempt():
    with pytest.raises(ValueError):
        first_episode_completed_by({'episodes': [
            {'attempt': {'started_at': 10}, 'outcome': {'finished_at': 9}},
        ]}, 20)
