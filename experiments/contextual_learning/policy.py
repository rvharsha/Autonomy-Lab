"""Authored update rule; all numerical reward knowledge comes from this arm.

Context labels have no built-in action mapping. No clock, phase, capacity or
external step determines an action. This is parameter learning, not code evolution.
"""

import copy

LEVELS = (4, 2, 8)


def empty():
    return {'visits': 0, 'rewards': {str(n): [] for n in LEVELS},
            'last_seen': {str(n): -1 for n in LEVELS}, 'resets': 0}


def step(observation):
    state = copy.deepcopy(observation['memory']) or {'contexts': {}}
    previous = observation['previous']
    if previous is not None:
        key = '*' if CONTEXT_BLIND else previous['context']
        known = state['contexts'].setdefault(key, empty())
        action = str(previous['action'])
        reward = previous['feedback']['timely_correct'] / previous['feedback']['offered']
        history = known['rewards'][action]
        # A measured drop triggers reacquisition only for the affected context.
        # The threshold is frozen before service observations, not fit to this run.
        if len(history) >= 2 and reward < sum(history) / len(history) - .12:
            resets = known['resets'] + 1
            known = empty()
            known['resets'] = resets
            state['contexts'][key] = known
        known['rewards'][action] = (known['rewards'][action] + [reward])[-4:]
        known['last_seen'][action] = known['visits']
        known['visits'] += 1
    key = '*' if CONTEXT_BLIND else observation['context']
    known = state['contexts'].setdefault(key, empty())
    unseen = [n for n in LEVELS if len(known['rewards'][str(n)]) < 2]
    if unseen:
        action = unseen[0]
    elif known['visits'] % 6 == 0:
        action = min(LEVELS, key=lambda n: known['last_seen'][str(n)])
    else:
        action = max(LEVELS, key=lambda n: (sum(known['rewards'][str(n)]) /
                                          len(known['rewards'][str(n)]), -n))
    return {'action': action, 'memory': state}


CONTEXT_BLIND = False  # The context-blind comparator changes only this constant.
