"""Development comparison of immediate retry and later repair opportunity.

The policies are authored. This tests a finite campaign budget, not learning,
production availability, or the optimal policy for an unknown incident mix.
"""

import hashlib
import json
import math
from collections import Counter

from autonomy_lab.ambiguity import journal_events
from autonomy_lab.campaign import Contract, read
from autonomy_lab.conflict import annotation_patch, load_evidence, repair_patch
from autonomy_lab.experiments import release_manifest
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedure import freeze, verify_bindings
from autonomy_lab.procedures import require
from autonomy_lab.recurrence import epoch, routing_only

ARMS = ('refresh', 'single_attempt', 'no_repair')


def declaration(arm):
    require(arm in ARMS, 'Unknown comparison policy')
    raw = (ROOT / 'procedures/bounded-refresh.json').read_bytes()
    if arm != 'refresh':
        values = json.loads(raw)
        values['conditional_rejection'] = 'escalate'
        if arm == 'no_repair':
            values['repairable_routing'] = 'escalate'
        raw = (json.dumps(values, indent=2) + '\n').encode()
    contract = Contract.model_validate({
        **read(ROOT / 'scenarios/campaign-program-refresh.json'),
        'duration_seconds': 210, 'max_operator_starts': 3,
        'procedure_program': raw.decode(),
    }).model_dump()
    paths = ['scripts/check_budget_horizon.py', 'scripts/check_campaign.py',
             'scripts/check_recurrence.py', 'scripts/check_refresh.py',
             'scripts/check_ambiguity.py', 'procedures/bounded-refresh.json',
             'scenarios/campaign-program-refresh.json', '.github/workflows/budget-horizon.yml']
    return {
        'arm': arm, 'evidence_use': 'authored_development', 'contract': contract,
        'program_pin': freeze(raw), 'release_files': release_manifest({})['files'],
        'gate_sources': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
        'stop_offset': 20, 'fault_offset': 25, 'first_start_offset': 45,
        'external_restore_offset': 80, 'second_fault_offset': 120,
        'second_start_offset': 140, 'response_deadline_seconds': 20,
        'schedule_lateness_seconds': 3,
        'hypothesis': 'Spending both dispatches on first-incident contention prevents a later repair; one attempt may preserve that opportunity.',
    }


