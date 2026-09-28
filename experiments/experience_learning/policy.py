"""Small online reward estimator, with a separately implemented conventional control.

Inputs contain only this arm's past measurements. No capacity labels or future
schedule enter a decision. State is serialized after every batch and reloaded.
"""

import copy
import statistics

LEVELS = (1, 2, 4, 8, 16)
ARMS = ('retained', 'erased', 'aimd', *(f'fixed-{n}' for n in LEVELS))


def initial():
    return {'version': 1, 'step': 0, 'rewards': {str(n): [] for n in LEVELS},
            'aimd': 1, 'aimd_reference_seconds': None}


def erase(state):
    result = copy.deepcopy(state)
    result['rewards'] = {str(n): [] for n in LEVELS}
    return result


def choose(arm, state):
    if arm.startswith('fixed-'):
        return int(arm.removeprefix('fixed-'))
    if arm == 'aimd':
        return state['aimd']
    unseen = [n for n in LEVELS if not state['rewards'][str(n)]]
    if unseen:
        return unseen[0]
    if state['step'] % 5 == 0:
        return LEVELS[(state['step'] // 5 - 1) % len(LEVELS)]
    return max(LEVELS, key=lambda n: (statistics.mean(state['rewards'][str(n)]), -n))


def learn(state, action, feedback):
    result = copy.deepcopy(state)
    result['step'] += 1
    result['rewards'][str(action)] = (
        result['rewards'].get(str(action), []) + [feedback['timely_correct'] / feedback['offered']]
    )[-3:]
    # Calibrate from this arm's first error-free low-concurrency batch, including
    # transport overhead. Waiting in the admission queue does not enter this p90.
    durations = sorted(feedback['dispatch_seconds'])
    p90 = durations[min(len(durations) - 1, int(.9 * len(durations)))] if durations else 0
    if result['aimd_reference_seconds'] is None and action == 1 and durations and not feedback['server_errors']:
        result['aimd_reference_seconds'] = p90
    reference = result['aimd_reference_seconds']
    congested = feedback['server_errors'] > 0 or (reference is not None and p90 > 2 * reference)
    result['aimd'] = (1 if reference is None else max(1, action // 2) if congested else min(16, action + 1))
    return result
