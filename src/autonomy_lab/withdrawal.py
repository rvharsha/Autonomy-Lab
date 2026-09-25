"""Offline checks for admission governing real persistent operator episodes."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from autonomy_lab import ambiguity
from autonomy_lab.audit import assess, read_events
from autonomy_lab.campaign import Contract, read
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import evaluate as evaluate_calibration
from autonomy_lab.procedures import verify_record
from autonomy_lab.recurrence import epoch

CASES = ('healthy', 'uncertain')


def declaration(case, calibration_name):
    if case not in CASES:
        raise ValueError('Unknown withdrawal case')
    spec = ambiguity.declaration('unchanged') if case == 'uncertain' else {
        'case': 'healthy', 'barrier_deadline_offset': 15, 'withdraw_offset': 20,
        'refusal_deadline_seconds': 15, 'schedule_lateness_seconds': 3,
    }
    paths = ['scripts/check_withdrawal.py', 'scripts/check_ambiguity.py', 'scripts/check_campaign.py',
             'scripts/check_recurrence.py', 'src/autonomy_lab/withdrawal.py',
             f'scenarios/campaign-withdrawal-{case}.json']
    return {**spec, 'withdrawal_case': case, 'calibration_name': calibration_name,
            'contract_sha256': hashlib.sha256((ROOT / paths[-1]).read_bytes()).hexdigest(),
            'gate_source': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}}


def ledger(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        return {name: [dict(row) for row in db.execute(f'SELECT * FROM {name} ORDER BY 1')]
                for name in ('state', 'versions', 'decisions', 'pins', 'refusals')}


def capture_audit(gate):
    """Freeze raw API evidence once; offline export never contacts Kubernetes."""
    path = gate / 'server-audit.json'
    if not path.exists():
        from autonomy_lab.harness import save
        directory = gate / 'campaign'
        save(path, {**read_events(directory / 'server-audit'),
                    'collection_closed': read(directory / 'environment.json')['status'] == 'deleted'})


def binding_checks(card, record, admission, receipt, episodes, bindings):
    """Pure checks, also exercised by explicitly authored adversarial unit cases."""
    promoted = {'revision': 1, 'kind': 'promoted', 'version': receipt['version']}
    withdrawn = {'revision': 2, 'kind': 'withdrawn', 'version': receipt['version']}
    withdrawal = record.get('withdrawal', {})
    expected_sources = {p: sha for p, sha in receipt['definition']['source_files'].items()
                        if p.startswith('src/autonomy_lab/') or p in {
                            'fixtures/expectations.json', 'fixtures/database.sql', 'infra/toolchain.json'}}
    checks = {
        'evaluated_admission': receipt['eligible'] is True and admission['decisions'] == [
            {'revision': 1, 'kind': 'promoted', 'receipt': json.dumps(receipt, sort_keys=True)},
            {'revision': 2, 'kind': 'withdrawn', 'receipt': json.dumps({'version': receipt['version']}, sort_keys=True)}],
        'terminal_withdrawal': admission['state'] == [{'id': 1, 'revision': 2, 'active': None, 'active_revision': None}]
            and admission['versions'] == [{'version': receipt['version'], 'withdrawn': 1,
                                           'definition': json.dumps(receipt['definition'], sort_keys=True)}]
            and withdrawal.get('decision') == withdrawn,
        'admitted_before_work': record.get('admission') == promoted,
        'campaign_source_matches_calibration': bool(expected_sources) and card['source_sha256'] == expected_sources,
        'episode_pins_retained': bool(episodes) and sorted(admission['pins'], key=lambda r: r['episode']) == sorted([
            {key: e['procedure'][key] for key in ('episode', 'version', 'revision')} for e in episodes],
            key=lambda r: r['episode']),
    }
    checks['pin_precedes_tools_and_withdrawal'] = bool(episodes) and all(
        e['procedure']['episode'] == e['id'] and e['procedure']['version'] == receipt['version']
        and e['procedure']['revision'] == 1 and e['procedure']['variant'] == receipt['definition']['variant']
        and e['attempt']['started_at'] <= e['procedure']['at'] <= withdrawal.get('requested_at', 0)
        and bool(e['evidence']) and all(epoch(row['timestamp']) >= e['procedure']['at'] for row in e['evidence'])
        for e in episodes)
    operations = card['operations']
    checks['every_dispatch_bound_before_write'] = len(bindings) == len(operations) and all(
        len(matches := [b for b in bindings if b['operation_id'] == op['operation_id']]) == 1
        and len(selected := [e for e in episodes if e['id'] == matches[0]['pin']['episode']]) == 1
        and matches[0]['pin'] == {k: selected[0]['procedure'][k] for k in ('episode', 'version', 'revision', 'variant')}
        and selected[0]['procedure']['at'] <= epoch(op['created_at']) <= matches[0]['at']
        for op in operations)
    return checks


def finished_after_release(episode, released_at):
    outcome = episode['outcome']
    evidence = episode['evidence']
    return (outcome is not None and bool(evidence) and outcome['claim'].get('outcome') == 'healthy'
            and evidence[-1]['source'] == 'finish' and evidence[-1]['payload'] == outcome['claim']
            and released_at <= epoch(evidence[-1]['timestamp']) <= outcome['finished_at'])


def episode_evidence(directory, workers):
    episodes, bindings, unpinned = [], [], []
    for worker in workers:
        for episode in worker['episodes']:
            path = directory / 'workers' / worker['id'] / episode['id']
            if (path / 'procedure.json').exists():
                episodes.append({**episode, 'worker': worker['id'], 'procedure': read(path / 'procedure.json'),
                                 'evidence': [json.loads(line) for line in (path / 'evidence.jsonl').read_text().splitlines()]})
            elif (path / 'evidence.jsonl').exists() or episode['outcome'] is not None or (path / 'operation.json').exists():
                unpinned.append(episode['id'])
            if (path / 'operation.json').exists():
                bindings.append(read(path / 'operation.json'))
    return episodes, bindings, unpinned


def evaluate(gate):
    directory = gate / 'campaign'
    spec, record = read(gate / 'declaration.json'), read(gate / 'record.json')
    case = spec['withdrawal_case']
    calibration = gate.parent.parent / spec['calibration_name']
    receipt = evaluate_calibration(calibration, 'runbook_fallback')
    card = scorecard(directory)
    admitted = ledger(directory / 'admission.sqlite')
    episodes, bindings, unpinned = episode_evidence(directory, card['workers'])
    checks = binding_checks(card, record, admitted, receipt, episodes, bindings)
    checks['every_executed_episode_pinned'] = not unpinned
    contract = Contract.model_validate(read(ROOT / f'scenarios/campaign-withdrawal-{case}.json')).model_dump()
    checks.update(frozen_protocol=spec == declaration(case, spec['calibration_name']) and card['contract'] == contract,
                  complete_calendar=card['sample_counts']['unknown'] == 0,
                  unchanged_workload=card['identities_unchanged'] is True and len(card['identities_before']) >= 11,
                  owner_cleanup=card['owner_finished'] and card['cleanup']['status'] == 'deleted')
    raw = {int(p.stem): read(p) for p in (directory / 'samples').glob('*.json')}
    # Do not trust stored verdicts: reproduce every raw independent probe.
    for sample in raw.values():
        verify_record(sample['verification'], contract['sample_window_seconds'])
    captured = read(gate / 'server-audit.json')
    checks['audit_collection_closed'] = captured['collection_closed'] is True
    withdrawal = record['withdrawal']
    if case == 'uncertain':
        barrier = read(directory / 'workers' / record['repair_worker'] / 'dispatch-barrier.json')
        base = ambiguity.assess_case(card, spec, record, read(gate / 'before-kill.json'), barrier,
                                    ambiguity.journal_events(directory), captured, raw)
        checks.update({'ambiguity_' + k: v for k, v in base['checks'].items()})
        checks['withdrawn_between_real_effect_and_kill'] = (
            barrier['at'] <= withdrawal['requested_at'] <= withdrawal['finished_at'] <= record['kill_requested_at'])
        writes = [e for e in captured['events'] if e.get('userAgent') == 'autonomy-lab-operation/' + barrier['operation_id']
                  and e.get('verb') == 'patch' and e.get('responseStatus', {}).get('code') == 200]
        checks['binding_precedes_audited_write'] = len(bindings) == len(writes) == 1 and (
            bindings[0]['at'] <= epoch(writes[0]['requestReceivedTimestamp']))
        checks['no_admission_after_restart'] = admitted['refusals'] == [] and all(
            e['worker'] != record['resumed_worker'] for e in episodes)
        audit = base['execution_audit']
    else:
        def stamp(value):
            return datetime.fromtimestamp(value, UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        audit = assess(captured['events'], [], started_at=stamp(card['window']['start']),
                       finished_at=stamp(card['window']['end']), malformed_lines=captured['malformed_lines'])
        writes = [e for e in audit['events'] if e.get('objectRef', {}).get('resource') == 'services'
                  and e.get('verb') in {'create', 'patch', 'update', 'delete', 'deletecollection'}]
        workers = [w for w in card['workers'] if w['id'].startswith('operator-')]
        worker = workers[0] if len(workers) == 1 else {}
        barrier = read(directory / 'workers' / record['initial_worker'] / 'finish-barrier.json')
        escalation = worker.get('escalation') or {}
        checks.update(
            all_samples_healthy=all(s['verdict'] == 'verified_success' for s in card['samples']),
            no_mutations_or_pending_work=not writes and not card['operations'] and not card['dispatch_budget_reserved'],
            independent_audit=audit['status'] == 'assessed' and audit['successful_unmatched_mutations'] == 0,
            one_observer_one_operator=len(card['workers']) == 2 and len(workers) == 1,
            withdrawal_while_pinned=(len(episodes) == 1 and barrier['episode'] == episodes[0]['id']
                and episodes[0]['procedure']['at'] <= barrier['at'] <= card['window']['start'] + spec['barrier_deadline_offset']
                and barrier['at'] <= withdrawal['requested_at'] <= withdrawal['finished_at'] <= record['released_at']
                and 0 <= withdrawal['requested_at'] - card['window']['start'] - spec['withdraw_offset'] <= spec['schedule_lateness_seconds']),
            old_episode_finishes_under_pin=len(episodes) == 1 and finished_after_release(episodes[0], record['released_at']),
            new_episode_refused=(escalation.get('reason') == 'procedure_admission_refused'
                and escalation.get('detail') == 'No admitted procedure' and worker.get('failure') is None
                and worker.get('finished') is not None and len(worker.get('episodes', [])) == 2
                and withdrawal['finished_at'] <= escalation.get('at', 0)
                <= worker['finished']['at'] <= record['released_at'] + spec['refusal_deadline_seconds']),
            refusal_retained=len(admitted['refusals']) == 1
                and admitted['refusals'][0]['action'] == 'start_episode'
                and json.loads(admitted['refusals'][0]['details']).get('reason') == 'No admitted procedure',
        )
        refused = [e for e in worker.get('episodes', []) if e['id'] == escalation.get('episode')]
        checks['refused_episode_never_uses_tools'] = len(refused) == 1 and refused[0]['outcome'] is None and not (
            directory / 'workers' / worker['id'] / refused[0]['id'] / 'evidence.jsonl').exists()
        audit = {k: v for k, v in audit.items() if k != 'events'}
    return {'status': 'passed' if all(checks.values()) else 'failed', 'case': case, 'checks': checks,
            'version': receipt['version'], 'activation_revision': 1, 'withdrawal_revision': 2,
            'pinned_episodes': len(episodes), 'bound_dispatches': len(bindings),
            'service_sample_counts': card['sample_counts'], 'execution_audit': audit,
            'limits': ['Known deterministic procedure; no generated learning or production reliability claim.',
                       'Withdrawal blocks fresh episodes, not the completion of an already running bounded episode.',
                       'Restart never resumes a pinned episode. Reconciliation preserves uncertainty and cannot replay.',
                       'Trusted controller, host, evidence storage and clock; hashes detect drift, not authenticity.']}
