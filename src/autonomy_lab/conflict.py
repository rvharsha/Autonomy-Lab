"""Reproduce a real conditional rejection; baseline failure is not improvement."""

import hashlib
import json

from autonomy_lab.ambiguity import journal_events
from autonomy_lab.campaign import Contract, read
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.experiments import release_manifest
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require, verify_record
from autonomy_lab.recurrence import epoch, routing_only

ANNOTATION = 'autonomy-lab/conditional-conflict'


def declaration():
    paths = ['scripts/check_conflict.py', 'scripts/check_ambiguity.py',
             'scripts/check_campaign.py', 'scripts/check_recurrence.py',
             'scenarios/campaign-conflict.json']
    return {
        'case': 'current_fallback_conditional_rejection', 'evidence_use': 'development',
        'stop_offset': 20, 'inject_offset': 25, 'repair_start_offset': 45,
        'barrier_deadline_offset': 65, 'release_deadline_seconds': 3,
        'escalation_deadline_seconds': 15, 'schedule_lateness_seconds': 3,
        'contract': Contract.model_validate(read(ROOT / paths[-1])).model_dump(),
        'release_files': release_manifest({})['files'],
        'gate_sources': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
    }


def annotation_patch(service, operation_id):
    return [
        {'op': 'test', 'path': '/metadata/uid', 'value': service['metadata']['uid']},
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': service['metadata']['resourceVersion']},
        {'op': 'add', 'path': '/metadata/annotations',
         'value': {**service['metadata'].get('annotations', {}), ANNOTATION: operation_id}},
    ]


