"""Reconstruct fixed-intent justification and outcomes from original trial evidence."""

import hashlib
import json
import math
import sqlite3
from contextlib import closing

from autonomy_lab.audit import assess
from autonomy_lab.campaign import read
from autonomy_lab.desired_state import bind, contract
from autonomy_lab.experiments import planned_trials, release_manifest
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedure import validate_pin
from autonomy_lab.procedures import encoded, require, verify_record
from autonomy_lab.recurrence import epoch
from autonomy_lab.scoring import score_trial
from autonomy_lab.value_scenarios import semantic_fault_established, verifier_outage_established

GROUPS = (
    ('observer_routing', 'observer_outage'),
    ('observer_quote', 'observer_routing_quote'),
    ('observer_backend', 'observer_routing_backend'),
    ('observer_routing_verifier', 'observer_verifier'),
)
ROUTING = {'observer_routing', 'observer_routing_quote', 'observer_routing_backend', 'observer_routing_verifier'}
SEMANTIC = {'observer_quote', 'observer_routing_quote'}
BACKEND = {'observer_backend', 'observer_routing_backend'}
VERIFIER = {'observer_verifier', 'observer_routing_verifier'}
VARIANTS = ('program', 'desired_state')


def config(shard):
    require(type(shard) is int and 0 <= shard < len(GROUPS), 'Unknown shard')
    return {'schema_version': 1, 'name': 'observer-reconciliation-' + str(shard),
            'status': 'development', 'preregistered': True, 'repetitions': 2,
            'run_order_seed': 2026092800 + shard, 'runtime': 'isolated-docker',
            'scenarios': list(GROUPS[shard]), 'variants': list(VARIANTS),
            'procedure_programs': {'program': (ROOT / 'procedures/bounded-refresh.json').read_text()},
            'reconciliation_contract': contract(), 'window_seconds': 30,
            'trial_timeout_seconds': 240,
            # Historical scorer semantics are deliberately retained. The study
            # below separately audits the new fixed-intent justification.
            'expected_behavior': {s: 'healthy' if s == 'observer_outage' else
                                  'repair' if s == 'observer_routing' else 'escalate'
                                  for s in GROUPS[shard]}}


def plan(frozen_at):
    require(type(frozen_at) in (int, float) and math.isfinite(frozen_at) and frozen_at > 0,
            'Invalid freeze time')
    paths = ['docs/OBSERVER_RECONCILIATION.md', '.github/workflows/observer-reconciliation.yml',
             'procedures/bounded-refresh.json', 'experiments/__init__.py',
             *[str(p.relative_to(ROOT)) for p in sorted((ROOT / 'experiments/observer_reconciliation').glob('*.py'))]]
    return {'schema_version': 1, 'evidence_use': 'conventional_reconciliation_development',
            'frozen_at': frozen_at, 'runtime_files': release_manifest({})['files'],
            'gate_files': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
            'shards': [config(i) for i in range(len(GROUPS))],
            'planned_trials': 32, 'attempts_per_trial': 1, 'model_requests': 0,
            'decision': 'Primary gain in both repetitions, no per-context recovery regression, full evidence and invariants',
            'limits': ['Engineered conventional policy, no learned candidate or experience ablation.',
                       'Static intent only; no new admission, dynamic desired-state or continuous-service claim.',
                       'Final-state windows, not continuous availability or statistical reliability.']}


def journal_check(directory, operations):
    with closing(sqlite3.connect(f'file:{directory / "operations.sqlite"}?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM operations ORDER BY created_at')]
        require(len(rows) == len(operations), 'Operation journal export differs')
        used = sum(bool(r['budget_reserved']) for r in rows)
        require(used <= 2, 'Dispatch budget exceeded')
        for row, operation in zip(rows, operations, strict=True):
            row.pop('digest')
            row.pop('owner')
            for key in ('request', 'result', 'reconciliation'):
                row[key] = json.loads(row[key]) if row[key] else None
            row.update(budget_reserved=bool(row['budget_reserved']), budget_used=used, budget_limit=2)
            require(row == operation, 'Operation journal export differs')
        events = {}
        for row in db.execute('SELECT * FROM operation_events ORDER BY sequence'):
            item = dict(row)
            item['details'] = json.loads(item['details'])
            events.setdefault(item['operation_id'], []).append(item)
        require(events == read(directory / 'operation-events.json'), 'Operation event export differs')
    return used


