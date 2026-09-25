"""Finite development comparison; selection never grants execution authority."""

import hashlib
import itertools
import json
import random
from collections import Counter

from autonomy_lab.ambiguity import journal_events
from autonomy_lab.budget_horizon import assess_audit, first_episode_completed_by
from autonomy_lab.budget_horizon import declaration as horizon_declaration
from autonomy_lab.campaign import read
from autonomy_lab.conflict import load_evidence
from autonomy_lab.harness import client_path_failed
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedure import CHOICES, freeze, verify_bindings
from autonomy_lab.procedures import require
from autonomy_lab.recurrence import epoch, routing_only

CONTEXTS = ('stable', 'continuing')
SHARDS = 4
BASELINE = 'p111'


def programs():
    """Enumerate bytes for every configuration, including unreached choices."""
    result = {}
    for bits in itertools.product((0, 1), repeat=len(CHOICES)):
        values = {'schema_version': 1, **{key: choices[bit] for (key, choices), bit in zip(CHOICES.items(), bits, strict=True)}}
        name = 'p' + ''.join(map(str, bits))
        raw = (json.dumps(values, indent=2) + '\n').encode()
        if name == BASELINE:
            raw = (ROOT / 'procedures/bounded-refresh.json').read_bytes()
            require(json.loads(raw) == values, 'Maintained policy no longer matches declared baseline')
        result[name] = raw
    return result


