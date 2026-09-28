"""Independent semantic reward reconstruction and complete population audit."""

import hashlib
import json
import math
from pathlib import Path

from autonomy_lab.procedures import require

from .policy import ARMS, choose, erase, initial, learn
from .protocol import BATCH_SIZE, BLOCKS, DEADLINE_SECONDS, PHASES, plan, schedule


def read(path):
    return json.loads(Path(path).read_text())


def strict_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def number(value):
    require(type(value) in (float, int) and math.isfinite(value) and value >= 0, 'Invalid timestamp')
    return value


def classify(records, cases, concurrency):
    require(len(records) == BATCH_SIZE, 'Offered population missing')
    timely = correct = errors = 0
    dispatch_seconds, events = [], []
    for index, item in enumerate(records):
        case = cases[index % len(cases)]
        require(item['index'] == index and item['case_id'] == case['id'], 'Request identity differs')
        if item['start'] is None:
            require(item == {'index': index, 'case_id': case['id'], 'start': None,
                             'end': None, 'status': None, 'body': None}, 'Undispatched request has output')
            continue
        start, end = number(item['start']), number(item['end'])
        require(start < DEADLINE_SECONDS and end >= start, 'Invalid dispatch interval')
        require(end - start < 2.5, 'Possible upstream timeout; drain uncertain')
        require(type(item['status']) is int and 100 <= item['status'] <= 599, 'Missing response; trial incomplete')
        require(type(item['body']) is str, 'Missing raw body')
        dispatch_seconds.append(end - start)
        events.extend([(start, 1), (end, -1)])
        errors += item['status'] >= 500
        try:
            body = json.loads(item['body'])
        except (ValueError, TypeError):
            body = None
        ok = item['status'] == case['status_code'] and (
            'body' not in case or strict_equal(body, case['body']))
        correct += ok
        timely += ok and end <= DEADLINE_SECONDS
    active = 0
    for _, change in sorted(events):
        active += change
        require(0 <= active <= concurrency, 'Concurrency bound violated')
    require(active == 0, 'Outstanding request')
    return {'offered': BATCH_SIZE, 'timely_correct': timely, 'correct': correct,
            'server_errors': errors, 'dispatch_seconds': dispatch_seconds}


def inventory(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file()}


def audit_block(directory, declared, block):
    directory = Path(directory)
    require(declared == plan(), 'Source/declaration changed')
    ledger = read(directory / 'result.json')
    require(ledger['status'] == 'complete' and ledger['block'] == block, 'Original block incomplete')
    require(ledger['completed_batches'] == ledger['planned_batches'] == len(schedule(block)), 'Incomplete ledger')
    require(inventory(directory / 'raw') == ledger['raw_sha256'], 'Raw inventory changed')
    raw = directory / 'raw'
    cases = read(raw / 'expectations.json')['quotes']
    from autonomy_lab.kubernetes import ROOT
    require(read(raw / 'expectations.json') == read(ROOT / 'fixtures/expectations.json'), 'Oracle changed')
    require(read(raw / 'cleanup.json')['status'] == 'deleted', 'Cleanup not confirmed')
    controls = read(raw / 'controls.json')
    require(len(controls) == len(PHASES), 'Missing intervention controls')
    products = read(raw / 'expectations.json')['products']
    baseline = controls[0]['workload']
    for phase_index, control in enumerate(controls):
        expected_capacity = schedule(block)[phase_index * 10 * len(ARMS)]['capacity']
        require(control['phase'] == PHASES[phase_index] and control['role_limit'] == expected_capacity,
                'Capacity intervention not established')
        require(control['products'] == products and control['workload'] == baseline,
                'Persistent workload or data changed')
    final = read(raw / 'final-control.json')
    require(final['workload'] == baseline and final['products'] == products, 'Final workload or data changed')
    states = {arm: initial() for arm in ARMS}
    rows = []
    prior_end = 0
    expected_files = {'expectations.json', 'cleanup.json', 'controls.json', 'final-control.json'}
    for index, expected in enumerate(schedule(block)):
        name = f'batch-{index:03}.json'
        expected_files.add(name)
        batch = read(raw / name)
        require(batch['identity'] == expected, 'Batch order or identity differs')
        require(batch['status'] == 'complete' and batch['drain']['reader_connections'] == 0 and
                number(batch['drain']['wait_seconds']) < 5, 'Drain not confirmed')
        arm = expected['arm']
        state = states[arm]
        if arm == 'erased' and expected['phase'] == 'retention' and expected['round'] == 0:
            state = erase(state)
        require(batch['before'] == state, 'History did not replay')
        action = choose(arm, state)
        require(batch['action'] == action, 'Action did not replay')
        feedback = classify(batch['requests'], cases, action)
        require(batch['feedback'] == feedback, 'Reward did not reproduce')
        after = learn(state, action, feedback)
        require(batch['after'] == after, 'Update did not replay')
        start, end = number(batch['start']), number(batch['end'])
        require(start >= prior_end and end >= start, 'Overlapping batches')
        require(all(r['end'] is None or r['end'] <= end - start for r in batch['requests']), 'Response outside batch')
        prior_end = end
        states[arm] = after
        rows.append({'block': block, **expected, 'action': action,
                     **{k: v for k, v in feedback.items() if k != 'dispatch_seconds'}})
    require(set(ledger['raw_sha256']) == expected_files, 'Unexpected or missing raw evidence')
    return rows