def repair_patch(request):
    return [
        {'op': 'test', 'path': '/metadata/uid', 'value': request['service_uid']},
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': request['resource_version']},
        {'op': 'test', 'path': '/spec/ports/0/name', 'value': 'http'},
        {'op': 'test', 'path': '/spec/ports/0/targetPort', 'value': request['expected_target_port']},
        {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': request['target_port']},
    ]


def assess_case(card, spec, record, prior, barrier, journal, captured, evidence, raw_samples):
    """Pure evidence checks. Unit inputs are authored; the real gate supplies API records."""
    window = card['window']
    mutations = [e for e in captured['events']
              if e.get('objectRef', {}).get('namespace') == 'autonomy-lab'
              and e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}
              and window['start'] <= epoch(e['requestReceivedTimestamp']) <= window['end']]
    writes = [e for e in mutations if e.get('objectRef', {}).get('resource') == 'services']
    actor_attempts = [e for e in mutations if e.get('user', {}).get('username') in {
        'system:serviceaccount:autonomy-lab:' + role for role in ('broker', 'observer', 'verifier')}]
    checks = {
        'closed_audit': captured.get('collection_closed') is True and captured['malformed_lines'] == 0,
        'unchanged_workload': card['identities_unchanged'] is True and len(card['identities_before']) >= 11,
        'owner_cleanup': card['owner_finished'] and (card['cleanup'] or {}).get('status') == 'deleted',
        'complete_calendar': len(card['samples']) == 12 and card['sample_counts'] == {
            'verified_success': 3, 'verified_failure': 9, 'unknown': 0},
        'protected_invariants': all(s['verdict'] == 'verified_success' or routing_only(s.get('reasons', []))
                                    for s in card['samples']),
        'one_operation_budget_remaining': len(card['operations']) == len(prior) == 1
            and card['dispatch_budget_reserved'] == 1 and card['contract']['max_dispatches'] == 2,
        'two_operators_one_observer': len(card['workers']) == 3
            and sum(w['id'].startswith('operator-') for w in card['workers']) == 2
            and sum(w['id'].startswith('observer-') for w in card['workers']) == 1,
    }
    detail = {}
    try:
        require(checks['one_operation_budget_remaining'], 'Missing original operation')
        op = card['operations'][0]
        request = json.loads(op['request'])
        op_id = op['operation_id']
        before, changed, after = (record[k] for k in ('before_change', 'changed_service', 'after_rejection'))
        fault, change = record['fault'], record['change']
        repair = next(w for w in card['workers'] if w['id'] == record['repair_worker'])
        initial = next(w for w in card['workers'] if w['id'] == record['initial_worker'])
        rows = evidence[repair['id']]
        require(len(rows) == len(repair['episodes']) == 1, 'Repair episode missing or duplicated')
        episode = repair['episodes'][0]
        tools = rows[0]['records']
        require(bool(tools), 'Missing tool evidence')

        def matched(tag, actor, patch, codes):
            return [e for e in writes if e.get('stage') == 'ResponseComplete'
                    and e.get('userAgent') == 'autonomy-lab-operation/' + tag
                    and e.get('user', {}).get('username') == actor
                    and e.get('objectRef', {}).get('resource') == 'services'
                    and e.get('objectRef', {}).get('name') == 'inventory' and e['verb'] == 'patch'
                    and type(e.get('responseStatus', {}).get('code')) is int
                    and e['responseStatus']['code'] in codes and e.get('requestObject') == patch]

        fault_patch = repair_patch({**request, 'resource_version': fault['patch'][1]['value'],
                                    'expected_target_port': 8080, 'target_port': 9999})
        faults = matched('ambiguity-fault', 'kubernetes-admin', fault_patch, range(200, 300))
        changes = matched('conflict-version-bump', 'kubernetes-admin', annotation_patch(before, op_id), range(200, 300))
        rejections = matched(op_id, 'system:serviceaccount:autonomy-lab:broker', repair_patch(request), {409, 422})
        require(len(faults) == len(changes) == len(rejections) == 1, 'Independent API requests do not match')
        rejected, bumped, injected = rejections[0], changes[0], faults[0]
        checks['exact_api_attempts'] = (len(writes) == 3 and len({e['auditID'] for e in writes}) == 3
                                       and {e['auditID'] for e in writes} == {rejected['auditID'], bumped['auditID'], injected['auditID']})
        checks['no_other_actor_mutations'] = [e['auditID'] for e in actor_attempts] == [rejected['auditID']]
        checks['independent_change_response'] = bumped['responseObject'] == changed
        checks['same_identity_and_spec_only_version_changed'] = (
            before['metadata']['uid'] == changed['metadata']['uid'] == after['metadata']['uid']
            == request['service_uid'] == card['identities_before']['Service/inventory']
            and before['spec'] == changed['spec'] == after['spec'] == injected['responseObject']['spec']
            and before['spec']['ports'][0]['name'] == 'http' and before['spec']['ports'][0]['targetPort'] == 9999
            and before['metadata']['resourceVersion'] == request['resource_version'] == injected['responseObject']['metadata']['resourceVersion']
            and changed['metadata']['resourceVersion'] == after['metadata']['resourceVersion'] != request['resource_version']
            and changed['metadata']['annotations'] == annotation_patch(before, op_id)[-1]['value'])
        checks['prepared_then_rejected_and_budget_retained'] = (
            prior[0]['operation_id'] == barrier['operation_id'] == op_id
            and prior[0]['status'] == 'prepared' and prior[0]['budget_reserved'] == 1
            and prior[0]['result'] is None and prior[0]['owner'] is None
            and prior[0]['request'] == op['request'] and op['status'] == 'rejected'
            and op['reason'] == 'api_rejected_' + str(rejected['responseStatus']['code'])
            and op['budget_reserved'] == 1 and json.loads(op['result'] or 'null') is None
            and op['reconciliation'] is None
            and [e['event'] for e in journal] == ['prepared', 'dispatching', 'rejected']
            and all(e['operation_id'] == op_id for e in journal)
            and journal[-1]['details']['reason'] == op['reason'])
        checks['original_scope'] = (request['run_id'] == record['run_id'] and request['namespace'] == 'autonomy-lab'
            and request['service_name'] == 'inventory' and request['port_name'] == 'http'
            and request['expected_target_port'] == 9999 and request['target_port'] == 8080)
        checks['actual_rejection_after_release'] = (
            repair['ready']['at'] <= epoch(op['created_at']) <= barrier['at'] <= change['requested_at']
            <= epoch(bumped['requestReceivedTimestamp']) <= epoch(bumped['stageTimestamp']) <= change['finished_at']
            <= record['release_requested_at'] <= epoch(journal[1]['timestamp'])
            <= epoch(rejected['requestReceivedTimestamp']) <= epoch(rejected['stageTimestamp'])
            <= epoch(journal[-1]['timestamp']) <= record['after_rejection_at']
            and 0 <= record['release_requested_at'] - change['finished_at'] <= spec['release_deadline_seconds'])
        claim = episode['outcome']['claim']
        checks['escalated_without_followup'] = (
            repair['failure'] is None and claim['outcome'] == 'escalated'
            and tools[-1]['source'] == 'finish' and tools[-1]['payload'] == claim
            and [t['source'] for t in tools] == ['observe_service', 'probe_backend', 'probe_application', 'propose_repair', 'finish']
            and tools[3]['payload']['operation_id'] == op_id and tools[3]['payload']['status'] == 'rejected'
            and tools[3]['payload']['reason'] == op['reason']
            and epoch(journal[-1]['timestamp']) <= epoch(tools[3]['timestamp']) <= epoch(tools[-1]['timestamp'])
            <= episode['outcome']['finished_at'] <= repair['finished']['at']
            <= record['release_requested_at'] + spec['escalation_deadline_seconds'])
        completed = [e for e in initial['episodes'] if e['outcome'] is not None]
        interrupted = [e for e in initial['episodes'] if e['outcome'] is None]
        checks['healthy_initial_episodes'] = (
            bool(completed) and all(e['outcome']['claim']['outcome'] == 'healthy'
                and e['attempt']['started_at'] <= e['outcome']['finished_at'] <= record['initial_stopped_at']
                for e in completed)
            and len(interrupted) <= 1 and all(
                max(e['outcome']['finished_at'] for e in completed) <= e['attempt']['started_at']
                <= record['initial_stopped_at'] for e in interrupted))
        checks['frozen_schedule'] = all(0 <= actual - target <= spec['schedule_lateness_seconds'] for actual, target in [
            (record['initial_stop_requested_at'], window['start'] + spec['stop_offset']),
            (fault['requested_at'], window['start'] + spec['inject_offset']),
            (record['repair_requested_at'], window['start'] + spec['repair_start_offset']),
        ]) and (record['initial_stop_requested_at'] <= record['initial_stopped_at'] <= fault['requested_at']
                <= epoch(injected['requestReceivedTimestamp']) <= epoch(injected['stageTimestamp']) <= fault['finished_at']
                <= record['repair_requested_at'] <= repair['ready']['at'] <= barrier['at']
                <= window['start'] + spec['barrier_deadline_offset']
                and repair['ready']['at'] - record['initial_stopped_at'] <= card['contract']['max_restart_downtime_seconds'])
        checks['failure_before_and_after_rejection'] = (
            any(s['started_at'] >= fault['finished_at'] and s['finished_at'] <= record['repair_requested_at']
                and client_path_failed(s['verification']) for s in raw_samples)
            and all(s['verdict'] == ('verified_success' if s['scheduled_at'] < fault['requested_at'] else 'verified_failure')
                    for s in card['samples']))
        detail = {'operation_id': op_id, 'api_status': rejected['responseStatus']['code'],
                  'rejected_audit_id': rejected['auditID'], 'change_audit_id': bumped['auditID'],
                  'budget_spent': 1, 'budget_remaining': 1,
                  'interrupted_initial_episodes': len(interrupted),
                  'old_resource_version': request['resource_version'],
                  'new_resource_version': changed['metadata']['resourceVersion']}
        checks['required_evidence_present'] = True
    except (KeyError, TypeError, ValueError, IndexError, StopIteration):
        checks['required_evidence_present'] = False
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
            'operation': detail, 'service_sample_counts': card['sample_counts'],
            'limits': ['Development evidence for the current deterministic fallback, not a sealed test or learned improvement.',
                       'Correct escalation leaves the service failed; the calendar retains this customer impact.',
                       'Trusted controller, host, clock and storage; bounded sampled windows, not production availability.']}


