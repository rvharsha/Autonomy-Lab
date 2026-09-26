"""Experimental patch construction and offline API gate; not a broker policy.

The feasibility runner and explicitly selected durable contract use this module.
The trusted snapshot is an API
observation, never a model-authored permission or arbitrary patch template.
"""

from __future__ import annotations

import copy

HEARTBEAT = 'autonomy-lab/contract-heartbeat'
AUTHORITY = 'autonomy-lab/authority'
SCRATCH = 'autonomyLabContractScratch'
CASES = (
    'unchanged', 'heartbeat_value', 'heartbeat_removed', 'annotation_added',
    'authority_changed', 'authority_removed', 'label_added', 'owner_added',
    'finalizer_added', 'selector_changed', 'protocol_changed', 'port_changed',
    'port_added', 'already_repaired', 'recreated',
)
ARMS = ('version', 'contract')


def pointer(value):
    return value.replace('~', '~0').replace('/', '~1')


def normalized_metadata(metadata):
    value = copy.deepcopy(metadata)
    value['resourceVersion'] = '<current-version>'
    value['managedFields'] = []
    value['annotations'][HEARTBEAT] = '<current-heartbeat>'
    return value


def visible_resource(service):
    """Only server bookkeeping is excluded from persisted-state comparison."""
    value = copy.deepcopy(service)
    for key in ('resourceVersion', 'managedFields'):
        value.get('metadata', {}).pop(key, None)
    return value


