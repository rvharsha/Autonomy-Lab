"""Development comparison of observation-dependent launch timing, not learning."""

import hashlib
import json
import math
import random

from autonomy_lab.ambiguity import journal_events
from autonomy_lab.budget_horizon import declaration as horizon_declaration
from autonomy_lab.budget_horizon import first_episode_completed_by
from autonomy_lab.campaign import Contract, read
from autonomy_lab.conflict import load_evidence, repair_patch
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.policy_search import require_controller_separation
from autonomy_lab.procedure import verify_bindings
from autonomy_lab.procedures import require
from autonomy_lab.recurrence import epoch, routing_only

ARMS = ('immediate', 'fixed_wait', 'observe_quiet')
CONTEXTS = ('quiet', 'transient', 'persistent', 'resumes')
SHARDS = 3
ANNOTATION = 'autonomy-lab/information-churn'


def declaration(arm, context):
    require(arm in ARMS and context in CONTEXTS, 'Unknown information case')
    base = horizon_declaration('refresh')
    contract = Contract.model_validate({**base['contract'], 'duration_seconds': 90,
        'sample_interval_seconds': 5, 'sample_lateness_seconds': 1,
        'max_operator_starts': 2, 'max_restart_downtime_seconds': 60}).model_dump()
    schedules = {'quiet': [], 'transient': list(range(24, 41)),
                 'persistent': list(range(24, 67)),
                 'resumes': [*range(24, 29), *range(35, 67)]}
    paths = ('scripts/check_information_gate.py', '.github/workflows/information-gate.yml',
             'docs/CONTENTION_INFORMATION_GATE.md')
    return {'arm': arm, 'context': context, 'evidence_use': 'information_development',
            'contract': contract, 'program_pin': base['program_pin'],
            'release_files': base['release_files'],
            'gate_sources': {**base['gate_sources'], **{
                p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}},
            'stop_offset': 8, 'fault_offset': 12, 'decision_offset': 30,
            'decision_duration': 15, 'observation_interval': 1,
            'churn_offsets': schedules[context], 'schedule_lateness_seconds': 1,
            'dispatch_delay_seconds': 2, 'dispatch_release_lateness_seconds': 1,
            'response_deadline_offset': 65}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def launch_decision(arm, observations, elapsed):
    """Only past projected read receipts enter this conventional rule.

    No context, annotations, future schedule, evaluator label or other-arm data.
    The quiescence rule uses four reads spanning at least 2.5 seconds, at most
    1.5 seconds apart. A stale/error/changed-identity read refuses launch.
    """
    require(arm in ARMS and finite(elapsed) and elapsed >= 0, 'Invalid decision input')
    if arm != 'observe_quiet':
        require(observations == [], 'Fixed policies do not collect selector observations')
        return 'launch' if arm == 'immediate' or elapsed >= 15 else 'wait'
    require(type(observations) is list and len(observations) <= 16, 'Observation budget exceeded')
    prior = -1
    for row in observations:
        require(set(row) == {'elapsed', 'uid', 'version'} and finite(row['elapsed'])
                and prior < row['elapsed'] <= elapsed, 'Future or malformed selector evidence')
        prior = row['elapsed']
        if not all(type(row[k]) is str and row[k] for k in ('uid', 'version')):
            return 'decline'
    if observations and (elapsed - observations[-1]['elapsed'] > 1.5
                         or len({r['uid'] for r in observations}) != 1):
        return 'decline'
    recent = observations[-4:]
    if (len(recent) == 4 and len({r['version'] for r in recent}) == 1
            and recent[-1]['elapsed'] - recent[0]['elapsed'] >= 2.5
            and all(0 < b['elapsed'] - a['elapsed'] <= 1.5 for a, b in zip(recent, recent[1:]))):
        return 'launch' if elapsed <= 15 else 'decline'
    return 'decline' if elapsed >= 15 else 'wait'


def churn_patch(uid, annotations, index):
    # Controller changes only metadata, independently of actor readiness.
    return [{'op': 'test', 'path': '/metadata/uid', 'value': uid},
            {'op': 'add', 'path': '/metadata/annotations',
             'value': {**annotations, ANNOTATION: str(index)}}]