def assess_audit(card, captured, record, context='continuing'):
    """Bind every namespace mutation to a declared controller or broker request."""
    require(context in {'stable', 'continuing'}, 'Unknown contention context')
    require(captured['collection_closed'] is True and captured['malformed_lines'] == 0,
            'Audit is not complete')
    window = card['window']
    mutations = [e for e in captured['events']
                 if e.get('objectRef', {}).get('namespace') == 'autonomy-lab'
                 and e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}
                 and window['start'] <= epoch(e['requestReceivedTimestamp']) <= window['end']]
    derived = {
        ('system:serviceaccount:kube-system:endpoint-controller', 'endpoints'),
        ('system:serviceaccount:kube-system:endpointslice-controller', 'endpointslices'),
    }
    writes = []
    for event in mutations:
        pair = (event.get('user', {}).get('username'), event.get('objectRef', {}).get('resource'))
        if pair in derived and event.get('verb') == 'update':
            continue
        require(event.get('objectRef', {}).get('resource') == 'services',
                'Undeclared non-Service mutation')
        writes.append(event)
    seen = set()

    def match(actor, tag, patch, codes, start, end):
        found = [e for e in writes if e.get('stage') == 'ResponseComplete'
                 and e.get('verb') == 'patch' and e.get('objectRef', {}).get('name') == 'inventory'
                 and e.get('user', {}).get('username') == actor
                 and e.get('userAgent') == 'autonomy-lab-operation/' + tag
                 and e.get('requestObject') == patch
                 and type(e.get('responseStatus', {}).get('code')) is int
                 and e['responseStatus']['code'] in codes
                 and start <= epoch(e['requestReceivedTimestamp'])
                 <= epoch(e['stageTimestamp']) <= end]
        require(len(found) == 1 and found[0]['auditID'] not in seen, 'Exact API request missing or duplicated')
        seen.add(found[0]['auditID'])
        return found[0]

    for name in (('fault',) if context == 'stable' else ('fault', 'external_restore', 'second_fault')):
        action = record[name]
        expected, target = (9999, 8080) if name == 'external_restore' else (8080, 9999)
        require(action['patch'] == repair_patch({
            'service_uid': card['identities_before']['Service/inventory'],
            'resource_version': action['patch'][1]['value'],
            'expected_target_port': expected, 'target_port': target,
        }), 'Controller action differs from declared routing change')
        event = match('kubernetes-admin', 'ambiguity-' + name, action['patch'], range(200, 300),
                      action['requested_at'], action['finished_at'])
        require(event['responseObject']['metadata']['resourceVersion'] == action['resource_version'],
                'Controller response differs')
    first = [a for a in record['attempts'] if a['phase'] == 'first']
    earliest = min((a['barrier']['at'] for a in first), default=None)
    for attempt in record['attempts']:
        require(attempt['phase'] in {'first', 'second'}, 'Unknown incident phase')
        conflict = attempt['phase'] == 'first' and (context == 'continuing' or attempt['barrier']['at'] == earliest)
        if not conflict:
            require('change' not in attempt, 'Uncontended repair must have no controller conflict')
            continue
        change = attempt['change']
        patch = annotation_patch(attempt['before'], attempt['operation_id'])
        require(change['patch'] == patch, 'Conflict changed more than the declared annotation')
        event = match('kubernetes-admin', 'horizon-conflict-' + attempt['operation_id'], patch,
                      range(200, 300), change['requested_at'], change['finished_at'])
        after = event['responseObject']
        require(after == attempt['changed_service'] and after['spec'] == attempt['before']['spec']
                and after['metadata']['uid'] == attempt['before']['metadata']['uid']
                and after['metadata']['resourceVersion'] != attempt['before']['metadata']['resourceVersion'],
                'Conflict must preserve identity and configuration')
    dispatches = []
    for op in card['operations']:
        if not op['budget_reserved']:
            require(op['status'] == 'rejected' and op['reason'] == 'budget_exhausted',
                    'Unexpected unsent operation')
            continue
        request = json.loads(op['request'])
        require(request['operation_id'] == op['operation_id'], 'Operation request identity differs')
        codes = range(200, 300) if op['status'] == 'acknowledged' else {409, 422}
        event = match('system:serviceaccount:autonomy-lab:broker', op['operation_id'],
                      repair_patch(request), codes, epoch(op['created_at']), epoch(op['updated_at']))
        attempts = [a for a in record['attempts'] if a['operation_id'] == op['operation_id']]
        require(len(attempts) == 1, 'Dispatch lacks one controller barrier record')
        attempt = attempts[0]
        if context == 'stable':
            incident_start = record['fault']['finished_at'] if attempt['phase'] == 'first' else record['second_requested_at']
            incident_end = record['first_stop_requested_at'] if attempt['phase'] == 'first' else window['end']
        else:
            incident_start = record['fault' if attempt['phase'] == 'first' else 'second_fault']['finished_at']
            incident_end = record['external_restore']['requested_at'] if attempt['phase'] == 'first' else window['end']
        require(incident_start <= attempt['barrier']['at']
                <= epoch(event['requestReceivedTimestamp']) <= epoch(event['stageTimestamp']) < incident_end,
                'Dispatch phase differs from the incident calendar')
        require(request['service_uid'] == attempt['before']['metadata']['uid']
                == card['identities_before']['Service/inventory']
                and request['resource_version'] == attempt['before']['metadata']['resourceVersion']
                and request['expected_target_port'] == 9999 and request['target_port'] == 8080,
                'Dispatch differs from the prepared routing repair')
        require(epoch(op['created_at']) <= attempt['barrier']['at'] <= attempt['release_requested_at']
                <= epoch(event['requestReceivedTimestamp']), 'Dispatch preceded barrier release')
        if 'change' in attempt:
            require(op['status'] == 'rejected', 'Contended dispatch was not rejected')
            require(attempt['barrier']['at'] <= attempt['change']['requested_at']
                    <= attempt['change']['finished_at'] <= attempt['release_requested_at'],
                    'Contention was not introduced before the actual dispatch')
        else:
            require(op['status'] == 'acknowledged', 'Uncontended dispatch was not acknowledged')
        if op['status'] == 'acknowledged':
            metadata = event['responseObject']['metadata']
            require(op['reason'] == 'api_acknowledged' and json.loads(op['result']) == {
                'service_uid': metadata['uid'], 'resource_version': metadata['resourceVersion']},
                'Acknowledgement differs from API response')
        else:
            require(op['status'] == 'rejected' and op['reason'] == 'api_rejected_' + str(event['responseStatus']['code'])
                    and json.loads(op['result']) is None and op['reconciliation'] is None,
                    'Actual API rejection differs from journal')
        dispatches.append(op)
    require(len(record['attempts']) == len(dispatches)
            and {a['operation_id'] for a in record['attempts']} == {o['operation_id'] for o in dispatches},
            'Controller barrier lacks an actual dispatch')
    require(len(writes) == len(seen) and {e['auditID'] for e in writes} == seen,
            'Undeclared or duplicate Service mutation')
    return dispatches