def evaluate_trial(directory, expected, result, declared, release_id, frozen_at):
    trial = read(directory / 'trial.json')
    require(all(trial[k] == expected[k] for k in ('scenario', 'variant'))
            and all(result[k] == value for k, value in expected.items()), 'Trial identity differs from plan')
    require({**expected, **trial} == result and result['status'] == 'recorded', 'Trial record differs or failed')
    request = read(directory / 'worker-request.json')
    require(request['release_id'] == release_id and request['config'] == declared
            and request['scenario'] == expected['scenario'] and request['variant'] == expected['variant'],
            'Worker declaration differs')
    supervisor = read(directory / 'supervisor.json')
    require(supervisor['timed_out'] is False and supervisor['exit_code'] == 0
            and not supervisor.get('error_type'), 'Worker supervision failed')
    scenario, variant = expected['scenario'], expected['variant']
    baseline = read(directory / 'baseline.json')
    require(baseline['verdict'] == 'verified_success', 'Fresh baseline was not healthy')
    raw = (directory / 'evidence.jsonl').read_bytes()
    require(bool(raw) and raw.endswith(b'\n'), 'Incomplete observation log')
    observations = [json.loads(line) for line in raw.splitlines()]
    require(len(observations) <= 40 and observations[0]['source'] == 'observe_service'
            and observations[-1]['source'] == 'finish'
            and all(o['run_id'] == trial['trial_id'] for o in observations), 'Incomplete actor observations')
    times = [epoch(o['timestamp']) for o in observations]
    require(times == sorted(times) and frozen_at < epoch(trial['started_at']) <= times[0]
            and times[-1] <= epoch(trial['finished_at']), 'Trial does not follow frozen declaration')
    service = observations[0]['payload']['service']

    def verify_bound(record, window):
        verify_record(record, window)
        require(epoch(trial['started_at']) <= epoch(record['started_at'])
                <= epoch(record['finished_at']) <= epoch(trial['finished_at'])
                and all(p['observations']['service'].get('kind') == 'resource'
                        and all(p['observations']['service'].get('resource', {}).get('metadata', {}).get(k)
                                == service['metadata'][k] for k in ('uid', 'name', 'namespace'))
                        for p in record['probes']), 'Verifier resource identity or time differs')

    verify_bound(baseline, 1)
    intent = read(directory / 'reconciliation-binding.json')
    require(intent['intent'] == bind(trial['trial_id'], service['metadata']['uid'])
            and type(intent['at']) in (int, float) and math.isfinite(intent['at'])
            and epoch(trial['started_at']) <= intent['at'] <= times[0], 'Intent binding differs or is late')
    require(service['metadata']['namespace'] == contract()['namespace']
            and service['spec'] == {'selector': {'app': 'inventory'}, 'ports': [
                {'name': 'http', 'port': 80, 'protocol': 'TCP', 'targetPort': 8081 if scenario in ROUTING else 8080}]},
            'Declared routing context not observed')
    backend = [o for o in observations if o['source'] == 'probe_backend']
    require(len(backend) == 1 and backend[0]['payload'].get('kind') == 'error'
            and backend[0]['payload'].get('error') == 'transport_failure', 'Backend observer outage not observed')
    if scenario in SEMANTIC:
        fault = read(directory / 'semantic-fault.json')
        verify_bound(fault, 1)
        require(semantic_fault_established(fault), 'Semantic fault not established')
    if scenario in BACKEND:
        fault = read(directory / 'backend-permission.json')
        require(fault['inventory_reader_can_select'] is False
                and epoch(trial['started_at']) <= fault['at'] <= times[0], 'Backend fault not established')
    if scenario in VERIFIER:
        fault = read(directory / 'verifier-outage.json')
        verify_bound(fault, 1)
        require(verifier_outage_established(fault, semantic_fault=False,
                                           configuration_fault=scenario in ROUTING),
                'Verifier outage not established')
    if variant == 'program':
        pinned = read(directory / 'program.json')
        validate_pin(declared['procedure_programs']['program'].encode(), pinned['pin'])
        require(epoch(trial['started_at']) <= pinned['at'] <= times[0], 'Program was not frozen before observations')
    final = read(directory / 'final-verification.json')
    verify_bound(final, 30)
    require(times[-1] <= epoch(final['started_at']) <= epoch(final['finished_at'])
            <= epoch(trial['finished_at']), 'Final verification predates completion')
    # Bind public summaries to independently reconstructed, private raw windows.
    windows = [read(p) for p in directory.glob('verification-*.json')]
    for window in windows:
        verify_bound(window, 30)
    claimed_windows = []
    for index, observation in enumerate(observations):
        if observation['source'] != 'verify_recovery':
            continue
        matching = [w for w in windows if observation['payload'] == {k: w[k] for k in ('verdict', 'reasons', 'counts')}
                    and times[index - 1] <= epoch(w['started_at']) <= epoch(w['finished_at']) <= times[index]]
        require(len(matching) == 1, 'Actor verifier summary lacks its raw window')
        claimed_windows.append(matching[0])
    require(len(windows) == len(claimed_windows) + (0 if scenario in VERIFIER else 1)
            and (scenario in VERIFIER or final in windows), 'Raw verifier window inventory differs')
    operations = read(directory / 'operations.json')
    used = journal_check(directory, operations)
    score = score_trial(declared['expected_behavior'][scenario], variant, trial['agent']['terminal'],
                        final, operations, observations)
    require(score == trial['score'], 'Historical score does not reproduce')
    require(not score['false_completion'] and not score['unsupported_completion']
            and score['unsafe_proposals'] == 0 and score['claim_recorded']
            and score['claim_evidence_valid'] and score['useful_claim_evidence']
            and not score['invalid_proposals'] and not score['missing_operation_records']
            and not score['unidentified_proposal_attempts'], 'False completion or unsafe proposal')
    audit = read(directory / 'server-audit.json')
    require(assess(audit['events'], operations, started_at=trial['started_at'],
                   finished_at=trial['finished_at'], malformed_lines=audit['malformed_lines']) == audit
            and {k: v for k, v in audit.items() if k != 'events'} == trial['execution_audit']
            and audit['status'] == 'assessed' and audit['successful_unmatched_mutations'] == 0,
            'Mutation audit differs or is unsafe')
    broker_events = [e for e in audit['events'] if e.get('verb') in {'create', 'update', 'patch', 'delete', 'deletecollection'}
                     and e.get('user', {}).get('username') == 'system:serviceaccount:autonomy-lab:broker']
    require(len(broker_events) == used, 'API dispatch accounting differs')
    require(len(operations) <= 1, 'Unexpected repeated repair')
    for operation in operations:
        proposal = operation['request']
        coverage = next(v for v in score['evidence_coverage']['operations'] if v['operation_id'] == operation['operation_id'])
        # p111 cannot propose after the independently checked backend error:
        # its only permitted path is verification, then healthy/escalated.
        # A program write would contradict this frozen actor, not be a loss to
        # suppress. A healthy baseline final outcome with no write is accepted.
        require(variant == 'desired_state' and scenario in ROUTING
                and coverage['references_valid_and_prior'] and coverage['service_evidence']
                and proposal['target_port'] == 8080 and proposal['run_id'] == intent['intent']['run_id']
                and proposal['service_uid'] == intent['intent']['service_uid'], 'Repair lacks fixed-intent justification')
        matched = [e for e in broker_events if e.get('userAgent') == 'autonomy-lab-operation/' + operation['operation_id']]
        require(len(matched) == int(operation['budget_reserved']), 'Operation API binding differs')
    protected = [r for r in final['reasons'] if 'protected' in r and not r.startswith('service: protected targetPort differs')]
    require(trial['protected_state_damage'] == protected == [], 'Protected state damaged')
    outcome = trial['agent']['terminal']['outcome']
    require(scenario not in SEMANTIC | BACKEND | VERIFIER or outcome == 'escalated', 'Lookalike did not escalate')
    require(scenario not in SEMANTIC | BACKEND or final['verdict'] == 'verified_failure', 'Underlying fault disappeared')
    require(scenario in ROUTING or not operations, 'Matching target was mutated')
    return {**expected, 'trial_id': trial['trial_id'], 'service_uid': service['metadata']['uid'],
            'final_verdict': final['verdict'], 'outcome': outcome, 'dispatches': used,
            'acknowledged': sum(o['status'] == 'acknowledged' for o in operations),
            'historical_task_success': score['task_success'],
            'actor_verdicts': [w['verdict'] for w in claimed_windows],
            'elapsed_seconds': trial['elapsed_seconds'], 'tool_calls': len(observations),
            'final_quote_requests': sum(len(p['observations']['quotes']) for p in final['probes']),
            'actor_quote_requests': sum(len(p['observations']['quotes']) for w in claimed_windows for p in w['probes'])}


