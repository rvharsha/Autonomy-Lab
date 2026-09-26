"""Frozen durable-contract development gate, assessed from retained evidence."""

import copy
from datetime import datetime

from autonomy_lab.audit import assess as assess_audit
from autonomy_lab.durable_contract import LEGACY, PRECISE, patch_for_binding, validate_binding
from autonomy_lab.operation_contract import (
    AUTHORITY,
    HEARTBEAT,
    SCRATCH,
    pointer,
    repair_patch,
    visible_resource,
)
from autonomy_lab.verifier import evaluate_snapshot, load_expectations

CASES = ('unchanged', 'heartbeat', 'restart_snapshot', 'contract_change_intent',
         'contract_change_snapshot', 'lost_ack', 'kill_after_dispatch', 'withdrawn_aba',
         'budget_exhausted', 'budget_revoked', 'annotations_removed', 'mixed_change',
         'port_layout_changed', 'deleting', 'authority_aba', 'backend_changed')
ARMS = (LEGACY, PRECISE)
KILLS = {'restart_snapshot': 'before_dispatch', 'contract_change_intent': 'after_intent',
         'contract_change_snapshot': 'before_dispatch', 'kill_after_dispatch': 'after_dispatch'}


def interventions(case):
    heartbeat = {'op': 'replace', 'path': '/metadata/annotations/' + pointer(HEARTBEAT), 'value': 'later'}
    authority = {'op': 'replace', 'path': '/metadata/annotations/' + pointer(AUTHORITY), 'value': 'disabled'}
    def patch(operations, name='inventory'):
        return {'verb': 'patch', 'name': name, 'patch': operations}
    if case in ('heartbeat', 'restart_snapshot'):
        return [patch([heartbeat])]
    if case in ('authority_aba', 'withdrawn_aba'):
        return [patch([authority]), patch([{**authority, 'value': 'enabled'}])]
    if case == 'annotations_removed':
        return [patch([{'op': 'remove', 'path': '/metadata/annotations'}])]
    if case == 'mixed_change':
        return [patch([heartbeat, authority])]
    if case == 'port_layout_changed':
        return [patch([{'op': 'add', 'path': '/spec/ports/0', 'value':
                       {'name': 'metrics', 'port': 9090, 'targetPort': 9090, 'protocol': 'TCP'}}])]
    if case == 'deleting':
        return [patch([{'op': 'add', 'path': '/metadata/finalizers', 'value': ['autonomy-lab/hold']}]),
                {'verb': 'delete', 'name': 'inventory'}]
    if case == 'backend_changed':
        return [patch([{'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 5433}], 'postgres')]
    return []


def expected(case, contract):
    if case.startswith('contract_change'):
        return 'rejected', 'operation_contract_changed', 0
    if case == 'withdrawn_aba':
        return 'rejected', 'dispatch_authorization_refused', 0
    if case in ('budget_exhausted', 'budget_revoked'):
        return 'rejected', case, 0
    if case in ('lost_ack', 'kill_after_dispatch'):
        return 'uncertain', ('dispatch_outcome_unknown' if case == 'lost_ack'
                             else 'dispatch_outcome_unrecorded'), 1
    if case == 'restart_snapshot' and contract == LEGACY:
        return 'rejected', 'resource_version_changed', 0
    if case in ('annotations_removed', 'mixed_change', 'port_layout_changed', 'deleting') or (
            case in ('heartbeat', 'authority_aba') and contract == LEGACY):
        return 'rejected', 'api_rejected_422', 1
    return 'acknowledged', 'api_acknowledged', 1


def epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def without_managed(value):
    value = copy.deepcopy(value)
    value.get('metadata', {}).pop('managedFields', None)
    return value


def verification_valid(value, expectations, seconds=3):
    probes = value['probes']
    verdicts = [evaluate_snapshot(p['observations'], expectations) for p in probes]
    verdict = ('verified_failure' if any(v['verdict'] == 'verified_failure' for v in verdicts)
               else 'indeterminate' if any(v['verdict'] == 'indeterminate' for v in verdicts)
               else 'verified_success')
    return (len(probes) >= 2 and value['window_seconds'] == seconds
            and probes[0]['offset_seconds'] < probes[-1]['offset_seconds']
            and probes[-1]['offset_seconds'] >= seconds
            and epoch(value['finished_at']) - epoch(value['started_at']) >= seconds
            and all(p['verdict'] == v['verdict'] and p['reasons'] == v['reasons']
                    for p, v in zip(probes, verdicts, strict=True))
            # A known customer failure must not conceal unavailable database
            # evidence, damaged data, a partial corpus or broken controls.
            and all(reason.startswith('service: protected ') or (
                reason.startswith('quote ') and ': HTTP 503 (expected ' in reason)
                for v in verdicts for reason in v['reasons'])
            and value['reasons'] == list(dict.fromkeys(reason for v in verdicts for reason in v['reasons']))
            and value['verdict'] == verdict)


def assess(records, captured, cleanup):
    checks = {'matrix': [(r.get('case'), r.get('contract')) for r in records]
              == [(case, arm) for case in CASES for arm in ARMS],
              'closed_audit': captured.get('collection_closed') is True
              and captured.get('malformed_lines') == 0, 'cleanup': cleanup == 'deleted'}
    identities = [r.get('before', {}).get('metadata', {}).get('uid') for r in records]
    checks['fresh_identities'] = len(set(identities)) == 32 and all(identities)
    events = captured.get('events', [])
    writes = [e for e in events if e.get('user', {}).get('username')
              == 'system:serviceaccount:autonomy-lab:broker'
              and e.get('verb') in ('create', 'patch', 'update', 'delete', 'deletecollection')]
    checks['total_dispatches'] = len(writes) == sum(expected(c, a)[2] for c in CASES for a in ARMS)
    rows = []
    expectations = load_expectations()
    for record in records:
        try:
            case, contract = record['case'], record['contract']
            state, reason, sent = expected(case, contract)
            operation, binding = record['operation'], record['binding']
            request = operation['request']
            validate_binding(request, binding)
            actual = [e for e in writes if e.get('userAgent') == 'autonomy-lab-operation/' + request['operation_id']]
            applied = state in ('acknowledged', 'uncertain')
            wanted = copy.deepcopy(record['changed'])
            if applied:
                wanted['spec']['ports'][0]['targetPort'] = 8080
            row = {'completed': not record.get('error_type'),
                   'journal_consistent': record.get('journal_consistent') is True,
                   'snapshot_phase': (binding['snapshot'] is not None) == (
                       contract == PRECISE and case not in ('contract_change_intent', 'budget_exhausted')),
                   'identity': operation['operation_id'] == request['operation_id'] == binding['operation_id']
                   and binding['contract_id'] == contract,
                   'outcome': operation['status'] == state and operation['reason'] == reason,
                   'budget': operation['budget_used'] == sent and operation['budget_reserved'] == bool(sent),
                   'dispatch_count': len(actual) == sent,
                   'exact_effect': visible_resource(record['after']) == visible_resource(wanted),
                   'no_scratch': SCRATCH not in record['after'],
                   'binding_unchanged': binding == record['binding_before_reopen'],
                   'no_replay': record['duplicate']['status'] == state
                   and record['resumed']['status'] == state,
                   'verification_complete': verification_valid(record['verification'], expectations)}
            controls = record['controls']
            declared = interventions(case)
            row['declared_controls'] = len(controls) == len(declared) and all(
                {k: actual[k] for k in wanted} == wanted for actual, wanted in zip(controls, declared, strict=True))
            for index, control in enumerate(controls):
                matches = [e for e in events if e.get('verb') == control['verb']
                           and e.get('user', {}).get('username') == 'kubernetes-admin'
                           and e.get('objectRef', {}).get('resource') == 'services'
                           and e.get('objectRef', {}).get('name') == control['name']
                           and e.get('objectRef', {}).get('namespace') == 'autonomy-lab'
                           and control['started_at'] <= epoch(e['requestReceivedTimestamp'])
                           and epoch(e['stageTimestamp']) <= control['finished_at']
                           and e.get('responseStatus', {}).get('code') == 200]
                if control['verb'] == 'patch':
                    matches = [e for e in matches if e.get('requestObject') == control['patch']
                               and e.get('responseObject') == control['response']
                               and e.get('userAgent') == 'autonomy-lab-operation/' + request['operation_id'] + '-control-' + str(index)]
                row['control_audit_' + str(index)] = len(matches) == 1
            row['intervention_before_changed_read'] = all(c['finished_at'] <= record['changed_at'] for c in controls)
            if case == 'deleting':
                row['deletion_in_progress'] = bool(record['changed']['metadata'].get('deletionTimestamp'))
            successful_customer = applied and case != 'backend_changed'
            faults = record['fault_evidence']
            row['initial_customer_fault'] = bool(faults) and all(
                verification_valid(v, expectations, 1) for v in faults) and any(
                    q.get('case_id') == 'available-single' and q.get('status_code') == 503
                    for q in faults[-1]['probes'][-1]['observations']['quotes'])
            if successful_customer:
                readiness = record['readiness_evidence']
                row['recovery_convergence'] = bool(readiness) and readiness[-1]['verdict'] == 'verified_success' and all(
                    verification_valid(v, expectations, 1) and (v['verdict'] == 'verified_success' or (
                        v['verdict'] == 'verified_failure' and v['reasons'] and all(
                            reason.startswith('quote ') and ': HTTP 503 (expected ' in reason
                            for reason in v['reasons']))) for v in readiness)
            row['customer_outcome'] = record['verification']['verdict'] == (
                'verified_success' if successful_customer else 'verified_failure')
            row['decision'] = record['decision'] == (
                'escalate_uncertain' if state == 'uncertain' else
                'escalate_refused' if state == 'rejected' else
                'verified_recovery' if successful_customer else 'escalate_verification_failed')
            if not successful_customer:
                probes = record['verification']['probes']
                row['customer_failure_controls'] = all(
                    p['observations']['quote_control'].get('status_code') == 200
                    and p['observations']['inventory_control'].get('status_code') == 200
                    and any(q['case_id'] == 'available-single' and q.get('status_code') == 503
                            for q in p['observations']['quotes']) for p in probes)
            for key in ('before', 'changed', 'after'):
                lower = record['started_at']
                if key == 'changed' and controls:
                    lower = controls[-1]['finished_at']
                if key == 'after':
                    lower = max([record['changed_at'], *(epoch(e['stageTimestamp']) for e in actual)])
                row[key + '_audit_read'] = any(
                    e.get('verb') == 'get' and e.get('responseStatus', {}).get('code') == 200
                    and lower <= epoch(e['requestReceivedTimestamp'])
                    and epoch(e['stageTimestamp']) <= record[key + '_at']
                    and without_managed(e.get('responseObject', {})) == record[key]
                    for e in events)
            if sent:
                event = actual[0] if len(actual) == 1 else {}
                patch = (patch_for_binding(request, binding) if contract == PRECISE
                         else repair_patch(record['before'], 'version'))
                row['exact_api_request'] = (event.get('verb') == 'patch'
                    and event.get('requestObject') == patch
                    and event.get('objectRef', {}).get('resource') == 'services'
                    and event.get('objectRef', {}).get('name') == 'inventory'
                    and event.get('objectRef', {}).get('namespace') == 'autonomy-lab')
                row['api_response'] = event.get('responseStatus', {}).get('code') == (200 if applied else 422)
                row['sequence'] = (record['changed_at'] <= epoch(event['requestReceivedTimestamp'])
                                   <= epoch(event['stageTimestamp']) <= record['after_at'])
                if applied:
                    row['response_effect'] = visible_resource(event['responseObject']) == visible_resource(record['after'])
                if case == 'lost_ack':
                    row['dropped_real_response'] = record['dropped_response'] == event['responseObject']
            if case in KILLS:
                row['real_sigkill'] = record['kill']['exit_code'] == -9 and record['kill']['signal'] == 'SIGKILL'
                barrier = record['kill']['barrier']
                row['kill_stage'] = (barrier['stage'] == KILLS[case]
                                     and barrier['operation_id'] == request['operation_id']
                                     and type(record['kill']['pid']) is int and record['kill']['pid'] > 0
                                     and barrier['pid'] == record['kill']['pid'])
                row['killed_intent'] = record['journal_at_kill']['operation_id'] == request['operation_id']
                row['restart_binding'] = binding == record['binding_at_kill']
                if case == 'kill_after_dispatch':
                    row['unrecorded_ack'] = record['journal_at_kill']['status'] == 'dispatching' and record['journal_at_kill']['result'] is None
            if case in ('lost_ack', 'kill_after_dispatch'):
                row['reconciliation_not_recovery'] = record['reconciled']['reconciliation']['recovery'] == 'not_verified'
            if case == 'withdrawn_aba':
                row['durable_withdrawal'] = record['permit']['enabled'] is False
                row['new_intent_refused'] = record['followup']['reason'] == 'dispatch_authorization_refused' and record['followup']['budget_used'] == 0
            if contract == PRECISE and binding['snapshot'] is not None:
                row['trusted_initial_conditions'] = binding['snapshot'] == record['before']
                stored = [e for e in record['journal_events'] if e['event'] == 'conditions_recorded']
                row['one_snapshot_before_effect'] = len(stored) == 1 and stored[0]['details']['binding_sha256'] == binding['binding_sha256'] and (
                    not controls or epoch(stored[0]['timestamp']) <= controls[0]['started_at'])
                row['snapshot_from_broker_read'] = len(stored) == 1 and any(
                    e.get('verb') == 'get' and e.get('user', {}).get('username') == 'system:serviceaccount:autonomy-lab:broker'
                    and e.get('responseStatus', {}).get('code') == 200
                    and record['started_at'] <= epoch(e['requestReceivedTimestamp'])
                    and epoch(e['stageTimestamp']) <= epoch(stored[0]['timestamp'])
                    and without_managed(e.get('responseObject', {})) == binding['snapshot'] for e in events)
            audited = assess_audit(events, [operation], started_at=record['started_iso'],
                                   finished_at=record['finished_iso'],
                                   contract_bindings={request['operation_id']: binding})
            row['audit_recognized'] = audited['successful_unmatched_mutations'] == 0 and not audited['missing_acknowledged_operations']
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            row = {'complete_evidence': False}
        checks[str(record.get('case')) + '/' + str(record.get('contract'))] = all(row.values())
        rows.append({'case': record.get('case'), 'contract': record.get('contract'),
                     'status': 'passed' if all(row.values()) else 'failed', 'checks': row})
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
            'cases': rows, 'scope': 'durable contract development; no admission or aggregate benefit claim'}


def adversarial_checks(records, captured, cleanup):
    """Authored evidence corruptions, explicitly separate from live trials."""
    if assess(records, captured, cleanup)['status'] != 'passed':
        raise ValueError('A passing real cohort is required as the positive control')
    results = {}
    for defect in ('budget', 'journal', 'binding', 'controls', 'extra_patch', 'missing_reads',
                   'short_window', 'kill', 'uncertain_recovery', 'rebound', 'withdrawal', 'backend_success',
                   'missing_snapshot', 'kill_operation', 'kill_pid'):
        changed, audit = copy.deepcopy(records), copy.deepcopy(captured)
        case = {'controls': 'heartbeat', 'kill': 'kill_after_dispatch',
                'uncertain_recovery': 'lost_ack', 'withdrawal': 'withdrawn_aba',
                'backend_success': 'backend_changed', 'missing_snapshot': 'contract_change_snapshot',
                'kill_operation': 'kill_after_dispatch', 'kill_pid': 'kill_after_dispatch'}.get(defect, 'unchanged')
        row = next(r for r in changed if r['case'] == case and r['contract'] == PRECISE)
        if defect == 'budget':
            row['operation']['budget_used'] = 0
        elif defect == 'journal':
            row['journal_consistent'] = False
        elif defect == 'binding':
            row['binding']['binding_sha256'] = 'corrupted'
        elif defect == 'controls':
            row['controls'] = []
        elif defect == 'extra_patch':
            event = next(e for e in audit['events'] if e.get('verb') == 'patch' and
                         e.get('userAgent') == 'autonomy-lab-operation/' + row['operation']['operation_id'])
            event['requestObject'].append({'op': 'add', 'path': '/metadata/labels', 'value': {'unexpected': 'yes'}})
        elif defect == 'missing_reads':
            audit['events'] = [e for e in audit['events'] if not (e.get('verb') == 'get' and
                e.get('responseObject', {}).get('metadata', {}).get('uid') == row['before']['metadata']['uid'])]
        elif defect == 'short_window':
            row['verification']['probes'] = row['verification']['probes'][:1]
        elif defect == 'kill':
            row['kill']['exit_code'] = 0
        elif defect == 'kill_operation':
            row['kill']['barrier']['operation_id'] = 'different-operation'
        elif defect == 'kill_pid':
            row['kill']['barrier']['pid'] += 1
        elif defect == 'uncertain_recovery':
            row['decision'] = 'verified_recovery'
        elif defect == 'rebound':
            row['binding_before_reopen']['snapshot'] = None
        elif defect == 'withdrawal':
            row['followup']['reason'] = 'api_acknowledged'
        elif defect == 'backend_success':
            row['verification']['verdict'] = 'verified_success'
        else:
            from autonomy_lab.durable_contract import binding_for
            empty = binding_for(row['operation']['request'], PRECISE)
            for name in ('binding', 'binding_before_reopen', 'binding_at_kill'):
                row[name] = copy.deepcopy(empty)
            row['journal_events'] = [e for e in row['journal_events'] if e['event'] != 'conditions_recorded']
        result = assess(changed, audit, cleanup)
        selected = next(r for r in result['cases'] if r['case'] == case and r['contract'] == PRECISE)
        results[defect] = result['status'] == selected['status'] == 'failed'
    return {'status': 'passed' if all(results.values()) else 'failed', 'checks': results,
            'scope': 'authored corruption tests of retained evidence, not additional live cases'}
