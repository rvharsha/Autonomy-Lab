"""Authored invariants; these values never enter empirical experiment evidence."""

import copy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from autonomy_lab.procedures import Refused

with patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1]), *sys.path]):
    from experiments.generated_policy.evaluate import decide, observation
    from experiments.generated_policy.protocol import ARMS, BLOCKS, schedule
    from experiments.generated_policy.runtime import container_args, source_for, validate_result


def rows():
    return [{'block': b, **r, 'offered': 128, 'timely_correct': 100, 'seconds': 2}
            for b in range(BLOCKS) for r in schedule(b)]


def test_complete_population_and_balanced_fresh_workload_order():
    assert len(rows()) == 640 and sum(r['offered'] for r in rows()) == 81920
    for position in range(4):
        assert {schedule(b)[40 * position]['arm'] for b in range(4)} == set(ARMS)
    assert {len([r for r in schedule(b) if r['arm'] == 'candidate' and r['phase'] == 'acquire']) for b in range(4)} == {7, 9, 11, 13}


def test_ties_do_not_prove_value_or_memory_and_missing_population_rejected():
    assert not decide(rows())['generated_improvement_gate_passed']
    assert not decide(rows())['retained_memory_gate_passed']
    for altered in (rows()[:-1], [rows()[0], *rows()[1:-1], rows()[0]]):
        with pytest.raises(Refused):
            decide(altered)


def test_gain_must_beat_both_baselines_and_include_acquisition_and_time():
    data = rows()
    for r in data:
        if r['arm'] == 'candidate':
            r['timely_correct'] = 110
    assert decide(data)['generated_improvement_gate_passed']
    for mode in ('legacy', 'acquisition', 'time', 'one_block'):
        altered = copy.deepcopy(data)
        for r in altered:
            if mode == 'legacy' and r['arm'] == 'legacy':
                r['timely_correct'] = 111
            if mode == 'acquisition' and r['arm'] == 'candidate' and r['phase'] == 'acquire':
                r['timely_correct'] = 0
            if mode == 'time' and r['arm'] == 'candidate':
                r['seconds'] = 3
            if mode == 'one_block' and r['arm'] == 'candidate' and r['block'] == 0:
                r['timely_correct'] = 99
        assert not decide(altered)['generated_improvement_gate_passed']


def test_warm_start_cannot_hide_late_memory_regression():
    data = rows()
    for r in data:
        if r['arm'] == 'candidate' and r['phase'] == 'retention':
            r['timely_correct'] = 120 if r['round'] < 5 else 99
    assert not decide(data)['retained_memory_gate_passed']


def test_erasure_cannot_reset_external_work_or_receive_previous_feedback():
    last = {'decision': {'result': {'memory': {'learned': True}}}, 'action': 4, 'feedback': {'observed': True}}
    identity = {'arm': 'erased', 'phase': 'retention', 'round': 0, 'step': 13}
    assert observation(last, identity) == {'step': 13, 'memory': {}, 'previous': None}
    identity['round'] = 1
    assert observation(last, identity)['memory'] == {'learned': True}


@pytest.mark.parametrize('value', [{'action': True, 'memory': {}}, {'action': 17, 'memory': {}},
                                  {'action': 4, 'memory': []}, {'action': 4, 'memory': {}, 'extra': 1},
                                  {'action': 4, 'memory': {'flood': 'x' * 16384}}])
def test_external_action_and_state_validation(value):
    with pytest.raises(Refused):
        validate_result(value)


def test_container_has_no_mount_or_host_environment_forwarding():
    args = container_args('sha256:' + '0' * 64, 'test-only')
    for flag in ('--network=none', '--read-only', '--cap-drop=ALL', '--user=10001:10001', '--security-opt=no-new-privileges'):
        assert flag in args
    assert '--env=PYTHONHASHSEED=0' in args and '-I' not in args and '-E' not in args
    assert '--mount' not in args and '-v' not in args
    assert source_for('legacy', 'untrusted').startswith(Path('experiments/experience_learning/policy.py').read_text())


def test_memory_boundary_uses_same_compact_encoding_as_executor():
    import json
    value = {'action': 4, 'memory': {'v': [0] * 8000, 'padding': 'x' * 364}}
    size = len(json.dumps(value['memory'], separators=(',', ':')).encode())
    value['memory']['padding'] += 'x' * (16384 - size)
    assert len(json.dumps(value['memory'], separators=(',', ':')).encode()) == 16384
    validate_result(value)
    value['memory']['padding'] += 'x'
    with pytest.raises(Refused):
        validate_result(value)


def test_trace_compaction_preserves_every_value_and_original_interleaving():
    from experiments.generated_policy.propose import pack_traces
    original = [[0, 'acquire', 0, 'fixed-4', 2, 4, 91, 3, 98, .12345678901234567],
                [0, 'acquire', 0, 'retained', 2, 1, 62, 0, 63, .07],
                [0, 'retention', 0, 'retained', 2, 8, 80, 8, 90, .1]]
    packed = pack_traces({'development_source': 'authored-unit-case', 'rows': original})
    restored = []
    for group in packed['groups']:
        b, phase, capacity = group['context']
        for row in group['rows']:
            restored.append([b, phase, row[0], packed['arms'][row[1]], capacity, *row[2:]])
    assert restored == original
