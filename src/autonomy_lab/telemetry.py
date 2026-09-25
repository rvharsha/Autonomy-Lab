"""Score real collection gaps separately from an operator's unavailable evidence."""

import hashlib
import json
from datetime import UTC, datetime

from autonomy_lab.ambiguity import journal_events
from autonomy_lab.audit import assess, read_events
from autonomy_lab.campaign import read
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.recurrence import epoch, routing_only


def declaration():
    return {'pause_offset': 25, 'resume_offset': 65, 'unknown_slots': [3, 4, 5, 6],
            'stop_offset': 80, 'inject_offset': 85, 'repair_start_offset': 105,
            'barrier_deadline_offset': 130, 'kill_deadline_seconds': 3,
            'revoke_after_stop_seconds': 5, 'restart_after_stop_seconds': 15,
            'escalation_deadline_seconds': 15, 'schedule_lateness_seconds': 3,
            'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                ['scenarios/campaign-telemetry.json', 'scripts/check_telemetry.py', 'src/autonomy_lab/telemetry.py']}}


def assess_telemetry(card, spec, record, before, barrier, journal, captured, raw):
    window, samples = card['window'], card['samples']
    unknown = [s['slot'] for s in samples if s['verdict'] == 'unknown']
    operations = [{**row, 'request': json.loads(row['request'])} for row in card['operations']]

    def stamp(value):
        return datetime.fromtimestamp(value, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')

    audit = assess(captured['events'], operations, started_at=stamp(window['start']), finished_at=stamp(window['end']),
                   malformed_lines=captured['malformed_lines'])
    writes = [e for e in audit['events'] if e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}
              and e.get('objectRef', {}).get('resource') in {'services', 'roles'}
              and type(e.get('responseStatus', {}).get('code')) is int and 200 <= e['responseStatus']['code'] < 300]
    checks = {
        'declared_gaps_preserved': len(samples) == 21 and unknown == spec['unknown_slots'] == [3, 4, 5, 6]
                                 and all(samples[i]['coverage'] == 'missing' and i not in raw for i in unknown),
        'all_other_slots_assessed': card['sample_counts']['unknown'] == 4 and all(
            s['verdict'] in {'verified_success', 'verified_failure'} for s in samples if s['slot'] not in spec['unknown_slots']),
        'unchanged_workload': card['identities_unchanged'] is True and len(card['identities_before']) >= 11,
        'owner_cleanup': card['owner_finished'] and card['cleanup']['status'] == 'deleted',
        'protected_invariants': all(s['verdict'] in {'verified_success', 'unknown'} or routing_only(s.get('reasons', [])) for s in samples),
        'one_operation_budget_remaining': len(operations) == 1 and card['dispatch_budget_reserved'] == 1 and card['contract']['max_dispatches'] == 2,
        'audit_complete': audit['status'] == 'assessed' and audit['successful_unmatched_mutations'] == 0,
        'one_observer_three_operators': sum(w['id'].startswith('observer-') for w in card['workers']) == 1
                                      and sum(w['id'].startswith('operator-') for w in card['workers']) == 3,
    }
    needed = ['paused_at', 'resumed_at', 'observer', 'initial_worker', 'initial_stopped_at', 'repair_ready_at',
              'repair_worker', 'stopped_at', 'resumed_worker', 'resumed_ready_at', 'restart_requested_at',
              'initial_stop_requested_at', 'repair_requested_at', 'kill_requested_at', 'run_id']
    complete = (all(k in record for k in needed) and all(k in record.get('fault', {}) for k in ['requested_at', 'finished_at', 'patch'])
                and all(k in record.get('revocation', {}) for k in ['requested_at', 'finished_at', 'before_rules', 'after_rules'])
                and all(k in barrier for k in ['at', 'operation_id']) and len(before) == len(operations) == 1)
    checks['controller_completed'] = complete
    details = {}
    if complete:
        op, prior = operations[0], before[0]
        op_id, request = op['operation_id'], op['request']
        recon = json.loads(op['reconciliation'] or 'null') or {}
        workers = {w['id']: w for w in card['workers']}
        original, interrupted, resumed = (workers.get(record[key]) for key in ['initial_worker', 'repair_worker', 'resumed_worker'])
        checks['actual_observer_suspension'] = (record.get('pause_state', '').startswith('T')
            and record.get('observer_identity_before') == record.get('observer_identity_after')
            and bool(record.get('observer_identity_before')) and record['observer'] in workers)
        prefix = record.get('samples_before_pause', {})
        checks['committed_samples_unchanged'] = (set(prefix) == {'0000.json', '0001.json', '0002.json'}
            and all(card['sample_sha256'].get(name) == sha for name, sha in prefix.items()))
        claims = [ep for ep in (original or {}).get('episodes', []) if ep['outcome'] is not None
                  and record['paused_at'] <= ep['attempt']['started_at'] <= ep['outcome']['finished_at'] <= record['resumed_at']
                  and ep['outcome']['claim'].get('outcome') == 'healthy']
        checks['operator_claims_did_not_fill_measurement_gap'] = len(claims) >= 2
        checks['observed_health_before_declared_fault'] = all(
            s['verdict'] == 'verified_success' for s in samples
            if s['slot'] not in spec['unknown_slots'] and s['scheduled_at'] < window['start'] + spec['inject_offset'])
        checks['frozen_schedule'] = all(0 <= actual - target <= spec['schedule_lateness_seconds'] for actual, target in [
            (record['paused_at'], window['start'] + spec['pause_offset']), (record['resumed_at'], window['start'] + spec['resume_offset']),
            (record['initial_stop_requested_at'], window['start'] + spec['stop_offset']),
            (record['fault']['requested_at'], window['start'] + spec['inject_offset']),
            (record['repair_requested_at'], window['start'] + spec['repair_start_offset']),
            (record['revocation']['requested_at'], record['stopped_at'] + spec['revoke_after_stop_seconds']),
            (record['restart_requested_at'], record['stopped_at'] + spec['restart_after_stop_seconds']),
        ]) and (record['repair_ready_at'] <= barrier['at'] <= window['start'] + spec['barrier_deadline_offset']
                and 0 <= record['kill_requested_at'] - barrier['at'] <= spec['kill_deadline_seconds']
                and record['kill_requested_at'] <= record['stopped_at'] < record['revocation']['requested_at']
                < record['revocation']['finished_at'] < record['restart_requested_at']
                and 0 <= record['resumed_ready_at'] - record['stopped_at'] <= card['contract']['max_restart_downtime_seconds']
                and 0 <= record['repair_ready_at'] - record['initial_stopped_at'] <= card['contract']['max_restart_downtime_seconds'])
        expected_rules = [{'apiGroups': [''], 'resources': ['services'], 'resourceNames': ['inventory'], 'verbs': ['get', 'patch']}]
        checks['read_revoked_write_permission_retained'] = (record['revocation']['before_rules'] == expected_rules
            and record['revocation']['after_rules'] == [{**expected_rules[0], 'verbs': ['patch']}])
        checks['uncertainty_survives_telemetry_loss'] = (
            prior['operation_id'] == barrier['operation_id'] == op_id and prior['status'] == 'dispatching'
            and prior['result'] is None and prior['reconciliation'] is None and prior['budget_reserved'] == 1
            and json.loads(prior['request']) == request and op['status'] == 'uncertain'
            and op['reason'] == 'dispatch_outcome_unrecorded' and json.loads(op['result'] or 'null') is None
            and recon.get('observation') == 'unavailable' and recon.get('attribution') == 'not_established'
            and recon.get('recovery') == 'not_verified'
            and 'target_port' not in recon and 'resource_version' not in recon
            and [e['event'] for e in journal] == ['prepared', 'dispatching', 'reconciled']
            and all(e['operation_id'] == op_id for e in journal))
        checks['interrupted_episode_uncommitted'] = (interrupted is not None and interrupted['finished'] is None
            and interrupted['failure'] is None and len(interrupted['episodes']) == 1 and interrupted['episodes'][0]['outcome'] is None)
        checks['escalated_without_new_episode'] = (resumed is not None and resumed['failure'] is None and resumed['episodes'] == []
            and resumed['escalation'] == {'reason': 'unresolved_prior_operations', 'operation_ids': [op_id]}
            and resumed['finished'] is not None and record['resumed_ready_at'] <= epoch(recon.get('observed_at', '1970-01-01T00:00:00Z'))
            <= resumed['finished']['at'] <= record['restart_requested_at'] + spec['escalation_deadline_seconds'])
        broker_user = 'system:serviceaccount:autonomy-lab:broker'
        denied = [e for e in audit['events'] if e.get('verb') == 'get' and e.get('user', {}).get('username') == broker_user
                  and e.get('objectRef', {}).get('resource') == 'services' and e['objectRef'].get('name') == 'inventory'
                  and e.get('responseStatus', {}).get('code') == 403
                  and record['resumed_ready_at'] <= epoch(e['requestReceivedTimestamp']) <= record['restart_requested_at'] + spec['escalation_deadline_seconds']]
        repairs = [e for e in writes if e.get('userAgent') == 'autonomy-lab-operation/' + op_id
                   and e.get('user', {}).get('username') == broker_user]
        injections = [e for e in writes if e.get('userAgent') == 'autonomy-lab-operation/ambiguity-fault'
                      and e.get('user', {}).get('username') == 'kubernetes-admin' and e.get('requestObject') == record['fault']['patch']
                      and record['fault']['requested_at'] <= epoch(e['requestReceivedTimestamp']) <= record['fault']['finished_at']]
        revocations = [e for e in writes if e.get('objectRef', {}).get('resource') == 'roles' and e['objectRef'].get('name') == 'broker'
                       and e.get('verb') == 'patch' and e.get('user', {}).get('username') == 'kubernetes-admin'
                       and record['revocation']['requested_at'] <= epoch(e['requestReceivedTimestamp']) <= record['revocation']['finished_at']]
        checks['real_denied_reconciliation_read'] = len(denied) == 1
        checks['exact_attributed_mutations'] = (len(repairs) == len(injections) == len(revocations) == 1
            and len(writes) == 3 and {e['auditID'] for e in writes} == {e['auditID'] for e in repairs + injections + revocations}
            and audit['correlated_mutations'] == [{'audit_id': repairs[0]['auditID'], 'operation_id': op_id}]
            and record['repair_ready_at'] <= epoch(op['created_at']) <= epoch(repairs[0]['requestReceivedTimestamp'])
            <= epoch(repairs[0]['stageTimestamp']) <= barrier['at']
            and request['run_id'] == record['run_id'] and request['service_uid'] == card['identities_before']['Service/inventory']
            and request['expected_target_port'] == 9999 and request['target_port'] == 8080)
        faults = [s for s in samples if s.get('started_at', 0) >= record['fault']['finished_at']
                  and s.get('finished_at', float('inf')) <= record['repair_requested_at'] and s['verdict'] == 'verified_failure'
                  and client_path_failed(raw[s['slot']]['verification'])]
        after = [s for s in samples if s.get('started_at', 0) >= record['resumed_ready_at']]
        checks['fault_independently_observed'] = bool(faults)
        checks['independent_health_after_escalation'] = len(after) >= 3 and all(s['verdict'] == 'verified_success' for s in after)
        details = {'operation_id': op_id, 'reconciliation': recon, 'denied_read_audit_ids': [e['auditID'] for e in denied],
                   'operator_healthy_claims_during_gap': len(claims), 'after_restart_slots': [s['slot'] for s in after]}
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
            'service_sample_counts': card['sample_counts'], 'unknown_slots': unknown, 'operation': details,
            'execution_audit': {k: v for k, v in audit.items() if k != 'events'},
            'limits': ['Collection gaps are unknown, even when operator claims and adjacent observations are healthy.',
                       'RBAC denies the broker read while independent measurement remains available; this is not a network partition.',
                       'Mutation counts cover Service and Role resources; dependent Kubernetes controller updates are outside those counts.',
                       'The operator correctly escalates a healthy but unresolved service; no autonomous learning is demonstrated.']}


def evaluate(gate):
    directory = gate / 'campaign'

    def optional(path, default):
        return read(path) if path.exists() else default

    record = optional(gate / 'record.json', {})
    barrier = optional(directory / 'workers' / record['repair_worker'] / 'dispatch-barrier.json', {}) if 'repair_worker' in record else {}
    return assess_telemetry(scorecard(directory), read(gate / 'declaration.json'), record,
        optional(gate / 'before-kill.json', []), barrier, journal_events(directory), read_events(directory / 'server-audit'),
        {int(p.stem): read(p) for p in (directory / 'samples').glob('*.json')})