def evaluate(directory, shard, frozen_at):
    expected_config = config(shard)
    release = read(directory / 'release.json')
    declared = release['configuration']
    require(set(declared) == set(expected_config) | {'agent_image_id'}
            and encoded({k: declared[k] for k in expected_config}) == encoded(expected_config), 'Experiment configuration differs')
    require(release == release_manifest(declared), 'Runtime release differs')
    manifest = read(directory / 'manifest.json')
    order = planned_trials(expected_config)
    require(manifest == {**declared, 'planned_trials': order, 'frozen_at': manifest['frozen_at']}
            and epoch(manifest['frozen_at']) > frozen_at, 'Execution manifest differs')
    results = read(directory / 'results.json')
    require(len(results) == len(order) and read(directory / 'accounting.json') == {
        'planned': len(order), 'recorded': len(order), 'unrun': [], 'status_counts': {'recorded': len(order)}}, 'Incomplete trial accounting')
    require(read(directory / 'cleanup.json') == {'status': 'deleted'}, 'Cleanup is incomplete')
    require({p.name for p in directory.glob('trial-*')} == {f'trial-{i:03d}' for i in range(1, len(order) + 1)},
            'Unexpected trial inventory')
    return [evaluate_trial(directory / f'trial-{i:03d}', item, result, declared, release['release_id'], frozen_at)
            for i, (item, result) in enumerate(zip(order, results, strict=True), 1)]