def repair_patch(snapshot, arm):
    """Build once from a trusted observation, before any intervention."""
    if arm not in ARMS:
        raise ValueError('Unknown arm')
    metadata = snapshot['metadata']
    port = {'name': 'http', 'port': 80, 'targetPort': 9999, 'protocol': 'TCP'}
    if (snapshot.get('apiVersion') != 'v1' or snapshot.get('kind') != 'Service'
            or metadata.get('namespace') != 'autonomy-lab'
            or metadata.get('name') != 'inventory'
            or not isinstance(metadata.get('uid'), str) or not metadata['uid']
            or not isinstance(metadata.get('resourceVersion'), str) or not metadata['resourceVersion']
            or not isinstance(metadata.get('annotations', {}).get(HEARTBEAT), str)
            or metadata.get('annotations', {}).get(AUTHORITY) != 'enabled'
            or snapshot.get('spec', {}).get('selector') != {'app': 'inventory'}
            or snapshot['spec'].get('ports') != [port]
            or 'status' not in snapshot or SCRATCH in snapshot):
        raise ValueError('Snapshot outside frozen feasibility scope')
    if arm == 'version':
        return [
            {'op': 'test', 'path': '/metadata/uid', 'value': metadata['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': metadata['resourceVersion']},
            {'op': 'test', 'path': '/spec/ports/0/name', 'value': 'http'},
            {'op': 'test', 'path': '/spec/ports/0/targetPort', 'value': 9999},
            {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 8080},
        ]
    # The copy holds the API's current metadata, not the stale observation. A
    # successful move restores it byte-for-JSON-value before the actual repair.
    # Failed tests abort the whole PATCH, including the temporary normalization.
    return [
        *({'op': 'test', 'path': '/' + key, 'value': copy.deepcopy(snapshot[key])}
          for key in ('apiVersion', 'kind', 'spec', 'status')),
        {'op': 'copy', 'from': '/metadata', 'path': '/' + SCRATCH},
        {'op': 'replace', 'path': '/metadata/resourceVersion', 'value': '<current-version>'},
        {'op': 'add', 'path': '/metadata/managedFields', 'value': []},
        # The pinned API's JSON Patch object replacement accepts a missing key.
        # Remove explicitly requires presence; restore from the saved metadata
        # after comparison so the latest heartbeat value is never overwritten.
        {'op': 'remove', 'path': '/metadata/annotations/' + pointer(HEARTBEAT)},
        {'op': 'add', 'path': '/metadata/annotations/' + pointer(HEARTBEAT),
         'value': '<current-heartbeat>'},
        {'op': 'test', 'path': '/metadata', 'value': normalized_metadata(metadata)},
        {'op': 'move', 'from': '/' + SCRATCH, 'path': '/metadata'},
        {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 8080},
    ]


def intervention_patch(case, owner_uid):
    """Controller-only interventions; the patch builder never receives the case."""
    annotation = '/metadata/annotations/'
    changes = {
        'heartbeat_value': ('replace', annotation + pointer(HEARTBEAT), 'tick-1'),
        'heartbeat_removed': ('remove', annotation + pointer(HEARTBEAT), None),
        'annotation_added': ('add', annotation + pointer('unknown.example/authority'), 'deny'),
        'authority_changed': ('replace', annotation + pointer(AUTHORITY), 'disabled'),
        'authority_removed': ('remove', annotation + pointer(AUTHORITY), None),
        'label_added': ('add', '/metadata/labels', {'unknown.example/authority': 'deny'}),
        'owner_added': ('add', '/metadata/ownerReferences', [
            {'apiVersion': 'v1', 'kind': 'ConfigMap', 'name': 'database-init', 'uid': owner_uid}]),
        'finalizer_added': ('add', '/metadata/finalizers', ['autonomy-lab/hold']),
        'selector_changed': ('replace', '/spec/selector', {'app': 'quote'}),
        'protocol_changed': ('replace', '/spec/ports/0/protocol', 'UDP'),
        'port_changed': ('replace', '/spec/ports/0/port', 81),
        'port_added': ('add', '/spec/ports/-',
                       {'name': 'metrics', 'port': 9090, 'targetPort': 9090, 'protocol': 'TCP'}),
        'already_repaired': ('replace', '/spec/ports/0/targetPort', 8080),
    }
    if case in ('unchanged', 'recreated'):
        return []
    op, path, value = changes[case]
    return [{'op': op, 'path': path, **({'value': value} if op != 'remove' else {})}]


def assess(records, captured, cleanup):
    """Closed-cohort assessment from retained observations and independent audit."""
    identities = [r.get('before', {}).get('metadata', {}).get('uid') for r in records]
    checks = {'complete_matrix': [(r.get('case'), r.get('arm')) for r in records]
              == [(case, arm) for case in CASES for arm in ARMS],
              'fresh_identities': all(isinstance(uid, str) and uid for uid in identities)
              and len(set(identities)) == len(CASES) * len(ARMS),
              'audit_complete': captured.get('malformed_lines') == 0
              and captured.get('collection_closed') is True,
              'cleanup': cleanup == 'deleted'}
    events = captured.get('events', [])
    broker_events = [e for e in events if e.get('user', {}).get('username')
                     == 'system:serviceaccount:autonomy-lab:broker'
                     and e.get('verb') in ('patch', 'update', 'create', 'delete', 'deletecollection')]
    checks['one_dispatch_per_case'] = len(broker_events) == len(CASES) * len(ARMS)
    rows = []
    for record in records:
        label = str(record.get('case')) + '/' + str(record.get('arm'))
        try:
            case, arm = record['case'], record['arm']
            before, changed, after = (record[key] for key in ('before', 'changed', 'after'))
            accepted = case == 'unchanged' or (arm == 'contract' and case == 'heartbeat_value')
            expected = copy.deepcopy(changed)
            if accepted:
                expected['spec']['ports'][0]['targetPort'] = 8080
            matching = [e for e in broker_events if e.get('userAgent')
                        == 'autonomy-lab-operation/' + record['operation_id']]
            api = matching[0] if len(matching) == 1 else {}
            response = api.get('responseObject', {})
            code = api.get('responseStatus', {}).get('code')
            control_patch = intervention_patch(case, record['owner_uid'])
            control_events = [e for e in events if e.get('userAgent')
                              == 'autonomy-lab-operation/' + record['operation_id'] + '-intervention'
                              and e.get('verb') == 'patch']
            if control_patch:
                control = control_events[0] if len(control_events) == 1 else {}
                intervention_proved = (
                    len(control_events) == 1
                    and control.get('user', {}).get('username') == 'kubernetes-admin'
                    and control.get('requestObject') == control_patch
                    and control.get('responseStatus', {}).get('code') == 200
                    and visible_resource(control.get('responseObject', {})) == visible_resource(changed)
                    and control.get('objectRef', {}).get('namespace') == 'autonomy-lab'
                    and control.get('objectRef', {}).get('name') == 'inventory'
                    and control.get('objectRef', {}).get('resource') == 'services')
            elif case == 'unchanged':
                intervention_proved = before == changed and not control_events
            else:
                # A replacement must itself meet the initial fixture semantics,
                # rather than count a missing or arbitrarily different object.
                repair_patch(changed, arm)
                intervention_proved = not control_events
            row_checks = {
                'completed': not record.get('error_type'),
                'frozen_request': record['patch'] == repair_patch(before, arm),
                'frozen_intervention': record['intervention'] == control_patch and intervention_proved,
                'sequence': record['started_at'] <= record['prepared_at'] <= record['changed_at']
                    <= record['dispatch_at'] <= record['finished_at'],
                'intervention_identity': (before['metadata']['uid'] != changed['metadata']['uid'])
                    and changed['metadata']['uid'] not in identities
                    if case == 'recreated' else (before['metadata']['uid'] == changed['metadata']['uid']),
                'version_changed': (before['metadata']['resourceVersion'] == changed['metadata']['resourceVersion'])
                    == (case == 'unchanged'),
                'expected_response': record['outcome'] == ('acknowledged' if accepted else 'rejected'),
                'exact_persisted_effect': visible_resource(after) == visible_resource(expected),
                'no_scratch': SCRATCH not in after,
                'version_effect': (after['metadata']['resourceVersion'] != changed['metadata']['resourceVersion'])
                    == accepted,
                'one_attributed_request': len(matching) == 1,
                'audit_request': api.get('requestObject') == record['patch']
                    and api.get('objectRef', {}).get('namespace') == 'autonomy-lab'
                    and api.get('objectRef', {}).get('name') == 'inventory'
                    and api.get('objectRef', {}).get('resource') == 'services'
                    and api.get('verb') == 'patch',
                'audit_response': (code == 200 and visible_resource(response) == visible_resource(after))
                    if accepted else (code == 422 and record.get('reason') == 'api_rejected_422'),
            }
        except (KeyError, TypeError, ValueError, IndexError):
            row_checks = {'complete_evidence': False}
        checks[label] = all(row_checks.values())
        rows.append({'case': record.get('case'), 'arm': record.get('arm'), 'checks': row_checks,
                     'status': 'passed' if all(row_checks.values()) else 'failed'})
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
            'cases': rows, 'scope': 'API feasibility only; no customer-benefit or admission claim'}
