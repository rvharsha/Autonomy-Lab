"""Reuse qualified corruptions on copied new evidence; originals stay intact."""

import shutil
import tempfile
from pathlib import Path

from autonomy_lab.procedures import Refused, require
from experiments.final_slot.negative import EXPECTED, apply_corruption, manifest, require_rejection

from .gate import evaluate, plan, select


def challenge(source, selection, frozen_at):
    receipts = []
    for name in EXPECTED:
        if name == 'incomplete_case_inventory':
            continue
        case = 'maintained-' + ('protected_before' if name.startswith('early_change_') else 'protected_final')
        paths = list(source.glob('shadow-selection-shard-*/cases/' + case))
        require(len(paths) == 1, 'Missing or duplicate control source case')
        original = paths[0]
        positive = evaluate(original, selection, frozen_at)
        before = manifest(original)
        with tempfile.TemporaryDirectory(prefix='shadow-negative-') as temporary:
            copied = Path(temporary) / case
            shutil.copytree(original, copied)
            apply_corruption(copied, name)
            reason = require_rejection(name, lambda: evaluate(copied, selection, frozen_at))
        require(manifest(original) == before and evaluate(original, selection, frozen_at) == positive,
                'Negative control modified original evidence')
        receipts.append({'name': name, 'rejected': True, 'reason': reason, 'original_unchanged': True})
    try:
        select(plan(selection, frozen_at), {})
    except Refused as error:
        require(str(error) == 'Incomplete or changed shadow comparison', 'Unexpected inventory refusal')
    else:
        raise Refused('Incomplete case inventory accepted')
    receipts.append({'name': 'incomplete_case_inventory', 'rejected': True})
    return {'status': 'passed', 'scope': 'Authored corruptions of copied evidence, not live trials',
            'checks': receipts}
