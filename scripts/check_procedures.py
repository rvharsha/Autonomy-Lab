"""Run real calibration trials and check a separate admission ledger.

Pins below exercise controller state, not dispatched work. check_withdrawal
separately consumes this release's evidence in live campaigns. Failed attempts
are retained in both gates.
"""

import argparse
import json
import uuid
from pathlib import Path

from autonomy_lab.experiments import release_manifest, run_experiment
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import Refused, Registry, calibration_config, evaluate, require


def check(output, run=None):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    config = calibration_config()
    run_id = uuid.uuid4().hex[:8]
    declared_run = run or ROOT / 'artifacts' / ('experiment-' + run_id)
    declaration = {'config': config, 'source_files': release_manifest(config)['files'],
                   'experiment_directory': str(declared_run), 'mode': 'existing' if run else 'execute',
                   'claim': 'Known-procedure admission calibration; no live rollout or learned improvement'}
    save(output / 'declaration.json', declaration)
    result = {'status': 'failed', 'stage': 'execution', 'experiment_directory': str(declared_run)}
    try:
        if run is None:
            run = run_experiment(config, run_id=run_id)
        receipts = {}
        for variant in ('runbook', 'runbook_fallback'):
            result['stage'] = 'evaluate_' + variant
            receipts[variant] = evaluate(run, variant)
            save(output / 'receipts.json', receipts)
        result['stage'] = 'calibration'
        require({o['scenario'] for o in receipts['runbook']['outcomes'] if not o['task_success']}
                == {'observer_outage'}, 'Negative calibration control differs')
        require(receipts['runbook_fallback']['eligible'] is True, 'Positive calibration control failed')
        registry_path = output / 'admission.sqlite'
        result['stage'] = 'admission'
        registry = Registry(registry_path)
        rejected = registry.promote(run, 'runbook', expected_revision=0)
        require(rejected['kind'] == 'rejected' and registry.state()['active'] is None,
                'Failed procedure became active')
        promoted = registry.promote(run, 'runbook_fallback', expected_revision=1)
        require(promoted['kind'] == 'promoted', 'Eligible procedure was not promoted')
        pin = registry.pin('calibration-pin')
        withdrawn = registry.withdraw(expected_revision=2)
        registry = Registry(registry_path)
        require(registry.pin('calibration-pin') == pin, 'Withdrawal changed historical binding')
        try:
            registry.pin('after-withdrawal')
        except Refused:
            blocked = True
        else:
            blocked = False
        require(blocked, 'Withdrawal admitted new work')
        require(release_manifest(config)['files'] == declaration['source_files'], 'Source drifted during gate')
        result.update(status='passed', rejected=rejected, promoted=promoted, withdrawn=withdrawn,
                      stage='completed', pin_retained=True, new_pin_blocked=True, final_state=registry.state())
        return result
    except BaseException as error:
        result['error_type'] = type(error).__name__
        if isinstance(error, Refused):
            result['reason'] = str(error)
        raise
    finally:
        save(output / 'result.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--run', type=Path, help='Existing complete trusted calibration run; no re-execution')
    args = parser.parse_args()
    output = ROOT / 'artifacts' / ('procedure-gate-' + uuid.uuid4().hex[:8])
    print(output, flush=True)
    print(json.dumps(check(output, args.run.resolve() if args.run else None), sort_keys=True))


if __name__ == '__main__':
    main()
