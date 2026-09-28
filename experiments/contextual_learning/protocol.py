"""Freeze observation changes, schedules, policy bytes and criteria before traffic."""

import hashlib
import random

from autonomy_lab.experiments import release_manifest
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from experiments.experience_learning.evaluate import read

ARMS = ('retained', 'erased', 'blind', 'fixed-4', 'aimd', 'generated', 'fixed-2', 'fixed-8')
PHASES = ('acquire', 'retention', 'changed', 'return')
CONTEXTS = ('mode-a', 'mode-b')
BLOCKS = 6
BLOCK_SECONDS = 45 * 60
DECLARATION = 'docs/validation/contextual-learning-v2/declaration.json'
GENERATED = 'docs/validation/generated-policy-v2/proposal.json'


def source_for(arm):
    require(arm in ARMS, 'Unknown arm')
    if arm in ('retained', 'erased', 'blind'):
        source = (ROOT / 'experiments/contextual_learning/policy.py').read_text()
        return source + ('\nCONTEXT_BLIND = True\n' if arm == 'blind' else '')
    if arm.startswith('fixed-'):
        return 'def step(observation):\n    return {"action": ' + arm[6:] + ', "memory": {}}\n'
    if arm == 'generated':
        return read(ROOT / GENERATED)['candidate']['source']
    return (ROOT / 'experiments/experience_learning/policy.py').read_text() + '''
def step(observation):
    memory = observation["memory"] or {"contexts": {}}
    previous = observation["previous"]
    if previous is not None:
        key = previous["context"]
        memory["contexts"][key] = learn(memory["contexts"].get(key, initial()),
                                         previous["action"], previous["feedback"])
    state = memory["contexts"].setdefault(observation["context"], initial())
    return {"action": choose("aimd", state), "memory": memory}
'''


def schedule(block):
    require(type(block) is int and 0 <= block < BLOCKS, 'Invalid block')
    rng = random.Random(202609280100 + block)
    phases = []
    # Eight visits per context per phase, in fresh shuffled runs of two visits.
    # Two labels disclose context identity, never the hidden capacity mapping.
    for phase in PHASES:
        labels = list(CONTEXTS) * 4
        rng.shuffle(labels)
        visits = dict.fromkeys(CONTEXTS, 0)
        for label in labels:
            low = (label == CONTEXTS[block % 2]) != (phase == 'changed')
            for _ in range(2):
                phases.append({'phase': phase, 'context': label, 'capacity': 2 if low else 16,
                               'context_round': visits[label]})
                visits[label] += 1
    rows = []
    offset = 2 * (block // 2)
    order = ARMS[offset:] + ARMS[:offset]
    if block % 2:
        order = tuple(reversed(order))
    for arm in order:
        rows.extend({'arm': arm, 'step': step, **row} for step, row in enumerate(phases))
    return rows


def plan():
    files = release_manifest({})['files']
    names = ['docs/CONTEXTUAL_LEARNING.md', '.github/workflows/contextual-learning.yml',
             'tests/test_contextual_learning.py', 'experiments/__init__.py', GENERATED]
    for folder in ('experience_learning', 'generated_policy', 'contextual_learning'):
        names.extend(str(p.relative_to(ROOT)) for p in sorted((ROOT / 'experiments' / folder).glob('*.py')))
    files.update({n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names})
    return {'version': 2, 'files': files, 'blocks': [schedule(b) for b in range(BLOCKS)],
            'policy_sha256': {a: hashlib.sha256(source_for(a).encode()).hexdigest() for a in ARMS},
            'block_seconds': BLOCK_SECONDS, 'attempts': 1, 'model_calls': 0,
            'batch_size': 128, 'deadline_seconds': 1, 'database_read_delay_seconds': .05,
            'dispatched_request_seconds_max': 2.5, 'drain_wait_seconds_max': 5,
            'memory_gate': 'retained-erased retention >=3pp pooled, positive every block; retention context_round>=6 nonnegative every block; full evaluation nonnegative',
            'context_gate': 'retained-blind evaluation >=3pp pooled, nonnegative every block and each visible context pooled',
            'value_gate': 'both learning gates; retained >=3pp over fixed2/fixed4/fixed8, context-aware AIMD and PR30 generated in evaluation and lifetime; nonnegative every block/window; changed phase regression <=1pp pooled vs each baseline; lifetime measured batch+decision goodput >= each baseline',
            'claim': 'authored contextual parameter learner with autonomous reward updates; not generated algorithms, novel procedures or production admission',
            'stop': 'any missing or invalid original, drifted source, failed replay or cleanup withholds benefit decisions'}
