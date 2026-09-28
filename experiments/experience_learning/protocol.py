"""Prospective declaration and deterministic, balanced block schedule."""

import hashlib
import random

from autonomy_lab.experiments import release_manifest
from autonomy_lab.kubernetes import ROOT

from .policy import ARMS, LEVELS

BATCH_SIZE = 128
DEADLINE_SECONDS = 1.0
ROUNDS_PER_PHASE = 10
PHASES = ('acquire', 'retention', 'changed', 'return')
BLOCKS = 4
BLOCK_SECONDS = 35 * 60


def schedule(block):
    assert type(block) is int and 0 <= block < BLOCKS
    rng = random.Random(2026092800 + block)
    initial_capacity = 2 if block % 2 == 0 else 16
    capacities = (initial_capacity, initial_capacity, 18 - initial_capacity, initial_capacity)
    rows = []
    for phase, capacity in zip(PHASES, capacities, strict=True):
        for round_index in range(ROUNDS_PER_PHASE):
            order = list(ARMS)
            rng.shuffle(order)
            rows.extend({'phase': phase, 'round': round_index, 'arm': arm,
                         'capacity': capacity} for arm in order)
    return rows


def plan():
    files = release_manifest({})['files']
    names = ['docs/EXPERIENCE_LEARNING.md', '.github/workflows/experience-learning.yml',
             'experiments/__init__.py',
             *[str(p.relative_to(ROOT)) for p in sorted((ROOT / 'experiments/experience_learning').glob('*.py'))]]
    files.update({n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names})
    return {'version': 1, 'files': files, 'blocks': [schedule(i) for i in range(BLOCKS)],
            'batch_size': BATCH_SIZE, 'deadline_seconds': DEADLINE_SECONDS,
            'block_wall_seconds': BLOCK_SECONDS,
            'levels': list(LEVELS), 'arms': list(ARMS), 'attempts': 1, 'model_calls': 0,
            'claim': 'bounded online parameter learning; authored workload, not novel procedures',
            'reset': 'erase reward history once after acquisition; preserve step and all spent work',
            'primary': 'retention phase timely-correct fraction: retained minus erased',
            'experience_gate': 'mean primary gain >= 0.05, positive in all four blocks; post-relearning retention gain >= 0 in every block; full evaluation aggregate retained >= erased',
            'value_gate': 'experience gate plus evaluation and lifetime retained >= AIMD and every fixed arm in each block',
            'stop': 'incomplete accounting, transport timeout, unresolved work, changed source or failed cleanup withholds all claims'}