def first_episode_completed_by(worker, deadline):
    """Episode names are UUIDs, so filename order does not imply chronology."""
    require(type(deadline) in (int, float) and math.isfinite(deadline), 'Malformed deadline')
    episodes = worker['episodes']
    if not episodes:
        return False
    starts = [e['attempt']['started_at'] for e in episodes]
    require(all(type(t) in (int, float) and math.isfinite(t) for t in starts),
            'Malformed episode start')
    earliest = min(starts)
    # Clock resolution can tie starts. Every tied earliest attempt must qualify;
    # list order must not select a favorable completion over a missing one.
    for episode in [e for e in episodes if e['attempt']['started_at'] == earliest]:
        if episode['outcome'] is None:
            return False
        finished = episode['outcome']['finished_at']
        require(type(finished) in (int, float) and math.isfinite(finished) and earliest <= finished,
                'Malformed episode completion')
        if finished > deadline:
            return False
    return True


def evaluate(gate):
    spec = read(gate / 'declaration.json')
    require(spec == declaration(spec['arm']), 'Comparison declaration or source changed')
    card, samples, evidence = load_evidence(gate, spec)
    directory = gate / 'campaign'
    record = read(gate / 'record.json')
    window = card['window']
    start = window['start']
    require(len(card['samples']) == 21 and card['sample_counts']['unknown'] == 0,
            'Incomplete customer measurement calendar')
    require(card['identities_unchanged'] is True and len(card['identities_before']) >= 11,
            'Workload identity changed')
    require(card['owner_finished'] and card['cleanup']['status'] == 'deleted', 'Owner cleanup incomplete')
    require(all(s['verdict'] == 'verified_success' or routing_only(s.get('reasons', []))
                for s in card['samples']), 'Protected invariant failure')
    require(Counter(w['id'].split('-')[0] for w in card['workers']) == {'operator': 3, 'observer': 1},
            'Worker population differs')
    require({record['initial_worker'], record['first_worker'], record['second_worker']}
            == {w['id'] for w in card['workers'] if w['id'].startswith('operator-')},
            'Each generation requires its own operator')
    for actual, offset in [(record['stop_requested_at'], spec['stop_offset']),
                           (record['fault']['requested_at'], spec['fault_offset']),
                           (record['first_requested_at'], spec['first_start_offset']),
                           (record['external_restore']['requested_at'], spec['external_restore_offset']),
                           (record['second_fault']['requested_at'], spec['second_fault_offset']),
                           (record['second_requested_at'], spec['second_start_offset'])]:
        require(0 <= actual - (start + offset) <= spec['schedule_lateness_seconds'], 'Controller schedule slipped')
    require(record['stop_requested_at'] <= record['stopped_at'] <= record['fault']['requested_at'],
            'Initial operator did not stop before fault')
    for name, phase in [('fault', 'first'), ('second_fault', 'second')]:
        require(any(s['started_at'] >= record[name]['finished_at']
                    and s['finished_at'] <= record[phase + '_requested_at']
                    and client_path_failed(s['verification']) for s in samples),
                'Customer did not observe the fault before operator start')
    recovered = [s for s in card['samples'] if start + 90 <= s['scheduled_at'] < start + 120]
    require(len(recovered) == 3 and all(s['verdict'] == 'verified_success' for s in recovered),
            'External recovery did not separate the incidents')
    for phase in ('first', 'second'):
        worker = next(w for w in card['workers'] if w['id'] == record[phase + '_worker'])
        require(worker['failure'] is None and worker['ready'] is not None,
                'Operator failed or never became ready')
        require(first_episode_completed_by(worker, record[phase + '_requested_at'] + spec['response_deadline_seconds']),
                'First episode missed its declared response deadline')
    dispatches = assess_audit(card, read(gate / 'server-audit.json'), record)
    expected = {'refresh': (2, 0), 'single_attempt': (1, 1), 'no_repair': (0, 0)}[spec['arm']]
    actual = tuple(sum(a['phase'] == phase for a in record['attempts']) for phase in ('first', 'second'))
    require(actual == expected and len(dispatches) == sum(expected), 'Dispatch sequence differs')
    require(card['dispatch_budget_reserved'] == sum(expected), 'Cumulative budget differs')
    require(len(card['operations']) == sum(expected) + (spec['arm'] == 'refresh'),
            'Unexpected extra operation or missing budget refusal')
    by_id = {op['operation_id']: op for op in dispatches}
    for attempt in record['attempts']:
        op = by_id[attempt['operation_id']]
        require(op['status'] == ('rejected' if attempt['phase'] == 'first' else 'acknowledged'),
                'Wrong phase operation result')
        path = directory / 'workers' / record[attempt['phase'] + '_worker'] / 'preflight' / op['operation_id']
        require(read(path / 'preflight-release.json') == {'operation_id': op['operation_id']}
                and read(path / 'preflight-barrier.json') == attempt['barrier'], 'Barrier or release changed')
    # Program bindings apply to actual dispatches; the separate budget-refused
    # operation must have no binding or API request. It is retained in card.
    verify_bindings(directory, spec, {**card, 'operations': dispatches}, evidence,
                    journal_events(directory), read(gate / 'server-audit.json'))
    later = [s for s in card['samples'] if s['scheduled_at'] >= start + 160]
    require(len(later) == 5, 'Later incident calendar differs')
    return {
        'status': 'passed', 'arm': spec['arm'], 'evidence_use': 'authored_development',
        'sample_counts': card['sample_counts'], 'later_incident_samples': dict(Counter(s['verdict'] for s in later)),
        'actual_api_attempts': len(dispatches), 'first_incident_api_attempts': actual[0],
        'second_incident_api_attempts': actual[1], 'spent_dispatches': card['dispatch_budget_reserved'],
        'budget_refusals': sum(op['reason'] == 'budget_exhausted' for op in card['operations']),
        'hypothesis_result': 'observed' if all(s['verdict'] == ('verified_success' if spec['arm'] == 'single_attempt'
                                                            else 'verified_failure') for s in later) else 'not_observed',
        'limits': ['One authored development sequence per policy, not independent generalization or a reliability estimate.',
                   'External recovery is controller-attributed, never credited to a policy.',
                   'No generated candidate, admission decision, deployment or model-value result.'],
    }