def plan():
    cases = {a + '-' + c: declaration(a, c) for a in ARMS for c in CONTEXTS}
    order = list(cases)
    random.Random(2026092504).shuffle(order)
    return {'schema_version': 1, 'evidence_use': 'information_development',
            'arms': list(ARMS), 'contexts': list(CONTEXTS), 'cases': cases,
            'order': order, 'order_seed': 2026092504,
            'shards': [order[i::SHARDS] for i in range(SHARDS)], 'attempts_per_case': 1,
            'selection_rule': 'Complete valid cohort; observe_quiet must be eligible in every context, gain at least two healthy windows summed with equal weight across the four contexts against each fixed comparator, lose at most one window in any context against either, and spend no more total dispatches than either. Otherwise close this hypothesis. No promotion.',
            'objective': {'context_weights': {c: 1 for c in CONTEXTS}, 'minimum_total_gain_windows': 2,
                          'maximum_context_loss_windows': 1, 'production_distribution': None},
            'cost_budget': {'campaigns': 12, 'workload_minutes': 18, 'dispatches_per_campaign': 2,
                            'selector_reads_per_campaign': 16, 'proposer_requests': 0,
                            'shard_timeout_minutes': 30, 'human_active_seconds': None,
                            'billed_compute_cost': None},
            'limits': ['Authored development stress with a common two-second pre-dispatch delay.',
                       'A timing guard is conventional automation, not persistent learning.',
                       'A positive screen needs fresh confirmation; missing evidence blocks the decision.']}


def assess_decision(spec, record, start, uid):
    origin = start + spec['decision_offset']
    history = []
    checks = record['decisions']
    require(bool(checks) and len(checks) <= 16, 'Decision calendar absent or excessive')
    for index, row in enumerate(checks):
        require(finite(row['at']) and 0 <= row['at'] - (origin + index) <= 1.5,
                'Decision check missed its calendar')
        if spec['arm'] == 'observe_quiet':
            observation = row['observation']
            require(origin + index <= observation['requested_at'] <= observation['finished_at'] <= row['at'],
                    'Observation not available before decision')
            require(observation['finished_at'] - observation['requested_at'] <= 1,
                    'Selector observation exceeded its time budget')
            service = observation['service']
            require(service['metadata']['uid'] == uid, 'Selector observed a different workload')
            history.append({'elapsed': observation['finished_at'] - origin,
                            'uid': service['metadata']['uid'], 'version': service['metadata']['resourceVersion']})
        else:
            require('observation' not in row, 'Fixed policy acquired undeclared evidence')
        expected = launch_decision(spec['arm'], history, row['at'] - origin)
        require(row['decision'] == expected and (index == len(checks) - 1 or expected == 'wait'),
                'Decision differs or continued past a terminal choice')
    require(checks[-1]['decision'] in {'launch', 'decline'}, 'Unfinished selector')
    if checks[-1]['decision'] == 'launch':
        require(checks[-1]['at'] <= record['launch_requested_at'] <= checks[-1]['at'] + 1,
                'Launch not attributable to selected decision')
    else:
        require('launch_requested_at' not in record and 'repair_worker' not in record,
                'Declined selector launched an operator')
    return checks[-1]['decision']


