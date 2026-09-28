"""Reconstruct all offered requests and replay untrusted policies in isolation."""

from pathlib import Path

from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from experiments.experience_learning.evaluate import classify, inventory, number, read, strict_equal
from experiments.generated_policy.runtime import invoke, validate_result

from .protocol import ARMS, BLOCKS, CONTEXTS, PHASES, plan, schedule, source_for
from .workload import verify_definition


def observation(last, identity):
    if last is None or (identity['arm'] == 'erased' and identity['phase'] == 'retention' and identity['step'] == 16):
        return {'step': identity['step'], 'context': identity['context'], 'memory': {}, 'previous': None}
    return {'step': identity['step'], 'context': identity['context'], 'memory': last['decision']['result']['memory'],
            'previous': {'context': last['identity']['context'], 'action': last['action'], 'feedback': last['feedback']}}


def audit_block(directory, declaration, block, image_id):
    directory = Path(directory)
    require(declaration['plan'] == plan(), 'Frozen source changed')
    require(read(directory / 'declaration.json') == declaration, 'Declaration differs')
    ledger = read(directory / 'result.json')
    require(ledger['status'] == 'complete' and ledger['block'] == block, 'Original block incomplete')
    require(ledger['completed_batches'] == ledger['planned_batches'] == len(schedule(block)), 'Incomplete ledger')
    require(ledger['policy_image'] == image_id, 'Replay image differs')
    raw = directory / 'raw'
    require(inventory(raw) == ledger['raw_sha256'], 'Raw inventory changed')
    require(0 < declaration['frozen_at'] < number(ledger['started_at']) <= number(ledger['finished_at']), 'Execution predates freeze')
    require(read(raw / 'policies.json') == {a: source_for(a) for a in ARMS}, 'Policy source changed')
    expected = read(ROOT / 'fixtures/expectations.json')
    require(read(raw / 'expectations.json') == expected, 'Oracle changed')
    require(read(raw / 'cleanup.json')['status'] == 'deleted', 'Cleanup not confirmed')
    controls = read(raw / 'controls.json')
    expected_controls = []
    for arm in dict.fromkeys(r['arm'] for r in schedule(block)):
        arm_rows = [r for r in schedule(block) if r['arm'] == arm]
        prior = None
        for row in arm_rows:
            context = (row['phase'], row['context'])
            if context != prior:
                expected_controls.append({k: row[k] for k in ('arm', 'step', 'phase', 'context', 'capacity')})
                prior = context
        expected_controls.append({'arm': arm, 'step': len(arm_rows), 'phase': 'final',
                                  'context': arm_rows[-1]['context'], 'capacity': arm_rows[-1]['capacity']})
    require(len(controls) == len(expected_controls), 'Missing controls')
    used, baselines, images = set(), {}, None
    for c, wanted in zip(controls, expected_controls, strict=True):
        require(all(c[k] == wanted[k] for k in ('arm', 'step', 'phase', 'context')) and
                c['role_limit'] == wanted['capacity'], 'Control identity or capacity differs')
        arm = c['arm']
        baseline = baselines.get(arm)
        if baseline is None:
            baseline = baselines[arm] = c['workload']
            current_images = sorted(i['image_id'] for i in baseline if 'image_id' in i)
            images = images or current_images
            require(len(current_images) == 3 and current_images == images, 'Images differ between arms')
            identities = {i.get('uid', i.get('service_uid')) for i in baseline}
            require(None not in identities and len(identities) == 4 and not (identities & used), 'Workload reused between arms')
            used |= identities
        require(c['workload'] == baseline and c['products'] == expected['products'], 'Workload or data changed')
        verify_definition(c['read_delay_view'])
    # Check every raw reward before expensive isolated replay. Corrupted copies
    # cannot consume a complete replay merely to expose a late semantic error.
    for index, _ in enumerate(schedule(block)):
        batch = read(raw / f'batch-{index:03}.json')
        result = validate_result(batch['decision']['result'])
        require(batch['action'] == result['action'], 'Action differs')
        require(strict_equal(classify(batch['requests'], expected['quotes'], batch['action']),
                             batch['feedback']), 'Feedback differs')
    rows, last, prior_end = [], None, 0
    expected_files = {'policies.json', 'expectations.json', 'controls.json', 'cleanup.json'}
    for index, identity in enumerate(schedule(block)):
        name = f'batch-{index:03}.json'
        expected_files.add(name)
        batch = read(raw / name)
        require(batch['identity'] == identity and batch['status'] == 'complete', 'Batch identity or status differs')
        if last is not None and last['identity']['arm'] != identity['arm']:
            last = None
        before = observation(last, identity)
        require(strict_equal(batch['before'], before), 'Observation does not replay')
        require(batch['drain']['reader_connections'] == 0 and number(batch['drain']['wait_seconds']) < 5, 'Unconfirmed drain')
        decision = invoke(source_for(identity['arm']), before, image_id)
        require(strict_equal(decision['result'], batch['decision']['result']) and
                decision['stdout_sha256'] == batch['decision']['stdout_sha256'], 'Nondeterministic or altered policy result')
        require(batch['action'] == decision['result']['action'], 'Action differs')
        feedback = classify(batch['requests'], expected['quotes'], batch['action'])
        require(strict_equal(feedback, batch['feedback']), 'Feedback differs')
        start, end = number(batch['start']), number(batch['end'])
        policy_start, policy_end = number(batch['policy_start']), number(batch['policy_end'])
        duration = number(batch['decision']['seconds'])
        require(prior_end <= policy_start <= policy_end <= start <= end and
                0 < duration <= 10 and duration <= policy_end - policy_start, 'Overlapping or invalid decision/batch timing')
        require(all(r['end'] is None or r['end'] <= end - start for r in batch['requests']), 'Response outside batch')
        prior_end, last = end, batch
        rows.append({'block': block, **identity, 'action': batch['action'],
                     'seconds': end - start + policy_end - policy_start,
                     **{k: v for k, v in feedback.items() if k != 'dispatch_seconds'}})
    require(set(ledger['raw_sha256']) == expected_files, 'Unexpected or missing evidence')
    return rows