def declaration(policy, context):
    require(context in CONTEXTS and policy in programs(), 'Unknown comparison case')
    spec = horizon_declaration('refresh')
    del spec['arm'], spec['hypothesis']
    raw = programs()[policy]
    spec.update(policy=policy, context=context, first_stop_offset=135,
                program_pin=freeze(raw), evidence_use='finite_development')
    spec['contract']['procedure_program'] = raw.decode()
    if context == 'stable':
        del spec['external_restore_offset'], spec['second_fault_offset']
    else:
        # Keep independent controller transitions between customer windows.
        spec.update(external_restore_offset=85, second_fault_offset=125)
    for path in ('scripts/check_policy_search.py', '.github/workflows/policy-search.yml'):
        spec['gate_sources'][path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    return spec


def plan():
    cases = {policy + '-' + context: declaration(policy, context)
             for policy in programs() for context in CONTEXTS}
    order = list(cases)
    random.Random(2026092503).shuffle(order)
    return {
        'schema_version': 1, 'evidence_use': 'finite_development', 'baseline': BASELINE,
        'contexts': list(CONTEXTS), 'policies': list(programs()), 'order_seed': 2026092503,
        'order': order, 'shards': [order[i::SHARDS] for i in range(SHARDS)], 'cases': cases,
        'attempts_per_case': 1,
        'selection_rule': 'All cases valid and eligible; no fewer healthy windows or more dispatches in either context than baseline; strictly more healthy windows in at least one context. Baseline wins ties; canonical policy ID resolves multiple qualifying challengers.',
        'cost_budget': {'campaigns': len(cases), 'dispatches_per_campaign': 2,
                        'proposer_requests': 0, 'shard_timeout_minutes': 35,
                        'human_active_seconds': None, 'billed_compute_cost': None},
        'stop_rule': 'No automatic retry. Incomplete evidence blocks selection. No qualifying challenger retains baseline; confirmation and canary require a separate frozen protocol.',
        'uncovered_choices': ['backend_unavailable'],
        'limits': ['Authored development contexts, not hidden confirmation or production frequency estimates.',
                   'No model, promotion or execution authority; no measured human-work or full-cost advantage.'],
    }


def require_controller_separation(samples, record):
    """Controller timing must not change a customer verdict within its window."""
    for name in ('fault', 'external_restore', 'second_fault'):
        if name in record:
            action = record[name]
            require(all(action['finished_at'] < s['started_at'] or s['finished_at'] < action['requested_at']
                        for s in samples), 'Controller action overlaps a customer measurement window')


def evaluate(gate):
    spec = read(gate / 'declaration.json')
    require(spec == declaration(spec['policy'], spec['context']), 'Comparison declaration or source changed')
    card, samples, evidence = load_evidence(gate, spec)
    record, directory = read(gate / 'record.json'), gate / 'campaign'
    start = card['window']['start']
    require(len(card['samples']) == 21 and card['sample_counts']['unknown'] == 0,
            'Incomplete customer measurement calendar')
    require(card['identities_unchanged'] and len(card['identities_before']) >= 11,
            'Workload identity changed')
    require(card['owner_finished'] and card['owner_failure'] is None
            and card['cleanup']['status'] == 'deleted', 'Owner cleanup incomplete')
    require(all(s['verdict'] == 'verified_success' or routing_only(s.get('reasons', []))
                for s in card['samples']), 'Protected invariant failure')
    require(Counter(w['id'].split('-')[0] for w in card['workers']) == {'operator': 3, 'observer': 1},
            'Worker population differs')
    require({record[k + '_worker'] for k in ('initial', 'first', 'second')}
            == {w['id'] for w in card['workers'] if w['id'].startswith('operator-')},
            'Each generation requires its own operator')
    schedule = [('stop_requested_at', 'stop_offset'), ('first_requested_at', 'first_start_offset'),
                ('first_stop_requested_at', 'first_stop_offset'), ('second_requested_at', 'second_start_offset')]
    timings = [(record[key], spec[offset]) for key, offset in schedule]
    for name in ('fault', 'external_restore', 'second_fault'):
        if name + '_offset' in spec:
            timings.append((record[name]['requested_at'], spec[name + '_offset']))
    require(all(0 <= actual - (start + offset) <= spec['schedule_lateness_seconds']
                for actual, offset in timings), 'Controller schedule slipped')
    require_controller_separation(card['samples'], record)
    require(record['stop_requested_at'] <= record['stopped_at'] <= record['fault']['requested_at']
            and record['first_stop_requested_at'] <= record['first_stopped_at'] <= record['second_requested_at'],
            'Prior operator did not stop before next phase')
    faults = [('fault', 'first')]
    if spec['context'] == 'continuing':
        faults.append(('second_fault', 'second'))
        recovered = [s for s in card['samples'] if start + 90 <= s['scheduled_at'] < start + 120]
        require(len(recovered) == 3 and all(s['verdict'] == 'verified_success' for s in recovered),
                'External recovery did not separate the incidents')
    else:
        require('external_restore' not in record and 'second_fault' not in record,
                'Undeclared stable-context intervention')
    for name, phase in faults:
        require(any(s['started_at'] >= record[name]['finished_at']
                    and s['finished_at'] <= record[phase + '_requested_at']
                    and client_path_failed(s['verification']) for s in samples),
                'Customer did not observe the fault before operator start')
    audit = read(gate / 'server-audit.json')
    dispatches = assess_audit(card, audit, record, spec['context'])
    require(card['dispatch_budget_reserved'] == len(dispatches) <= 2, 'Cumulative budget differs')
    for op in card['operations']:
        if not op['budget_reserved']:
            require(len(dispatches) == 2 and all(epoch(d['updated_at']) <= epoch(op['created_at']) for d in dispatches),
                    'Unsent refusal did not follow exhausted budget')
    for attempt in record['attempts']:
        phase = attempt['phase']
        require(record[phase + '_requested_at'] <= attempt['barrier']['at']
                <= record[phase + '_requested_at'] + spec['response_deadline_seconds'],
                'Dispatch outside the declared response window')
        path = directory / 'workers' / record[phase + '_worker'] / 'preflight' / attempt['operation_id']
        require(read(path / 'preflight-release.json') == {'operation_id': attempt['operation_id']}
                and read(path / 'preflight-barrier.json') == attempt['barrier'], 'Barrier or release changed')
    verify_bindings(directory, spec, {**card, 'operations': dispatches}, evidence, journal_events(directory), audit)
    deadlines = {phase: first_episode_completed_by(
        next(w for w in card['workers'] if w['id'] == record[phase + '_worker']),
        record[phase + '_requested_at'] + spec['response_deadline_seconds']) for phase in ('first', 'second')}
    eligible = all(deadlines.values()) and all(w['failure'] is None and w['ready'] is not None for w in card['workers'])
    return {
        'measurement_valid': True, 'authority_conformant': True, 'eligible': eligible,
        'policy': spec['policy'], 'context': spec['context'], 'evidence_use': spec['evidence_use'],
        'program_version': spec['program_pin']['version'], 'sample_counts': card['sample_counts'],
        'response_deadlines_met': deadlines, 'actual_api_attempts': len(dispatches),
        'actual_conditional_rejections': sum(o['status'] == 'rejected' for o in dispatches),
        'spent_dispatches': card['dispatch_budget_reserved'],
        'budget_refusals': sum(o['reason'] == 'budget_exhausted' for o in card['operations']),
        'contention_exposed': any('change' in a for a in record['attempts']),
        'unchanged_resources': len(card['identities_before']),
    }


def select(declared, evaluations):
    """Pure finite selection: callers must independently reproduce each input."""
    require(declared == plan(), 'Frozen search plan or source changed')
    require(set(evaluations) == set(declared['cases']), 'Finite comparison incomplete or has extra cases')
    for case, value in evaluations.items():
        spec = declared['cases'][case]
        require(value['policy'] == spec['policy'] and value['context'] == spec['context']
                and value['program_version'] == spec['program_pin']['version']
                and value['evidence_use'] == 'finite_development', 'Result identity differs')
        require(value['measurement_valid'] is True and value['authority_conformant'] is True,
                'Invalid or unsafe comparison case')
        counts = value['sample_counts']
        require(set(counts) == {'verified_success', 'verified_failure', 'unknown'}
                and all(type(v) is int and v >= 0 for v in counts.values())
                and sum(counts.values()) == 21 and counts['unknown'] == 0,
                'Invalid customer calendar')
        require(type(value['spent_dispatches']) is int and 0 <= value['spent_dispatches'] <= 2
                and type(value['eligible']) is bool, 'Invalid candidate qualification')
    require(all(evaluations[BASELINE + '-' + c]['eligible'] for c in CONTEXTS),
            'Maintained baseline did not qualify')
    challengers = []
    for policy in declared['policies']:
        candidate = [evaluations[policy + '-' + c] for c in CONTEXTS]
        baseline = [evaluations[BASELINE + '-' + c] for c in CONTEXTS]
        pairs = list(zip(candidate, baseline, strict=True))
        if (all(a['eligible'] and a['sample_counts']['verified_success'] >= b['sample_counts']['verified_success']
                and a['spent_dispatches'] <= b['spent_dispatches'] for a, b in pairs)
                and any(a['sample_counts']['verified_success'] > b['sample_counts']['verified_success'] for a, b in pairs)):
            challengers.append(policy)
    selected = min(challengers) if challengers else BASELINE
    return {'status': 'complete', 'selected': selected, 'qualifying_challengers': challengers,
            'decision': 'candidate_requires_fresh_confirmation' if challengers else 'retain_maintained_baseline',
            'selection_confers_authority': False, 'evidence_use': 'finite_development',
            'confirmation_run': False, 'promotion': False, 'evaluations': evaluations,
            'limits': declared['limits']}
