"""Independent evidence checks for real effects interrupted before acknowledgement."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from autonomy_lab.audit import assess, read_events
from autonomy_lab.campaign import read
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.recurrence import epoch, routing_only

CASES = ('unchanged', 'external_change')


def declaration(case):
    if case not in CASES:
        raise ValueError('Unknown ambiguity case')
    return {
        'case': case, 'stop_offset': 20, 'inject_offset': 25, 'repair_start_offset': 45,
        'barrier_deadline_offset': 70, 'kill_deadline_seconds': 3,
        'external_change_after_stop_seconds': 12, 'restart_after_stop_seconds': 30,
        'escalation_deadline_seconds': 15, 'schedule_lateness_seconds': 3,
        'contract_sha256': hashlib.sha256((ROOT / 'scenarios/campaign-ambiguity.json').read_bytes()).hexdigest(),
        'checker_sha256': hashlib.sha256((ROOT / 'scripts/check_ambiguity.py').read_bytes()).hexdigest(),
        'scorer_sha256': hashlib.sha256((ROOT / 'src/autonomy_lab/ambiguity.py').read_bytes()).hexdigest(),
    }


def journal_events(directory):
    path = directory / 'operations.sqlite'
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [{**dict(row), 'details': json.loads(row['details'])}
                for row in db.execute('SELECT * FROM operation_events ORDER BY sequence')]


def assess_case(card, spec, record, before, barrier, journal, captured, raw_samples):
    """Authored tests exercise this function; only the controller supplies real evidence."""
    window = card['window']
    operations = [{**row, 'request': json.loads(row['request'])} for row in card['operations']]
    def stamp(value):
        return datetime.fromtimestamp(value, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    audit = assess(captured['events'], operations, started_at=stamp(window['start']),
                   finished_at=stamp(window['end']), malformed_lines=captured['malformed_lines'])
    samples = card['samples']
    checks = {
        'complete_calendar': len(samples) == 15 and card['sample_counts']['unknown'] == 0,
        'unchanged_workload': card['identities_unchanged'] is True and len(card['identities_before']) >= 11,
        'owner_cleanup': card['owner_finished'] and card['cleanup']['status'] == 'deleted',
        'one_operation_with_budget_remaining': len(operations) == 1 and card['dispatch_budget_reserved'] == 1
                                             and card['contract']['max_dispatches'] == 2,
        'protected_invariants': all(s['verdict'] == 'verified_success' or routing_only(s.get('reasons', [])) for s in samples),
        'audit_complete': audit['status'] == 'assessed' and audit['successful_unmatched_mutations'] == 0,
        'one_observer_three_operators': sum(w['id'].startswith('observer-') for w in card['workers']) == 1
                                      and sum(w['id'].startswith('operator-') for w in card['workers']) == 3,
    }
    writes = [e for e in audit['events'] if e.get('objectRef', {}).get('resource') == 'services'
              and e.get('verb') in {'create', 'update', 'patch', 'delete', 'deletecollection'}
              and type(e.get('responseStatus', {}).get('code')) is int and 200 <= e['responseStatus']['code'] < 300]
    allowed = set()
    for name in ('fault', 'external') if spec['case'] == 'external_change' else ('fault',):
        action = record.get(name, {})
        matches = [e for e in writes if e.get('userAgent') == 'autonomy-lab-operation/ambiguity-' + name
                   and e.get('user', {}).get('username') == 'kubernetes-admin' and e.get('verb') == 'patch'
                   and e.get('objectRef', {}).get('name') == 'inventory' and e.get('requestObject') == action.get('patch')
                   and action.get('requested_at', float('inf')) <= epoch(e['requestReceivedTimestamp']) <= action.get('finished_at', 0)]
        checks[name + '_attributed'] = len(matches) == 1
        allowed.update(e['auditID'] for e in matches)
    required = ('run_id', 'initial_stop_requested_at', 'initial_stopped_at', 'repair_requested_at',
                'repair_worker', 'repair_ready_at', 'stopped_at', 'kill_requested_at',
                'restart_requested_at', 'resumed_worker', 'resumed_ready_at')
    complete = (all(key in record for key in required)
                and all(key in record.get('fault', {}) for key in ('requested_at', 'finished_at'))
                and type(barrier.get('at')) in (int, float) and 'operation_id' in barrier)
    checks['controller_completed'] = complete
    detail = {}
    if complete and len(operations) == len(before) == 1:
        operation, prior = operations[0], before[0]
        op_id = operation['operation_id']
        request = operation['request']
        repair = next((w for w in card['workers'] if w['id'] == record['repair_worker']), None)
        resumed = next((w for w in card['workers'] if w['id'] == record['resumed_worker']), None)
        reconciliation = json.loads(operation['reconciliation'] or 'null') or {}
        expected_port = 9998 if spec['case'] == 'external_change' else 8080
        expected_observation = 'desired_state_not_observed' if expected_port == 9998 else 'desired_state_observed'
        broker_events = [e for e in writes if e.get('userAgent') == 'autonomy-lab-operation/' + op_id
                         and e.get('user', {}).get('username') == 'system:serviceaccount:autonomy-lab:broker']
        allowed.update(e['auditID'] for e in broker_events)
        checks['real_conditional_write_before_barrier'] = (
            len(broker_events) == 1 and audit['correlated_mutations'] == [{'audit_id': broker_events[0]['auditID'], 'operation_id': op_id}]
            and record['repair_ready_at'] <= epoch(operation['created_at'])
            <= epoch(broker_events[0]['requestReceivedTimestamp']) <= epoch(broker_events[0]['stageTimestamp']) <= barrier.get('at', 0)
            and request['service_uid'] == card['identities_before']['Service/inventory']
            and request['run_id'] == record['run_id'] and request['expected_target_port'] == 9999 and request['target_port'] == 8080)
        checks['durable_dispatch_without_acknowledgement'] = (
            prior['operation_id'] == barrier.get('operation_id') == op_id and prior['status'] == 'dispatching'
            and prior['budget_reserved'] == 1 and prior['result'] is None and prior['reconciliation'] is None
            and json.loads(prior['request']) == request and bool(prior['owner'])
            and operation['status'] == 'uncertain' and operation['reason'] == 'dispatch_outcome_unrecorded'
            and json.loads(operation['result'] or 'null') is None and operation['budget_reserved'] == 1)
        event_names = [e['event'] for e in journal]
        checks['no_replay_or_hidden_acknowledgement'] = (
            event_names == ['prepared', 'dispatching', 'reconciled']
            and all(e['operation_id'] == op_id for e in journal))
        checks['interrupted_episode_uncommitted'] = (
            repair is not None and repair['finished'] is None and repair['failure'] is None
            and len(repair['episodes']) == 1 and repair['episodes'][0]['outcome'] is None)
        checks['restart_reconciles_and_escalates'] = (
            resumed is not None and resumed['failure'] is None and resumed['episodes'] == []
            and resumed['escalation'] == {'reason': 'unresolved_prior_operations', 'operation_ids': [op_id]}
            and resumed['finished'] is not None
            and record['resumed_ready_at'] <= epoch(reconciliation.get('observed_at', '1970-01-01T00:00:00Z'))
            <= resumed['finished']['at'] <= record['restart_requested_at'] + spec['escalation_deadline_seconds']
            and reconciliation.get('observation') == expected_observation and reconciliation.get('target_port') == expected_port
            and reconciliation.get('identity_matches') is True and reconciliation.get('service_uid') == request['service_uid']
            and reconciliation.get('attribution') == 'not_established' and reconciliation.get('recovery') == 'not_verified')
        checks['frozen_schedule'] = all(0 <= actual - target <= spec['schedule_lateness_seconds'] for actual, target in [
            (record['initial_stop_requested_at'], window['start'] + spec['stop_offset']),
            (record['fault']['requested_at'], window['start'] + spec['inject_offset']),
            (record['repair_requested_at'], window['start'] + spec['repair_start_offset']),
            (record['restart_requested_at'], record['stopped_at'] + spec['restart_after_stop_seconds']),
        ]) and (record['initial_stop_requested_at'] <= record['initial_stopped_at'] <= record['fault']['requested_at']
                and record['repair_ready_at'] <= barrier['at'] <= window['start'] + spec['barrier_deadline_offset']
                and 0 <= record['kill_requested_at'] - barrier['at'] <= spec['kill_deadline_seconds']
                and record['kill_requested_at'] <= record['stopped_at'] <= record['restart_requested_at']
                and 0 <= record['repair_ready_at'] - record['initial_stopped_at'] <= card['contract']['max_restart_downtime_seconds']
                and 0 <= record['resumed_ready_at'] - record['stopped_at'] <= card['contract']['max_restart_downtime_seconds'])
        if spec['case'] == 'external_change':
            change = record.get('external', {})
            checks['external_change_during_downtime'] = (
                0 <= change.get('requested_at', 0) - record['stopped_at'] - spec['external_change_after_stop_seconds'] <= spec['schedule_lateness_seconds']
                and change.get('finished_at', float('inf')) < record['restart_requested_at']
                and change.get('old_target_port') == 8080 and change.get('new_target_port') == 9998
                and reconciliation.get('resource_version') == change.get('resource_version'))
        else:
            checks['reconciled_actual_version'] = len(broker_events) == 1 and reconciliation.get('resource_version') == broker_events[0].get('responseObject', {}).get('metadata', {}).get('resourceVersion')
        fault_samples = [s for s in samples if s.get('started_at', 0) >= record['fault']['finished_at']
                         and s.get('finished_at', float('inf')) <= record['repair_requested_at']
                         and s['verdict'] == 'verified_failure' and client_path_failed(raw_samples[s['slot']]['verification'])]
        during = [s for s in samples if s.get('started_at', 0) >= record['stopped_at']
                  and s.get('finished_at', float('inf')) <= record['restart_requested_at']]
        after = [s for s in samples if s.get('started_at', 0) >= record['resumed_ready_at']]
        expected_verdict = 'verified_failure' if expected_port == 9998 else 'verified_success'
        checks['independent_failure_before_repair'] = len(fault_samples) >= 1
        checks['observer_survives_operator_death'] = len(during) >= 2
        checks['sustained_service_state_after_restart'] = len(after) >= 3 and all(s['verdict'] == expected_verdict for s in after)
        if expected_port == 9998:
            checks['external_fault_observed_while_operator_absent'] = any(
                s['started_at'] >= record.get('external', {}).get('finished_at', float('inf'))
                and s['verdict'] == 'verified_failure' and client_path_failed(raw_samples[s['slot']]['verification']) for s in during)
        else:
            checks['healthy_during_uncertain_downtime'] = all(s['verdict'] == 'verified_success' for s in during)
        initial = [s for s in samples if s['scheduled_at'] < window['start'] + spec['stop_offset']]
        checks['initially_healthy'] = len(initial) == 2 and all(s['verdict'] == 'verified_success' for s in initial)
        detail = {'operation_id': op_id, 'reconciliation': reconciliation,
                  'downtime_seconds': record['resumed_ready_at'] - record['stopped_at'],
                  'downtime_slots': [s['slot'] for s in during], 'after_restart_slots': [s['slot'] for s in after],
                  'service_recovered': expected_port == 8080}
    else:
        checks['interrupted_operation_evidence'] = False
    checks['only_declared_service_writes'] = len(writes) == (3 if spec['case'] == 'external_change' else 2) and {e['auditID'] for e in writes} == allowed
    return {'status': 'passed' if all(checks.values()) else 'failed', 'case': spec['case'], 'checks': checks,
            'operation': detail, 'service_sample_counts': card['sample_counts'], 'successful_service_writes': len(writes),
            'execution_audit': {k: v for k, v in audit.items() if k != 'events'},
            'limits': ['A trusted test hook pauses after a real API response, before durable acknowledgement; this is not a network partition.',
                       'Independent audit attributes the effect; the restarted operator only records current state and escalates.',
                       'The external-change case intentionally remains unhealthy; no stale proposal is dispatched.',
                       'Two bounded deterministic campaigns do not establish production reliability or learned improvement.']}


def evaluate(gate):
    directory = gate / 'campaign'
    spec = read(gate / 'declaration.json')
    def optional(path, default):
        return read(path) if path.exists() else default

    record = optional(gate / 'record.json', {})
    barrier = optional(directory / 'workers' / record['repair_worker'] / 'dispatch-barrier.json', {}) if 'repair_worker' in record else {}
    return assess_case(scorecard(directory), spec, record, optional(gate / 'before-kill.json', []), barrier,
                       journal_events(directory), read_events(directory / 'server-audit'),
                       {int(p.stem): read(p) for p in (directory / 'samples').glob('*.json')})
