"""Reconstruct all offered requests and replay untrusted policies in isolation."""

from pathlib import Path

from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from experiments.experience_learning.evaluate import classify, inventory, number, read, strict_equal

from .protocol import ARMS, BLOCKS, PHASES, plan, schedule
from .runtime import invoke, source_for, validate_result


def observation(last, identity):
    if last is None or (identity['arm'] == 'erased' and identity['phase'] == 'retention' and identity['round'] == 0):
        return {'step': identity['step'], 'memory': {}, 'previous': None}
    return {'step': identity['step'], 'memory': last['decision']['result']['memory'],
            'previous': {'action': last['action'], 'feedback': last['feedback']}}


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
    proposal = read(raw / 'proposal.json')
    from .amend import verify_execution
    verify_execution(declaration, proposal)
    require(proposal == read(ROOT / 'docs/validation/generated-policy-v2/proposal.json'), 'Official proposal differs')
    expected = read(ROOT / 'fixtures/expectations.json')
    require(read(raw / 'expectations.json') == expected, 'Oracle changed')
    require(read(raw / 'cleanup.json')['status'] == 'deleted', 'Cleanup not confirmed')
    controls = read(raw / 'controls.json')
    require(len(controls) == len(ARMS) * (len(PHASES) + 1), 'Missing controls')
    used = set()
    images = None
    for arm in ARMS:
        selected = [c for c in controls if c['arm'] == arm]
        require([c['phase'] for c in selected] == [*PHASES, 'final'], 'Intervention population differs')
        baseline = selected[0]['workload']
        current_images = sorted(c['image_id'] for c in baseline if 'image_id' in c)
        if images is None:
            images = current_images
        require(current_images == images, 'Images differ between arms')
        identities = {c.get('uid', c.get('service_uid')) for c in baseline}
        require(len(identities) == 4 and not (identities & used), 'Workload reused between arms')
        used |= identities
        for c in selected:
            phase = 'return' if c['phase'] == 'final' else c['phase']
            capacity = next(r['capacity'] for r in schedule(block) if r['arm'] == arm and r['phase'] == phase)
            require(c['role_limit'] == capacity and c['workload'] == baseline and
                    c['products'] == expected['products'], 'Workload, capacity or data changed')
    # Check every raw reward before expensive isolated replay. Corrupted copies
    # cannot consume a complete replay merely to expose a late semantic error.
    for index, _ in enumerate(schedule(block)):
        batch = read(raw / f'batch-{index:03}.json')
        result = validate_result(batch['decision']['result'])
        require(batch['action'] == result['action'], 'Action differs')
        require(strict_equal(classify(batch['requests'], expected['quotes'], batch['action']),
                             batch['feedback']), 'Feedback differs')
    rows, last, prior_end = [], None, 0
    expected_files = {'proposal.json', 'expectations.json', 'controls.json', 'cleanup.json'}
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
        decision = invoke(source_for(identity['arm'], proposal['candidate']['source']), before, image_id)
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
    def total(arm, blocks=range(BLOCKS), phases=PHASES, capacity=None, late=False):
        selected = [r for r in rows if r['arm'] == arm and r['block'] in blocks and r['phase'] in phases
                    and (capacity is None or r['capacity'] == capacity) and (not late or r['round'] >= 5)]
        return {k: sum(r[k] for r in selected) for k in ('timely_correct', 'offered', 'seconds')}
    def gain(a, b, **kwargs):
        x, y = total(a, **kwargs), total(b, **kwargs)
        require(x['offered'] == y['offered'] and x['offered'] > 0, 'Unmatched comparison')
        return (x['timely_correct'] - y['timely_correct']) / x['offered']
    evaluation = PHASES[1:]
    windows = {'evaluation': evaluation, 'lifetime': PHASES}
    baselines = ('fixed-4', 'legacy')
    pooled = {window: {a: total(a, phases=p) for a in ARMS} for window, p in windows.items()}
    by_block = [{window: {a: total(a, blocks=[b], phases=p) for a in ARMS}
                 for window, p in windows.items()} for b in range(BLOCKS)]
    gains = {window: {a: gain('candidate', a, phases=p) for a in baselines} for window, p in windows.items()}
    value = all(g >= .03 for v in gains.values() for g in v.values())
    value &= all(gain('candidate', a, blocks=[b], phases=p) >= 0
                 for b in range(BLOCKS) for p in windows.values() for a in baselines)
    value &= all(gain('candidate', a, capacity=c) >= -.01 for c in (2, 16) for a in baselines)
    goodput = {a: total(a)['timely_correct'] / total(a)['seconds'] for a in ARMS}
    value &= all(goodput['candidate'] >= goodput[a] for a in baselines)
    memory_gains = {str(b): gain('candidate', 'erased', blocks=[b], phases=['retention']) for b in range(BLOCKS)}
    late_gains = {str(b): gain('candidate', 'erased', blocks=[b], phases=['retention'], late=True) for b in range(BLOCKS)}
    memory = (gain('candidate', 'erased', phases=['retention']) >= .03 and
              all(g > 0 for g in memory_gains.values()) and all(g >= 0 for g in late_gains.values()) and
              gain('candidate', 'erased', phases=evaluation) >= 0)
    return {'generated_improvement_gate_passed': value, 'retained_memory_gate_passed': memory,
            'pooled': pooled, 'blocks': by_block, 'baseline_gains': gains,
            'retention_gains': memory_gains, 'late_retention_gains': late_gains,
            'timely_responses_per_batch_and_decision_second': goodput,
            'model_necessity_proved': False, 'production_admission': False}
