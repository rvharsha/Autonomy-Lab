"""Development comparison for authored bounded refresh, not generated learning."""

import hashlib
import json

from autonomy_lab import ambiguity, conflict
from autonomy_lab.campaign import Contract, read
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from autonomy_lab.recurrence import epoch, routing_only
from autonomy_lab.runbook import _backend_works, _service_scope

CASES = ('stable', 'continuing', 'uncertain_external_change')


def declaration(case):
    require(case in CASES, 'Unknown refresh case')
    spec = conflict.declaration()
    if case == 'uncertain_external_change':
        spec.update(ambiguity.declaration('external_change'))
    manifest = 'scenarios/campaign-refresh' + ('-uncertain' if case == 'uncertain_external_change' else '') + '.json'
    paths = [*spec['gate_sources'], 'scripts/check_refresh.py', manifest]
    return {**spec, 'refresh_case': case, 'evidence_use': 'development',
            'manifest': manifest, 'second_barrier_deadline_seconds': 10,
            'contract': Contract.model_validate(read(ROOT / manifest)).model_dump(),
            'gate_sources': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}}


def assess_case(card, spec, record, journal, captured, evidence, raw_samples):
    """Check actual requests, causal observations, two distinct intents and the full calendar."""
    window = card['window']
    stable = spec['refresh_case'] == 'stable'
    mutations = [e for e in captured['events'] if e.get('objectRef', {}).get('namespace') == 'autonomy-lab'
                 and e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}
                 and window['start'] <= epoch(e['requestReceivedTimestamp']) <= window['end']]
    writes = [e for e in mutations if e.get('objectRef', {}).get('resource') == 'services']
    actors = [e for e in mutations if e.get('user', {}).get('username') in {
        'system:serviceaccount:autonomy-lab:' + role for role in ('broker', 'observer', 'verifier')}]
    checks = {
        'closed_audit': captured.get('collection_closed') is True and captured['malformed_lines'] == 0,
        'unchanged_workload': card['identities_unchanged'] is True and len(card['identities_before']) >= 11,
        'owner_cleanup': card['owner_finished'] and (card['cleanup'] or {}).get('status') == 'deleted',
        'complete_calendar': len(card['samples']) == 12 and card['sample_counts']['unknown'] == 0,
        'protected_invariants': all(s['verdict'] == 'verified_success' or routing_only(s.get('reasons', [])) for s in card['samples']),
        'two_spent_dispatches': len(card['operations']) == 2 and card['dispatch_budget_reserved'] == 2
            and card['contract']['max_dispatches'] == 2,
        'two_operators_one_observer': len(card['workers']) == 3
            and sum(w['id'].startswith('operator-') for w in card['workers']) == 2
            and sum(w['id'].startswith('observer-') for w in card['workers']) == 1,
    }
    detail = {}
    try:
        require(checks['two_spent_dispatches'], 'Expected two operations')
        operations = card['operations']
        requests = [json.loads(op['request']) for op in operations]
        ids = [op['operation_id'] for op in operations]
        attempts = record['attempts']
        require(len(attempts) == 2 and len(set(ids)) == 2, 'Distinct attempts missing')
        repair = next(w for w in card['workers'] if w['id'] == record['repair_worker'])
        initial = next(w for w in card['workers'] if w['id'] == record['initial_worker'])
        episodes = sorted(repair['episodes'], key=lambda e: e['attempt']['started_at'])
        episode = episodes[0]
        tools = next(e['records'] for e in evidence[repair['id']] if e['id'] == episode['id'])
        claim = episode['outcome']['claim']
        api_ids, broker_ids, api_operations = [], [], []

        def match(tag, actor, patch, codes):
            found = [e for e in writes if e.get('stage') == 'ResponseComplete'
                     and e.get('userAgent') == 'autonomy-lab-operation/' + tag
                     and e.get('user', {}).get('username') == actor
                     and e.get('objectRef', {}).get('name') == 'inventory' and e['verb'] == 'patch'
                     and type(e.get('responseStatus', {}).get('code')) is int
                     and e['responseStatus']['code'] in codes and e.get('requestObject') == patch]
            require(len(found) == 1, 'Exact API request missing or duplicated')
            api_ids.append(found[0]['auditID'])
            return found[0]

        fault = record['fault']
        injected = match('ambiguity-fault', 'kubernetes-admin', conflict.repair_patch({
            **requests[0], 'resource_version': fault['patch'][1]['value'],
            'expected_target_port': 8080, 'target_port': 9999}), range(200, 300))
        previous_service = injected['responseObject']
        for index, (op, request, attempt) in enumerate(zip(operations, requests, attempts, strict=True)):
            key = 'attempt_' + str(index + 1)
            barrier, before = attempt['barrier'], attempt['before']
            prior = attempt['operations']
            history = [e for e in journal if e['operation_id'] == op['operation_id']]
            rejection = index == 0 or not stable
            checks[key + '_scope'] = (
                request['operation_id'] == op['operation_id'] and request['run_id'] == record['run_id']
                and request['namespace'] == 'autonomy-lab' and request['service_name'] == 'inventory'
                and request['service_uid'] == card['identities_before']['Service/inventory']
                and request['port_name'] == 'http' and request['expected_target_port'] == 9999 and request['target_port'] == 8080
                and request['resource_version'] == before['metadata']['resourceVersion']
                and before['metadata']['uid'] == request['service_uid'] and before['spec'] == previous_service['spec']
                and before['metadata']['resourceVersion'] == previous_service['metadata']['resourceVersion'])
            checks[key + '_prepared_and_released'] = (
                len(prior) == index + 1 and prior[-1]['operation_id'] == op['operation_id'] == barrier['operation_id']
                and prior[-1]['status'] == 'prepared' and prior[-1]['budget_reserved'] == 1
                and prior[-1]['owner'] is None and prior[-1]['result'] is None
                and prior[-1]['request'] == op['request']
                and all(p['status'] == 'rejected' and p['budget_reserved'] == 1 for p in prior[:-1])
                and attempt['release'] == {'operation_id': op['operation_id']})
            require([e['event'] for e in history] == ['prepared', 'dispatching', 'rejected' if rejection else 'acknowledged'],
                    'Operation state transition differs')
            if rejection:
                change = attempt['change']
                changed = match('refresh-version-bump-' + str(index + 1), 'kubernetes-admin',
                                conflict.annotation_patch(before, op['operation_id']), range(200, 300))
                response = changed['responseObject']
                checks[key + '_only_annotation_changed'] = (
                    response == attempt['changed_service'] and response['spec'] == before['spec']
                    and response['metadata']['uid'] == before['metadata']['uid']
                    and response['metadata']['resourceVersion'] != before['metadata']['resourceVersion']
                    and response['metadata']['annotations'] == conflict.annotation_patch(before, op['operation_id'])[-1]['value'])
                checks[key + '_change_after_preflight'] = (
                    barrier['at'] <= change['requested_at'] <= epoch(changed['requestReceivedTimestamp'])
                    <= epoch(changed['stageTimestamp']) <= change['finished_at'] <= attempt['release_requested_at']
                    <= change['finished_at'] + spec['release_deadline_seconds'])
                previous_service = response
            else:
                checks[key + '_no_second_interference'] = 'change' not in attempt
            api = match(op['operation_id'], 'system:serviceaccount:autonomy-lab:broker',
                        conflict.repair_patch(request), {409, 422} if rejection else range(200, 300))
            api_operations.append(api)
            broker_ids.append(api['auditID'])
            checks[key + '_terminal_budget_and_result'] = (
                op['status'] == ('rejected' if rejection else 'acknowledged') and op['budget_reserved'] == 1
                and op['reconciliation'] is None and bool(op['owner'])
                and (op['reason'] == 'api_rejected_' + str(api['responseStatus']['code'])
                     and json.loads(op['result'] or 'null') is None if rejection
                     else json.loads(op['result']) == api['responseObject']))
            checks[key + '_causal_dispatch'] = (
                epoch(op['created_at']) <= barrier['at'] <= attempt['read_at'] <= attempt['release_requested_at']
                <= epoch(history[1]['timestamp']) <= epoch(api['requestReceivedTimestamp'])
                <= epoch(api['stageTimestamp']) <= epoch(history[2]['timestamp']))
            if not rejection:
                previous_service = api['responseObject']
        checks['exact_api_attempts'] = len(writes) == len(set(api_ids)) == (4 if stable else 5)
        checks['no_other_actor_mutations'] = sorted(e['auditID'] for e in actors) == sorted(broker_ids)
        checks['exact_journal'] = len(journal) == 6 and [e['operation_id'] for e in journal] == [ids[0]] * 3 + [ids[1]] * 3
        checks['distinct_fresh_version'] = requests[1]['resource_version'] != requests[0]['resource_version']
        checks['fresh_diagnosis_after_rejection'] = (
            [t['source'] for t in tools] == ['observe_service', 'probe_backend', 'probe_application', 'propose_repair',
                'observe_service', 'probe_backend', 'probe_application', 'propose_repair',
                *(['verify_recovery'] if stable else []), 'finish']
            and epoch(api_operations[0]['stageTimestamp']) <= epoch(tools[3]['timestamp'])
            < epoch(tools[4]['timestamp']) <= epoch(tools[5]['timestamp']) <= epoch(tools[6]['timestamp'])
            <= epoch(operations[1]['created_at'])
            and _service_scope(tools[4]['payload']) is not None
            and tools[4]['payload']['run_id'] == requests[1]['run_id']
            and tools[4]['payload']['service']['metadata']['uid'] == requests[1]['service_uid']
            and tools[4]['payload']['service']['metadata']['resourceVersion'] == requests[1]['resource_version']
            and tools[4]['payload']['service']['spec']['ports'][0]['targetPort'] == requests[1]['expected_target_port']
            and _backend_works(tools[5]['payload']) and tools[5]['payload']['backend_port'] == 8080
            and tools[6]['payload']['kind'] == 'response' and tools[6]['payload']['status_code'] == 503
            and tools[6]['payload']['body'] == {'detail': 'inventory unavailable'}
            and all(t['observation_id'] in requests[1]['evidence_ids'] for t in tools[:7]))
        checks['received_operation_matches_journal'] = all(
            tools[n]['payload']['operation_id'] == ids[i] and tools[n]['payload']['request'] == requests[i]
            and tools[n]['payload']['status'] == operations[i]['status']
            and tools[n]['payload'].get('reason') == operations[i]['reason']
            and tools[n]['payload']['budget_used'] == i + 1 and tools[n]['payload']['budget_limit'] == 2
            and tools[n]['payload']['budget_reserved'] is True for i, n in enumerate((3, 7)))
        checks['bounded_terminal'] = (repair['failure'] is None and tools[-1]['payload'] == claim
            and claim['outcome'] == ('resolved' if stable else 'escalated')
            and epoch(api_operations[-1]['stageTimestamp']) <= epoch(tools[7]['timestamp'])
            <= epoch(tools[-1]['timestamp']) <= episode['outcome']['finished_at']
            <= attempts[0]['release_requested_at'] + spec['escalation_deadline_seconds']
            and (stable or (len(repair['episodes']) == 1 and repair['finished']['at'] <= attempts[0]['release_requested_at'] + spec['escalation_deadline_seconds'])))
        checks['independently_verified_recovery'] = not stable or tools[-2]['payload']['verdict'] == 'verified_success'
        completed = [e for e in initial['episodes'] if e['outcome'] is not None]
        interrupted = [e for e in initial['episodes'] if e['outcome'] is None]
        checks['healthy_initial_episodes'] = bool(completed) and all(
            e['outcome']['claim']['outcome'] == 'healthy' and e['attempt']['started_at'] <= e['outcome']['finished_at'] <= record['initial_stopped_at'] for e in completed
        ) and len(interrupted) <= 1 and all(max(e['outcome']['finished_at'] for e in completed) <= e['attempt']['started_at'] <= record['initial_stopped_at'] for e in interrupted)
        checks['later_episodes_no_mutation'] = all(e['outcome'] is None or e['outcome']['claim']['outcome'] == 'healthy' for e in episodes[1:])
        checks['frozen_schedule'] = all(0 <= actual - target <= spec['schedule_lateness_seconds'] for actual, target in [
            (record['initial_stop_requested_at'], window['start'] + spec['stop_offset']),
            (fault['requested_at'], window['start'] + spec['inject_offset']),
            (record['repair_requested_at'], window['start'] + spec['repair_start_offset']),
        ]) and (record['initial_stop_requested_at'] <= record['initial_stopped_at'] <= fault['requested_at']
            <= epoch(injected['requestReceivedTimestamp']) <= epoch(injected['stageTimestamp']) <= fault['finished_at']
            <= record['repair_requested_at'] <= repair['ready']['at'] <= attempts[0]['barrier']['at']
            <= window['start'] + spec['barrier_deadline_offset']
            and attempts[1]['barrier']['at'] <= attempts[0]['release_requested_at'] + spec['second_barrier_deadline_seconds']
            and repair['ready']['at'] - record['initial_stopped_at'] <= card['contract']['max_restart_downtime_seconds'])
        checks['customer_failure_before_repair'] = any(s['started_at'] >= fault['finished_at']
            and s['finished_at'] <= record['repair_requested_at'] and client_path_failed(s['verification']) for s in raw_samples)
        post = [s for s in card['samples'] if s['scheduled_at'] > episode['outcome']['finished_at']]
        checks['customer_outcome_retained'] = bool(post) and all(s['verdict'] == ('verified_success' if stable else 'verified_failure') for s in post)
        checks['controller_final_read_matches_api'] = (record['after_operations'] == previous_service
            and episode['outcome']['finished_at'] <= record['after_operations_at'] <= window['end'])
        detail = {'operation_ids': ids, 'api_statuses': [a['responseStatus']['code'] for a in api_operations],
                  'budget_spent': 2, 'budget_remaining': 0, 'outcome': claim['outcome'],
                  'interrupted_initial_episodes': len(interrupted)}
        checks['required_evidence_present'] = True
    except (KeyError, TypeError, ValueError, IndexError, StopIteration):
        checks['required_evidence_present'] = False
    return {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks, 'operations': detail,
            'service_sample_counts': card['sample_counts'],
            'limits': ['Authored deterministic baseline and development cases; no generated candidate or sealed evaluation.',
                       'Trusted controller, host, clock and storage; sampled windows are not production availability.',
                       'Admission of this two-dispatch procedure is not implemented.']}