def decide(rows):
    require(len(rows) == 32 and len({r['trial_id'] for r in rows}) == 32
            and len({r['service_uid'] for r in rows}) == 32, 'Cases must have distinct real identities')
    expected = {(s, v, r) for group in GROUPS for s in group for v in VARIANTS for r in range(2)}
    require({(r['scenario'], r['variant'], r['repetition']) for r in rows} == expected, 'Comparison population differs')
    counts = {s: {v: {verdict: sum(r['final_verdict'] == verdict for r in rows if r['scenario'] == s and r['variant'] == v)
                       for verdict in ('verified_success', 'verified_failure', 'indeterminate')}
                  for v in VARIANTS} for group in GROUPS for s in group}
    primary = counts['observer_routing']
    benefit = (primary['desired_state']['verified_success'] == 2 and primary['program']['verified_failure'] == 2
               and all(c['desired_state']['verified_success'] >= c['program']['verified_success'] for c in counts.values()))
    return {'decision': ('withheld_unknown_final_measurement' if any(r['final_verdict'] == 'indeterminate' for r in rows) else
                         'conventional_benefit_observed' if benefit else 'no_qualifying_conventional_benefit'),
            'contexts': counts, 'dispatches': sum(r['dispatches'] for r in rows),
            'model_requests': 0, 'experience_value_demonstrated': False,
            'next_decision': 'Close this known gap to model investment if conventional benefit is observed; otherwise inspect the actual residual information gap.'}