def decide(rows):
    require(len(rows) == BLOCKS * len(schedule(0)), 'Incomplete comparison')
    keys = [(r['block'], r['phase'], r['round'], r['arm']) for r in rows]
    expected = [(b, r['phase'], r['round'], r['arm']) for b in range(BLOCKS) for r in schedule(b)]
    require(sorted(keys) == sorted(expected), 'Population differs')

    def selected_rows(block, arm, phases, rounds=range(10)):
        return [r for r in rows if r['block'] == block and r['arm'] == arm and
                r['phase'] in phases and r['round'] in rounds]

    def fraction(block, arm, phases, rounds=range(10)):
        selected = selected_rows(block, arm, phases, rounds)
        return sum(r['timely_correct'] for r in selected) / sum(r['offered'] for r in selected)

    def delta(block, phases, rounds=range(10)):
        return (sum(r['timely_correct'] for r in selected_rows(block, 'retained', phases, rounds)) -
                sum(r['timely_correct'] for r in selected_rows(block, 'erased', phases, rounds)))

    summaries = []
    for block in range(BLOCKS):
        phases = {p: {a: fraction(block, a, {p}) for a in ARMS} for p in PHASES}
        evaluation = {a: fraction(block, a, set(PHASES) - {'acquire'}) for a in ARMS}
        lifetime = {a: fraction(block, a, set(PHASES)) for a in ARMS}
        summaries.append({'block': block, 'phase_fractions': phases, 'evaluation_fractions': evaluation,
                          'lifetime_fractions': lifetime,
                          'retention_reacquisition_gain': delta(block, {'retention'}, range(5)) / (5 * BATCH_SIZE),
                          'retention_post_relearning_gain': delta(block, {'retention'}, range(5, 10)) / (5 * BATCH_SIZE),
                          'retention_gain': phases['retention']['retained'] - phases['retention']['erased'],
                          'evaluation_gain': evaluation['retained'] - evaluation['erased']})
    # Count differences avoid a floating-point boundary around exactly 5pp.
    experience = (sum(delta(b, {'retention'}) for b in range(BLOCKS)) >= 256
                  and all(delta(b, {'retention'}) > 0 and
                          delta(b, {'retention'}, range(5, 10)) >= 0 for b in range(BLOCKS))
                  and sum(delta(b, set(PHASES) - {'acquire'}) for b in range(BLOCKS)) >= 0)
    value = experience and all(s[metric]['retained'] >= s[metric][a]
                               for s in summaries for metric in ('evaluation_fractions', 'lifetime_fractions')
                               for a in ARMS if a not in ('retained', 'erased'))
    return {'experience_gate_passed': experience, 'comparative_value_gate_passed': value,
            'blocks': summaries, 'novel_procedure_learning_proved': False,
            'production_or_generalization_claim': False}