def episode_records(path, committed):
    """Retain, but never interpret, an interrupted append without its newline."""
    raw = path.read_bytes() if path.exists() else b''
    complete, _, tail = raw.rpartition(b'\n')
    records = [json.loads(line) for line in complete.splitlines()]
    require(not committed or (not tail and bool(records)), 'Incomplete committed evidence')
    return {'records': records, 'uncommitted_bytes': len(tail),
            'uncommitted_sha256': hashlib.sha256(tail).hexdigest() if tail else None}


def evaluate(gate):
    directory = gate / 'campaign'
    spec = read(gate / 'declaration.json')
    require(spec == declaration(), 'Protocol or release changed')
    card = scorecard(directory)
    require(card['contract'] == spec['contract'], 'Campaign differs from frozen contract')
    sources = {p: sha for p, sha in spec['release_files'].items()
               if p.startswith('src/autonomy_lab/') or p in {
                   'fixtures/expectations.json', 'fixtures/database.sql', 'infra/toolchain.json'}}
    require(card['source_sha256'] == sources, 'Campaign source differs from release')
    samples = [read(p) for p in sorted((directory / 'samples').glob('*.json'))]
    for sample in samples:
        verify_record(sample['verification'], card['contract']['sample_window_seconds'])
    evidence = {}
    for worker in card['workers']:
        evidence[worker['id']] = []
        for episode in worker['episodes']:
            path = directory / 'workers' / worker['id'] / episode['id']
            observed = episode_records(path / 'evidence.jsonl', episode['outcome'] is not None)
            records = observed['records']
            evidence[worker['id']].append({'id': episode['id'], **observed})
            if episode['outcome'] is not None:
                require(records[-1]['source'] == 'finish'
                        and records[-1]['payload'] == episode['outcome']['claim'], 'Terminal evidence differs')
            for verification in path.glob('verification-*.json'):
                verify_record(read(verification), card['contract']['sample_window_seconds'])
    record = read(gate / 'record.json')
    barrier = read(directory / 'workers' / record['repair_worker'] / 'preflight-barrier.json')
    release = read(directory / 'workers' / record['repair_worker'] / 'preflight-release.json')
    require(release == {'operation_id': barrier['operation_id']}, 'Release operation differs')
    assessment = assess_case(card, spec, record, read(gate / 'before-release.json'), barrier,
                             journal_events(directory), read(gate / 'server-audit.json'), evidence, samples)
    assessment['uncommitted_evidence'] = [
        {'worker': worker, 'episode': e['id'], 'bytes': e['uncommitted_bytes'], 'sha256': e['uncommitted_sha256']}
        for worker, episodes in evidence.items() for e in episodes if e['uncommitted_bytes']]
    return assessment