def evaluate(gate):
    spec = read(gate / 'declaration.json')
    require(spec == declaration(spec['refresh_case']), 'Protocol or release changed')
    card, samples, evidence = conflict.load_evidence(gate, spec)
    directory = gate / 'campaign'
    captured, record = read(gate / 'server-audit.json'), read(gate / 'record.json')
    journal = ambiguity.journal_events(directory)
    if spec['refresh_case'] == 'uncertain_external_change':
        barrier = read(directory / 'workers' / record['repair_worker'] / 'dispatch-barrier.json')
        result = ambiguity.assess_case(card, spec, record, read(gate / 'before-kill.json'), barrier,
                                      journal, captured, {s['slot']: s for s in samples})
        mutations = [e for e in captured['events'] if e.get('objectRef', {}).get('namespace') == 'autonomy-lab'
                     and e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}
                     and card['window']['start'] <= epoch(e['requestReceivedTimestamp']) <= card['window']['end']]
        actor_attempts = [e for e in mutations if e.get('user', {}).get('username') in {
            'system:serviceaccount:autonomy-lab:' + r for r in ('broker', 'observer', 'verifier')}]
        # Exactly three successful requests: admin fault, broker repair, admin
        # external change. ANY additional attempt (including rejection) fails.
        service_attempts = [e for e in mutations if e.get('objectRef', {}).get('resource') == 'services']
        result['checks']['exact_service_attempts'] = len(service_attempts) == 3 and all(
            e.get('stage') == 'ResponseComplete' and type(e.get('responseStatus', {}).get('code')) is int
            and 200 <= e['responseStatus']['code'] < 300 for e in service_attempts)
        result['checks']['closed_audit'] = captured.get('collection_closed') is True and captured['malformed_lines'] == 0
        result['checks']['exact_actor_attempts'] = len(actor_attempts) == 1 and actor_attempts[0]['userAgent'] == 'autonomy-lab-operation/' + barrier['operation_id']
        result['status'] = 'passed' if result['status'] == 'passed' and all(result['checks'].values()) else 'failed'
    else:
        for attempt in record['attempts']:
            base = directory / 'workers' / record['repair_worker'] / 'preflight' / attempt['barrier']['operation_id']
            require(read(base / 'preflight-barrier.json') == attempt['barrier'], 'Barrier differs')
            require(read(base / 'preflight-release.json') == attempt['release'], 'Release differs')
        result = assess_case(card, spec, record, journal, captured, evidence, samples)
    result['uncommitted_evidence'] = [
        {'worker': worker, 'episode': e['id'], 'bytes': e['uncommitted_bytes'], 'sha256': e['uncommitted_sha256']}
        for worker, episodes in evidence.items() for e in episodes if e['uncommitted_bytes']]
    return result