def decide(rows):
    def key(r):
        return (r['block'], r['arm'], r['step'])
    expected = [{'block': b, **r} for b in range(BLOCKS) for r in schedule(b)]
    require(sorted(map(key, rows)) == sorted(map(key, expected)), 'Incomplete comparison')
    for actual, wanted in zip(sorted(rows, key=key), sorted(expected, key=key), strict=True):
        require(all(actual[k] == v for k, v in wanted.items()), 'Comparison identity differs')
        require(type(actual['offered']) is int and actual['offered'] == 128 and
                type(actual['timely_correct']) is int and 0 <= actual['timely_correct'] <= 128 and
                number(actual['seconds']) > 0, 'Invalid comparison score')

    def total(arm, blocks=range(BLOCKS), phases=PHASES, context=None, late=False):
        selected = [r for r in rows if r['arm'] == arm and r['block'] in blocks and r['phase'] in phases
                    and (context is None or r['context'] == context) and
                    (not late or r['context_round'] >= 6)]
        return {k: sum(r[k] for r in selected) for k in ('timely_correct', 'offered', 'seconds')}

    def gain(a, b, **kwargs):
        x, y = total(a, **kwargs), total(b, **kwargs)
        require(x['offered'] == y['offered'] and x['offered'] > 0, 'Unmatched comparison')
        return (x['timely_correct'] - y['timely_correct']) / x['offered']

    evaluation = PHASES[1:]
    memory_by_block = {str(b): gain('retained', 'erased', blocks=[b], phases=['retention']) for b in range(BLOCKS)}
    late_by_block = {str(b): gain('retained', 'erased', blocks=[b], phases=['retention'], late=True) for b in range(BLOCKS)}
    memory_gain = gain('retained', 'erased', phases=['retention'])
    memory = (memory_gain >= .03 and all(g > 0 for g in memory_by_block.values()) and
              all(g >= 0 for g in late_by_block.values()) and gain('retained', 'erased', phases=evaluation) >= 0)
    context_by_block = {str(b): gain('retained', 'blind', blocks=[b], phases=evaluation) for b in range(BLOCKS)}
    context_by_label = {c: gain('retained', 'blind', context=c, phases=evaluation) for c in CONTEXTS}
    context_gain = gain('retained', 'blind', phases=evaluation)
    context = (context_gain >= .03 and all(g >= 0 for g in context_by_block.values()) and
               all(g >= 0 for g in context_by_label.values()))
    windows = {'evaluation': evaluation, 'lifetime': PHASES}
    baselines = ('fixed-2', 'fixed-4', 'fixed-8', 'aimd', 'generated')
    baseline_gains = {w: {a: gain('retained', a, phases=p) for a in baselines} for w, p in windows.items()}
    changed_gains = {a: gain('retained', a, phases=['changed']) for a in baselines}
    goodput = {a: total(a)['timely_correct'] / total(a)['seconds'] for a in ARMS}
    value = (memory and context and all(g >= .03 for v in baseline_gains.values() for g in v.values()) and
             all(gain('retained', a, blocks=[b], phases=p) >= 0 for b in range(BLOCKS)
                 for p in windows.values() for a in baselines) and
             all(g >= -.01 for g in changed_gains.values()) and
             all(goodput['retained'] >= goodput[a] for a in baselines))
    return {'retained_memory_gate_passed': memory, 'context_gate_passed': context,
            'operating_value_gate_passed': value, 'autonomous_parameter_learning_gate_passed': memory and context,
            'pooled': {w: {a: total(a, phases=p) for a in ARMS} for w, p in windows.items()},
            'blocks': [{w: {a: total(a, blocks=[b], phases=p) for a in ARMS} for w, p in windows.items()} for b in range(BLOCKS)],
            'retention_gain': memory_gain, 'retention_gains': memory_by_block, 'late_retention_gains': late_by_block,
            'context_gain': context_gain, 'context_gains': context_by_block, 'context_label_gains': context_by_label,
            'baseline_gains': baseline_gains, 'changed_gains': changed_gains,
            'timely_responses_per_batch_and_decision_second': goodput,
            'generated_algorithm': False, 'model_necessity_proved': False, 'production_admission': False}
