"""Corrupt copies of executed evidence; these are not additional live trials."""

import shutil

from autonomy_lab.campaign import read
from autonomy_lab.harness import save
from autonomy_lab.procedures import Refused, require

from .gate import evaluate


def controls(source, frozen_at, destination):
    original = source / 'observer-reconciliation-shard-0/raw'
    rows = read(original / 'results.json')
    index = next(i for i, r in enumerate(rows, 1) if r['variant'] == 'desired_state' and r['scenario'] == 'observer_routing')
    trial = f'trial-{index:03d}'
    cases = {
        'wrong_intent': (trial + '/reconciliation-binding.json', lambda v: v['intent'].update(service_uid='other-resource'), 'Intent binding differs or is late'),
        'late_intent': (trial + '/reconciliation-binding.json', lambda v: v.update(at=1e20), 'Intent binding differs or is late'),
        'changed_final_summary': (trial + '/final-verification.json', lambda v: v.update(verdict='indeterminate'), 'Verification summary does not reproduce'),
        'missing_cleanup': ('cleanup.json', lambda v: v.update(status='kept'), 'Cleanup is incomplete'),
        'omitted_attempt': ('accounting.json', lambda v: v.update(recorded=7), 'Incomplete trial accounting'),
        'changed_worker': (trial + '/worker-request.json', lambda v: v.update(variant='program'), 'Worker declaration differs'),
        'changed_journal_export': (trial + '/operations.json', lambda v: v[0]['request'].update(target_port=9090), 'Operation journal export differs'),
        'missing_actor_window': (None, None, 'Actor verifier summary lacks its raw window'),
        'wrong_trial_identity': (trial + '/trial.json', lambda v: v.update(scenario='observer_outage'), 'Trial identity differs from plan'),
    }
    result = {}
    for name, (relative, corrupt, reason) in cases.items():
        copy = destination / name
        shutil.copytree(original, copy)
        if relative:
            path = copy / relative
            value = read(path)
            corrupt(value)
            save(path, value)
        else:
            for path in (copy / trial).glob('verification-*.json'):
                path.unlink()
        try:
            evaluate(copy, 0, frozen_at)
        except Refused as error:
            require(str(error) == reason, 'Negative control refused for an unexpected reason: ' + name)
            result[name] = {'status': 'refused', 'reason': reason}
        else:
            raise Refused('Corrupted evidence was accepted: ' + name)
    return result
