"""Authored unit cases for invariants; never used as real experiment outcomes."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from autonomy_lab.procedures import Refused

with patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1]), *sys.path]):
    from experiments.experience_learning.evaluate import classify, decide
    from experiments.experience_learning.policy import ARMS, LEVELS, choose, erase, initial, learn
    from experiments.experience_learning.protocol import BATCH_SIZE, BLOCKS, schedule
    from experiments.experience_learning.run import feedback_from_responses


def authored_requests():
    cases = json.loads(Path('fixtures/expectations.json').read_text())['quotes']
    requests = []
    for index in range(BATCH_SIZE):
        case = cases[index % len(cases)]
        requests.append({'index': index, 'case_id': case['id'], 'start': None,
                         'end': None, 'status': None, 'body': None})
    requests[0].update(start=0.0, end=.2, status=200, body=json.dumps(cases[0]['body']))
    requests[1].update(start=.3, end=1.1, status=200, body=json.dumps(cases[1]['body']))
    return requests, cases


def test_all_arrivals_and_late_work_remain_in_denominator():
    requests, cases = authored_requests()
    score = classify(requests, cases, 1)
    assert score == feedback_from_responses(requests, cases)
    assert score['offered'] == 128 and score['correct'] == 2 and score['timely_correct'] == 1


@pytest.mark.parametrize('replacement', [False, '125', 125.0, 999])
def test_success_status_cannot_hide_wrong_typed_body(replacement):
    requests, cases = authored_requests()
    body = json.loads(requests[0]['body'])
    body['total_minor'] = replacement
    requests[0]['body'] = json.dumps(body)
    assert classify(requests, cases, 1)['timely_correct'] == 0
    assert feedback_from_responses(requests, cases)['timely_correct'] == 0


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'overlap', 'timeout', 'uncertain', 'nan'])
def test_unverifiable_requests_are_refused(mutation):
    requests, cases = authored_requests()
    if mutation == 'missing':
        requests.pop()
    elif mutation == 'duplicate':
        requests[-1] = requests[0]
    elif mutation == 'overlap':
        requests[1]['start'] = .1
    elif mutation == 'timeout':
        requests[1]['end'] = 3
    elif mutation == 'uncertain':
        requests[0]['status'] = None
    else:
        requests[0]['end'] = float('nan')
    with pytest.raises(Refused):
        classify(requests, cases, 1)


def test_erasure_removes_only_reward_history_and_permits_relearning():
    state = initial()
    for action in LEVELS:
        state = learn(state, action, {'offered': 128, 'timely_correct': action,
                                     'server_errors': 0, 'dispatch_seconds': [.01]})
    original = copy.deepcopy(state)
    reset = erase(state)
    assert state == original and reset['step'] == state['step'] == 5
    assert reset['aimd'] == state['aimd'] and all(not v for v in reset['rewards'].values())
    assert choose('erased', reset) == 1
    updated = learn(reset, 1, {'offered': 128, 'timely_correct': 5,
                              'server_errors': 0, 'dispatch_seconds': [.01]})
    assert updated['step'] == 6 and choose('erased', updated) == 2


def test_controller_can_increase_despite_queueing_and_decrease_on_errors():
    state = initial()
    state = learn(state, 1, {'offered': 128, 'timely_correct': 5,
                            'server_errors': 0, 'dispatch_seconds': [.01]})
    assert choose('aimd', state) == 2
    state = learn(state, 16, {'offered': 128, 'timely_correct': 127,
                             'server_errors': 1, 'dispatch_seconds': [.01]})
    assert choose('aimd', state) == 8


def test_aimd_supports_intermediate_limits_outside_learners_grid():
    state = initial()
    for expected in range(1, 17):
        action = choose('aimd', state)
        assert action == expected
        state = learn(state, action, {'offered': 128, 'timely_correct': 20,
                                     'server_errors': 0, 'dispatch_seconds': [.01]})
    assert choose('aimd', state) == 16


def test_aimd_calibrates_from_own_requests_including_transport_overhead():
    state = initial()
    for action, latency, expected in [(1, .4, 2), (2, .45, 3), (3, .9, 1)]:
        state = learn(state, action, {'offered': 128, 'timely_correct': 2,
                                     'server_errors': 0, 'dispatch_seconds': [latency]})
        assert choose('aimd', state) == expected
        assert state['aimd_reference_seconds'] == .4


def test_late_zero_connection_readback_cannot_pass_live_drain(monkeypatch):
    from unittest.mock import MagicMock

    from experiments.experience_learning import run

    clock = iter([0, 4.9, 5.1])
    monkeypatch.setattr(run.time, 'monotonic', lambda: next(clock))
    connection = MagicMock()
    connection.__enter__.return_value.execute.return_value.fetchone.return_value = (0,)
    monkeypatch.setattr(run.psycopg, 'connect', lambda *a, **kw: connection)
    with pytest.raises(Refused, match='did not drain in time'):
        run.drain('unit-test-only', {'requests': []})


def authored_rows():
    return [{'block': b, **r, 'offered': 128, 'timely_correct': 128}
            for b in range(BLOCKS) for r in schedule(b)]


def test_tie_and_missing_or_aliased_populations_cannot_prove_learning():
    rows = authored_rows()
    assert not decide(rows)['experience_gate_passed']
    with pytest.raises(Refused):
        decide(rows[:-1])
    rows[-1] = rows[0]
    with pytest.raises(Refused):
        decide(rows)


def test_experience_benefit_does_not_imply_comparative_value():
    rows = authored_rows()
    for row in rows:
        if row['arm'] == 'retained':
            row['timely_correct'] = 120
        if row['arm'] == 'erased':
            row['timely_correct'] = 100
    result = decide(rows)
    assert result['experience_gate_passed'] and not result['comparative_value_gate_passed']
    assert result['novel_procedure_learning_proved'] is False


def test_acquisition_cost_can_withhold_comparative_value():
    rows = authored_rows()
    for row in rows:
        if row['arm'] == 'erased':
            row['timely_correct'] = 100
        if row['arm'] == 'retained' and row['phase'] == 'acquire':
            row['timely_correct'] = 1
    result = decide(rows)
    assert result['experience_gate_passed'] and not result['comparative_value_gate_passed']


def test_reacquisition_gain_cannot_mask_post_relearning_regression():
    rows = authored_rows()
    for row in rows:
        if row['arm'] == 'erased':
            row['timely_correct'] = 100
        if row['arm'] == 'retained' and row['phase'] == 'retention' and row['round'] >= 5:
            row['timely_correct'] = 99
    result = decide(rows)
    assert all(b['retention_gain'] > .05 and b['retention_post_relearning_gain'] < 0
               for b in result['blocks'])
    assert not result['experience_gate_passed']


def test_exact_five_percentage_point_boundary_uses_counts():
    rows = authored_rows()
    for row in rows:
        if row['arm'] == 'erased' and row['phase'] == 'retention' and row['round'] == 0:
            row['timely_correct'] = 64
    assert decide(rows)['experience_gate_passed']


def test_full_population_and_both_change_directions_declared():
    assert BLOCKS * len(schedule(0)) * BATCH_SIZE == 163840
    for block in range(BLOCKS):
        rows = schedule(block)
        for index in range(0, len(rows), len(ARMS)):
            assert {r['arm'] for r in rows[index:index + len(ARMS)]} == set(ARMS)
        capacities = [rows[i * 80]['capacity'] for i in range(4)]
        assert capacities == ([2, 2, 16, 2] if block % 2 == 0 else [16, 16, 2, 16])
