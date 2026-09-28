"""Immutable experiment contract, independent of the generated candidate."""

import hashlib

from autonomy_lab.experiments import release_manifest
from autonomy_lab.kubernetes import ROOT

ARMS = ('candidate', 'erased', 'fixed-4', 'legacy')
BLOCKS = 4
PHASES = ('acquire', 'retention', 'changed', 'return')
DWELLS = ((11, 7, 13, 9), (9, 13, 7, 11), (13, 9, 11, 7), (7, 11, 9, 13))
# A Latin rotation balances execution position. Each arm gets a fresh namespace.
BLOCK_SECONDS = 40 * 60
SOURCE_LIMIT = 16384
MEMORY_LIMIT = 16384
OUTPUT_LIMIT = 32768
POLICY_SECONDS = 10


def schedule(block):
    assert type(block) is int and 0 <= block < BLOCKS
    first = 2 if block % 2 == 0 else 16
    rows = []
    for arm in ARMS[block:] + ARMS[:block]:
        step = 0
        for phase, capacity, dwell in zip(PHASES, (first, first, 18 - first, first), DWELLS[block], strict=True):
            for index in range(dwell):
                rows.append({'arm': arm, 'phase': phase, 'capacity': capacity,
                             'round': index, 'step': step})
                step += 1
    return rows


def plan():
    files = release_manifest({})['files']
    names = ['docs/validation/generated-policy/proposal.json', 'docs/GENERATED_POLICY.md', '.github/workflows/generated-policy-confirmation.yml', '.github/workflows/generated-policy-boundary.yml',
             'experiments/__init__.py', 'tests/test_generated_policy.py']
    for folder in ('experience_learning', 'generated_policy'):
        names.extend(str(p.relative_to(ROOT)) for p in sorted((ROOT / 'experiments' / folder).glob('*.py')))
    files.update({n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names})
    return {'version': 3, 'files': files, 'blocks': [schedule(b) for b in range(BLOCKS)],
            'block_seconds': BLOCK_SECONDS, 'attempts': 1, 'model_calls': 1,
            'model': 'gemini-3.8-flash', 'input_tokens_max': 50000, 'output_tokens_max': 8192,
            'source_bytes_max': SOURCE_LIMIT, 'memory_bytes_max': MEMORY_LIMIT,
            'policy_seconds_max': POLICY_SECONDS, 'batch_size': 128, 'deadline_seconds': 1,
            'isolation': 'fresh network-none read-only nonroot container for each decision; stdin only',
            'value_gate': '>=3pp pooled gain over BOTH fixed4 and legacy in evaluation and lifetime; nonnegative gain in each block for both windows; no capacity-pooled regression >1pp; lifetime timely responses per measured batch+decision second >= both baselines',
            'memory_gate': '>=3pp pooled retention gain over erased; positive in all blocks; retention rounds >=5 nonnegative in each block; nonnegative full evaluation gain',
            'stop': 'any incomplete original, changed source, invalid action, nondeterministic replay or unconfirmed cleanup withholds all benefit decisions',
            'claim': 'one generated operating policy, not model necessity, novel cloud procedure or production improvement'}