def assess_api(card, spec, record, captured):
    require(captured['collection_closed'] is True and captured['malformed_lines'] == 0, 'Incomplete API audit')
    start, end = card['window']['start'], card['window']['end']
    changes = [e for e in captured['events'] if e.get('objectRef', {}).get('namespace') == 'autonomy-lab'
               and e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}
               and start <= epoch(e['requestReceivedTimestamp']) <= end]
    derived = {('system:serviceaccount:kube-system:endpoint-controller', 'endpoints'),
               ('system:serviceaccount:kube-system:endpointslice-controller', 'endpointslices')}
    writes = [e for e in changes if not (e.get('verb') == 'update'
              and (e.get('user', {}).get('username'), e.get('objectRef', {}).get('resource')) in derived)]
    seen = set()

    def match(tag, actor, patch, codes, lower, upper):
        hits = [e for e in writes if e.get('stage') == 'ResponseComplete'
                and e.get('userAgent') == 'autonomy-lab-operation/' + tag
                and e.get('user', {}).get('username') == actor
                and e.get('verb') == 'patch'
                and e.get('objectRef', {}).get('resource') == 'services'
                and e.get('objectRef', {}).get('name') == 'inventory'
                and e.get('requestObject') == patch and type(e.get('responseStatus', {}).get('code')) is int
                and e['responseStatus']['code'] in codes]
        require(len(hits) == 1 and hits[0]['auditID'] not in seen, 'Missing or duplicate API attribution')
        event = hits[0]
        require(lower <= epoch(event['requestReceivedTimestamp']) <= epoch(event['stageTimestamp']) <= upper,
                'API evidence outside its recorded interval')
        seen.add(event['auditID'])
        return event

    uid = card['identities_before']['Service/inventory']
    fault = record['fault']
    require(fault['patch'] == repair_patch({'service_uid': uid, 'resource_version': fault['patch'][1]['value'],
                 'expected_target_port': 8080, 'target_port': 9999}), 'Undeclared routing fault')
    match('ambiguity-fault', 'kubernetes-admin', fault['patch'], range(200, 300),
          fault['requested_at'], fault['finished_at'])
    require(len(record['churn']) == len(spec['churn_offsets']) and record['churn_finished'] is True,
            'Churn calendar incomplete')
    for index, (offset, row) in enumerate(zip(spec['churn_offsets'], record['churn'], strict=True)):
        require(row['index'] == index and 0 <= row['requested_at'] - (start + offset) <= 1
                and row['requested_at'] <= row['finished_at'] <= start + offset + 1.5,
                'Independent controller missed its calendar')
        patch = churn_patch(uid, record['initial_annotations'], index)
        require(row['patch'] == patch, 'Controller changed more than declared metadata')
        event = match('information-churn-' + str(index), 'kubernetes-admin', patch, range(200, 300),
                      row['requested_at'], row['finished_at'])
        require(event['responseObject'] == row['response'], 'Controller response differs from API evidence')
    require(len(card['operations']) == card['dispatch_budget_reserved'] <= 2, 'Dispatch budget differs')
    require(len(record['barriers']) == len(card['operations']), 'Missing or extra dispatch barrier')
    for op in card['operations']:
        request = json.loads(op['request'])
        require(request['service_uid'] == uid and request['namespace'] == 'autonomy-lab'
                and request['service_name'] == 'inventory' and request['port_name'] == 'http'
                and request['expected_target_port'] == 9999 and request['target_port'] == 8080
                and op['status'] in {'acknowledged', 'rejected'} and op['budget_reserved'] == 1,
                'Undeclared or unresolved operator operation')
        rows = [b for b in record['barriers'] if b['operation_id'] == op['operation_id']]
        require(len(rows) == 1, 'Missing or duplicate prepared-write barrier')
        barrier = rows[0]
        require(epoch(op['created_at']) <= barrier['at'] and 2 <= barrier['release_at'] - barrier['at'] <= 3,
                'Common dispatch delay changed')
        event = match(op['operation_id'], 'system:serviceaccount:autonomy-lab:broker', repair_patch(request),
                      range(200, 300) if op['status'] == 'acknowledged' else {409, 422},
                      barrier['release_at'], epoch(op['updated_at']))
        if op['status'] == 'rejected':
            require(op['reason'] == 'api_rejected_' + str(event['responseStatus']['code']),
                    'Journal rejection differs from actual API response')
    require(len(writes) == len(seen) and {e['auditID'] for e in writes} == seen,
            'Unattributed namespace mutation')


