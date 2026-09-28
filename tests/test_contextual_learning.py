"""Authored unit cases, never empirical learning evidence."""

import copy
import hashlib

import pytest

from autonomy_lab.procedures import Refused
from experiments.contextual_learning import policy
from experiments.contextual_learning.evaluate import decide, observation
from experiments.contextual_learning.protocol import ARMS, BLOCKS, CONTEXTS, schedule, source_for


def feedback(successes):
    return {'offered': 128, 'timely_correct': successes}


def test_reward_updates_belong_to_previous_context_not_current_context():
    before = {'context': 'mode-a', 'step': 0, 'memory': {}, 'previous': None}
    first = policy.step(before)
    assert before['memory'] == {} and first['action'] == 4
    after = policy.step({'context': 'mode-b', 'step': 400, 'memory': first['memory'],
                         'previous': {'context': 'mode-a', 'action': 4, 'feedback': feedback(96)}})
    assert after['memory']['contexts']['mode-a']['rewards']['4'] == [.75]
    assert after['memory']['contexts']['mode-b']['visits'] == 0
    assert first['memory']['contexts']['mode-a']['rewards']['4'] == []


def test_decision_uses_measured_rewards_and_is_invariant_to_label_and_spent_step():
    known = policy.empty()
    known.update(visits=7, rewards={'2': [.9, .9], '4': [.7, .7], '8': [.5, .5]})
    obs = {'context': 'opaque', 'step': 7000, 'memory': {'contexts': {'opaque': known}}, 'previous': None}
    assert policy.step(obs)['action'] == 2
    obs['memory']['contexts']['opaque']['rewards']['8'] = [1., 1.]
    assert policy.step(obs)['action'] == 8
    obs['context'] = 'renamed'
    obs['step'] = 0
    obs['memory']['contexts']['renamed'] = obs['memory']['contexts'].pop('opaque')
    assert policy.step(obs)['action'] == 8


def test_measured_drop_resets_only_affected_context():
    known = policy.empty()
    known['rewards']['4'] = [1., 1.]
    other = policy.empty()
    obs = {'context': 'b', 'step': 0, 'memory': {'contexts': {'a': known, 'b': other}},
           'previous': {'context': 'a', 'action': 4, 'feedback': feedback(64)}}
    result = policy.step(obs)['memory']['contexts']
    assert result['a']['resets'] == 1 and result['a']['rewards']['4'] == [.5]
    assert result['b'] == other


def test_blind_comparator_changes_only_context_partition(monkeypatch):
    monkeypatch.setattr(policy, 'CONTEXT_BLIND', True)
    obs = {'context': 'a', 'step': 0, 'memory': {}, 'previous': None}
    first = policy.step(obs)
    obs.update(context='b', memory=first['memory'], previous={'context': 'a', 'action': 4, 'feedback': feedback(100)})
    assert set(policy.step(obs)['memory']['contexts']) == {'*'}


def test_erasure_happens_once_and_cannot_reset_work_or_expose_hidden_capacity():
    last = {'identity': {'context': 'mode-a'}, 'decision': {'result': {'memory': {'learned': 1}}},
            'action': 4, 'feedback': feedback(100)}
    identity = {'arm': 'erased', 'phase': 'retention', 'step': 16, 'context': 'mode-b', 'capacity': 16}
    result = observation(last, identity)
    assert result == {'step': 16, 'context': 'mode-b', 'memory': {}, 'previous': None}
    identity['step'] += 1
    result = observation(last, identity)
    assert result['memory'] == {'learned': 1} and result['previous']['context'] == 'mode-a'
    assert set(result) == {'step', 'context', 'memory', 'previous'}


def test_schedule_balances_execution_position_and_context_capacity_without_leaking_source():
    positions = []
    for block in range(BLOCKS):
        rows = schedule(block)
        assert len(rows) == 512
        order = list(dict.fromkeys(r['arm'] for r in rows))
        positions.append(order)
        for arm in ARMS:
            selected = [r for r in rows if r['arm'] == arm]
            assert [r['step'] for r in selected] == list(range(64))
            for phase in ('acquire', 'retention', 'changed', 'return'):
                for context in CONTEXTS:
                    group = [r for r in selected if r['phase'] == phase and r['context'] == context]
                    assert len(group) == 8 and {r['capacity'] for r in group} in ({2}, {16})
    for arm in ARMS:
        assert sum(order.index(arm) for order in positions) == BLOCKS * 3.5
    assert hashlib.sha256(source_for('generated').encode()).hexdigest() == '8eeeeea0221f02864ba9bf2a6cc8ae5b4eeab3c9539883b30e32067ba225224e'
    assert source_for('retained') == source_for('erased')
    assert source_for('blind') == source_for('retained') + '\nCONTEXT_BLIND = True\n'


def authored_scores():
    return [{'block': b, **r, 'offered': 128, 'timely_correct': 112 if r['arm'] == 'retained' else 100,
             'seconds': 1.0} for b in range(BLOCKS) for r in schedule(b)]


def test_gates_require_memory_relevance_baseline_value_and_complete_population():
    data = authored_scores()
    result = decide(data)
    assert result['autonomous_parameter_learning_gate_passed'] and result['operating_value_gate_passed']
    for mode in ('erased', 'blind', 'fixed-4', 'aimd', 'generated', 'late', 'acquisition', 'time', 'block', 'changed'):
        altered = copy.deepcopy(data)
        for r in altered:
            if mode in ARMS and r['arm'] == mode:
                r['timely_correct'] = 113
            if r['arm'] == 'retained':
                if ((mode == 'late' and r['phase'] == 'retention' and r['context_round'] >= 6) or
                    (mode == 'acquisition' and r['phase'] == 'acquire') or
                    (mode == 'block' and r['block'] == 0) or
                    (mode == 'changed' and r['phase'] == 'changed')):
                    r['timely_correct'] = 0
                if mode == 'time':
                    r['seconds'] = 3
        assert not decide(altered)['operating_value_gate_passed'], mode
    for altered in (data[:-1], [*data[:-1], data[0]]):
        with pytest.raises(Refused):
            decide(altered)


def test_equal_outcomes_do_not_establish_learning():
    data = authored_scores()
    for r in data:
        r['timely_correct'] = 100
    result = decide(data)
    assert not result['autonomous_parameter_learning_gate_passed']
    assert not result['operating_value_gate_passed']


def test_negative_controls_cannot_pass_an_auditor_that_rejects_everything(tmp_path, monkeypatch):
    from autonomy_lab.harness import save
    from experiments.contextual_learning import negative
    source = tmp_path / 'authored-unit-case'
    source.mkdir()
    save(source / 'result.json', {'block': 3})
    calls = []

    def reject(directory, declaration, block, image):
        calls.append(block)
        raise Refused('authored reject-everything audit')

    monkeypatch.setattr(negative, 'audit_block', reject)
    with pytest.raises(Refused, match='reject-everything'):
        negative.controls(source, {}, 'authored-image')
    assert calls == [3]


def test_delay_definition_accepts_cast_formatting_but_rejects_changed_workload():
    from experiments.contextual_learning.workload import DEFINITION, verify_definition
    verify_definition(DEFINITION.replace('0.05::', '(0.05)::'))
    for value in (DEFINITION.replace('0.05', '0.005'), DEFINITION.replace('products_data', 'other_data'),
                  DEFINITION.replace('p.stock', '0 AS stock')):
        with pytest.raises(Refused, match='view changed'):
            verify_definition(value)
