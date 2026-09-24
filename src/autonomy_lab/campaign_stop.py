"""Offline checks for supervisor recovery of a genuinely interrupted campaign."""

import json
from datetime import UTC, datetime

from autonomy_lab.audit import assess
from autonomy_lab.harness import client_path_failed
from autonomy_lab.recurrence import epoch, routing_only


def assess_stop(card, receipt, record, captured, journal, raw):
    operations = [{**row, 'request': json.loads(row['request'])} for row in card['operations']]
    samples, window = card['samples'], card['window']

    def stamp(value):
        return datetime.fromtimestamp(value, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')

    audit = assess(captured['events'], operations, started_at=stamp(window['start']),
                   finished_at=stamp(record['stop_requested_at']), malformed_lines=captured['malformed_lines'])
    known = [s for s in samples if s['verdict'] != 'unknown']
    later = [s for s in samples if s['scheduled_at'] > record['stop_requested_at']]
    members = record['cgroup_members']
    checks = {
        'shared_termination_boundary': {m['role'] for m in members} == {'owner', 'operator', 'observer', 'janitor'}
            and len(members) == len({m['pid'] for m in members}) == 4 and all(m['identity'] for m in members)
            and len({m['cgroup'] for m in members}) == 1 and bool(members[0]['cgroup'])
            and record['before']['KillMode'] == 'control-group' and record['before']['Restart'] == 'no'
            and bool(record['before']['ExecStopPost']),
        'original_processes_terminated': record['original_processes_terminated'] is True,
        'supervised_cleanup': receipt['status'] == 'finished' and receipt['cleanup'] == 'deleted'
            and receipt['accounting'] == 'recorded' and not any(receipt['remaining'].values())
            and record['stop_requested_at'] <= receipt['started_at'] <= receipt['finished_at']
            <= record['stop_requested_at'] + record['declaration']['cleanup_deadline_seconds'],
        'original_invocation_receipt': bool(record['before'].get('InvocationID'))
            and receipt.get('invocation_id') == record['before']['InvocationID'],
        'interrupted_owner_not_completed': card['owner_window_completed'] is False and card['owner_finished'] is False,
        'frozen_calendar_retained': len(samples) == 12 and len(known) >= 4 and len(later) >= 3
            and all(s['verdict'] == 'unknown' and s['coverage'] == 'missing' for s in later),
        'initial_health_observed': all(s['verdict'] == 'verified_success' for s in samples[:3]),
        'original_committed_samples_preserved': bool(record['sample_sha256_before'])
            and card['sample_sha256'] == record['sample_sha256_before'] == receipt['sample_sha256']
            and receipt['original_evidence_unchanged'] is True,
        'workload_unchanged_until_termination': len(card['identities_before']) >= 11
            and card['identities_before'] == record['identities_at_barrier'] and card['identities_after'] is None,
        'protected_observed_state': all(s['verdict'] == 'verified_success' or routing_only(s.get('reasons', [])) for s in known),
        'one_unrecorded_effect': len(operations) == 1 and card['dispatch_budget_reserved'] == 1 and card['contract']['max_dispatches'] == 2,
        'audit_complete': audit['status'] == 'assessed' and audit['successful_unmatched_mutations'] == 0,
        'no_restart_replay': record['launch_claim_unchanged'] is True and record['post_stop_receipt_unchanged'] is True
            and (record['restart_refused'] is True if record['mode'] == 'restart' else record['after']['ExecMainStatus'] == '9'),
    }
    writes = [e for e in audit['events'] if e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}
              and e.get('objectRef', {}).get('resource') == 'services'
              and type(e.get('responseStatus', {}).get('code')) is int and 200 <= e['responseStatus']['code'] < 300]
    if len(operations) == 1:
        op = operations[0]
        op_id, request = op['operation_id'], op['request']
        repairs = [e for e in writes if e.get('userAgent') == 'autonomy-lab-operation/' + op_id
                   and e.get('user', {}).get('username') == 'system:serviceaccount:autonomy-lab:broker']
        fault = record['fault']
        injections = [e for e in writes if e.get('userAgent') == 'autonomy-lab-operation/ambiguity-fault'
                      and e.get('user', {}).get('username') == 'kubernetes-admin' and e.get('requestObject') == fault['patch']
                      and fault['requested_at'] <= epoch(e['requestReceivedTimestamp']) <= fault['finished_at']]
        checks['exact_attributed_mutations'] = (len(writes) == 2 and len(repairs) == len(injections) == 1
            and audit['correlated_mutations'] == [{'audit_id': repairs[0]['auditID'], 'operation_id': op_id}]
            and {e['auditID'] for e in writes} == {repairs[0]['auditID'], injections[0]['auditID']}
            and request['service_uid'] == card['identities_before']['Service/inventory']
            and request['run_id'] == record['run_id'] and request['expected_target_port'] == 9999 and request['target_port'] == 8080
            and epoch(op['created_at']) <= epoch(repairs[0]['requestReceivedTimestamp'])
            <= epoch(repairs[0]['stageTimestamp']) <= record['barrier']['at'] <= record['stop_requested_at'])
        checks['effect_not_invented_as_acknowledged'] = (op['status'] == 'dispatching' and op['result'] is None and op['reconciliation'] is None
            and op_id == record['barrier']['operation_id'] and [e['event'] for e in journal] == ['prepared', 'dispatching']
            and all(e['operation_id'] == op_id for e in journal))
        worker = next((w for w in card['workers'] if w['id'] == record['operator']), None)
        checks['interrupted_episode_uncommitted'] = (worker is not None and worker['failure'] is None and worker['finished'] is None
            and sum(ep['outcome'] is None for ep in worker['episodes']) == 1)
    else:
        checks['interrupted_effect_evidence'] = False
    checks['fault_observed_before_resume'] = any(s['verdict'] == 'verified_failure'
        and s.get('started_at', 0) >= record['fault']['finished_at']
        and s.get('finished_at', float('inf')) <= record['operator_resumed_at']
        and client_path_failed(raw[s['slot']]['verification']) for s in known)
    checks['frozen_schedule'] = all(0 <= actual - target <= record['declaration']['schedule_lateness_seconds'] for actual, target in [
        (record['operator_paused_at'], window['start'] + 20), (record['fault']['requested_at'], window['start'] + 25),
        (record['operator_resumed_at'], window['start'] + 35),
    ]) and (record['barrier']['at'] <= window['start'] + 65
            and 0 <= record['stop_requested_at'] - record['barrier']['at'] <= record['declaration']['stop_after_barrier_seconds'])
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks, 'mode': record['mode'],
            'sample_counts': card['sample_counts'], 'known_slots': [s['slot'] for s in known],
            'unknown_slots': [s['slot'] for s in samples if s['verdict'] == 'unknown'],
            'cleanup_seconds': receipt['finished_at'] - record['stop_requested_at'],
            'execution_audit': {k: v for k, v in audit.items() if k != 'events'},
            'limits': ['Original owner, workers and janitor share the killed systemd control group; recovery requires the surviving host supervisor.',
                       'Unknown future measurements are retained, not service failures or successful observations.',
                       'This does not establish host/power-loss recovery, exactly-once effects, or continuous availability.']}