def evaluate(gate):
    spec, record = read(gate / 'declaration.json'), read(gate / 'record.json')
    require(spec == declaration(spec['arm'], spec['context']), 'Declaration or release changed')
    card, samples, evidence = load_evidence(gate, spec)
    start = card['window']['start']
    require(len(card['samples']) == 18 and card['sample_counts']['unknown'] == 0,
            'Incomplete customer calendar')
    require(card['identities_unchanged'] and len(card['identities_before']) >= 11, 'Workload identity changed')
    require(card['owner_finished'] and card['owner_failure'] is None
            and card['cleanup']['status'] == 'deleted', 'Owner or cleanup failed')
    require(all(s['verdict'] == 'verified_success' or routing_only(s.get('reasons', []))
                for s in card['samples']), 'Protected invariant failure')
    for actual, offset in [(record['stop_requested_at'], 8), (record['fault']['requested_at'], 12)]:
        require(0 <= actual - (start + offset) <= 1, 'Initial intervention calendar slipped')
    require(record['stop_requested_at'] <= record['stopped_at'] <= record['fault']['requested_at'],
            'Initial operator alive during fault')
    require_controller_separation(card['samples'], record)
    require(any(s['started_at'] >= record['fault']['finished_at'] and s['finished_at'] <= start + 30
                and client_path_failed(s['verification']) for s in samples),
            'Customer failure was not independently observed before decisions')
    decision = assess_decision(spec, record, start, card['identities_before']['Service/inventory'])
    operators = {w['id']: w for w in card['workers'] if w['id'].startswith('operator-')}
    expected = {record['initial_worker']} | ({record['repair_worker']} if decision == 'launch' else set())
    require(set(operators) == expected and len(card['workers']) == len(expected) + 1
            and sum(w['id'].startswith('observer-') for w in card['workers']) == 1,
            'Unexpected or missing workers')
    require(all(w['failure'] is None and w['ready'] is not None for w in card['workers']), 'Worker failed')
    initial = operators[record['initial_worker']]
    require(any(e['outcome'] is not None for e in initial['episodes']) and all(
        e['outcome'] is None or e['outcome']['claim']['outcome'] == 'healthy' for e in initial['episodes']),
        'Initial health not established')
    if decision == 'launch':
        repair = operators[record['repair_worker']]
        require(record['launch_requested_at'] <= repair['ready']['at'] <= record['launch_requested_at'] + 10,
                'Selected launch missed readiness bound')
        require(all(epoch(op['created_at']) >= repair['ready']['at'] for op in card['operations']),
                'Mutation predates chosen response')
        eligible = first_episode_completed_by(repair, start + spec['response_deadline_offset'])
        for b in record['barriers']:
            path = gate / 'campaign/workers' / repair['id'] / 'preflight' / b['operation_id']
            require(read(path / 'preflight-barrier.json') == {k: b[k] for k in ('at', 'operation_id')}
                    and read(path / 'preflight-release.json') == {'operation_id': b['operation_id']},
                    'Actual barrier or release differs')
    else:
        require(card['operations'] == [], 'Declined response caused an operation')
        eligible = True
    audit = read(gate / 'server-audit.json')
    assess_api(card, spec, record, audit)
    verify_bindings(gate / 'campaign', spec, card, evidence, journal_events(gate / 'campaign'), audit)
    return {'measurement_valid': True, 'authority_conformant': True, 'eligible': eligible,
            'arm': spec['arm'], 'context': spec['context'], 'decision': decision,
            'sample_counts': card['sample_counts'], 'spent_dispatches': card['dispatch_budget_reserved'],
            'conditional_rejections': sum(op['status'] == 'rejected' for op in card['operations']),
            'selector_reads': len(record['decisions']) if spec['arm'] == 'observe_quiet' else 0,
            'selector_elapsed_seconds': record['decisions'][-1]['at'] - (start + 30),
            'unchanged_resources': len(card['identities_before']), 'evidence_use': spec['evidence_use']}


def select(declared, evaluations):
    require(declared == plan() and set(evaluations) == set(declared['cases']), 'Incomplete frozen comparison')
    for name, row in evaluations.items():
        spec = declared['cases'][name]
        require(row['arm'] == spec['arm'] and row['context'] == spec['context']
                and row['evidence_use'] == 'information_development'
                and row['measurement_valid'] is True and row['authority_conformant'] is True,
                'Invalid comparison evidence')
        counts = row['sample_counts']
        require(set(counts) == {'verified_success', 'verified_failure', 'unknown'}
                and all(type(n) is int and n >= 0 for n in counts.values())
                and sum(counts.values()) == 18 and counts['unknown'] == 0
                and type(row['spent_dispatches']) is int and 0 <= row['spent_dispatches'] <= 2
                and type(row['eligible']) is bool, 'Invalid customer or authority counts')
    qualifies = True
    for baseline in ('immediate', 'fixed_wait'):
        pairs = [(evaluations['observe_quiet-' + c], evaluations[baseline + '-' + c]) for c in CONTEXTS]
        require(all(b['eligible'] for _, b in pairs), 'Comparator did not qualify')
        differences = [a['sample_counts']['verified_success'] - b['sample_counts']['verified_success'] for a, b in pairs]
        qualifies &= all(a['eligible'] for a, _ in pairs) and min(differences) >= -1 and sum(differences) >= 2
        qualifies &= sum(a['spent_dispatches'] for a, _ in pairs) <= sum(b['spent_dispatches'] for _, b in pairs)
    return {'status': 'complete', 'decision': 'candidate_for_fresh_confirmation' if qualifies else 'close_information_hypothesis',
            'promotion': False, 'confirmation_run': False, 'evidence_use': 'information_development',
            'evaluations': evaluations, 'limits': declared['limits']}
