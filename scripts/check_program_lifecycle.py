"""Calibrate exact program bytes, then attempt each declared lifecycle case once."""

import argparse
import time
import uuid
from pathlib import Path

from check_ambiguity import run_case as ambiguous_case
from check_refresh import run_case as refresh_case

from autonomy_lab.campaign import read
from autonomy_lab.experiments import release_manifest, run_experiment
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from autonomy_lab.program_admission import ProgramRegistry, configuration
from autonomy_lab.program_admission import evaluate as evaluate_calibration
from autonomy_lab.program_lifecycle import CASES, declaration, evaluate
from autonomy_lab.withdrawal import capture_audit


def withdraw(gate, record):
    directory = gate / 'campaign'
    record['admission'] = read(directory / 'admission.json')
    registry = ProgramRegistry(directory / 'admission.sqlite')
    record['withdrawal'] = {'requested_at': time.time()}
    save(gate / 'record.json', record)
    decision = registry.withdraw(expected_revision=record['admission']['revision'])
    record['withdrawal'].update(finished_at=time.time(), decision=decision)
    save(gate / 'record.json', record)


def before_release(gate, record, index):
    case = read(gate / 'declaration.json')['program_lifecycle_case']
    record['admission'] = read(gate / 'campaign/admission.json')
    save(gate / 'record.json', record)
    if case == 'before_first' or case == 'between_attempts' and index == 1:
        withdraw(gate, record)
        return True
    return False


def captured_evaluate(gate):
    capture_audit(gate)
    return evaluate(gate)


def run(calibration=None):
    gate = ROOT / 'artifacts' / ('program-lifecycle-gate-' + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    run_id = uuid.uuid4().hex[:8]
    calibration = calibration.resolve() if calibration is not None else None
    declared_run = calibration or ROOT / 'artifacts' / ('experiment-' + run_id)
    require(declared_run.parent == gate.parent, 'Retain calibration beside its lifecycle study')
    raw = (ROOT / 'procedures/bounded-refresh.json').read_bytes()
    config = configuration(raw)
    specs = [declaration(case, declared_run.name) for case in CASES]
    save(gate / 'declaration.json', {'cases': specs, 'calibration': config,
         'source_files': release_manifest(config)['files'], 'calibration_name': declared_run.name})
    ledger = {'status': 'running', 'started_at': time.time(), 'calibration_name': declared_run.name,
              'cases': {c: {'status': 'unrun'} for c in CASES}}
    save(gate / 'result.json', ledger)
    try:
        if calibration is None:
            calibration = run_experiment(config, run_id=run_id)
        require(calibration == declared_run, 'Calibration identity changed')
        receipts = {'program': evaluate_calibration(calibration, raw),
                    'program_adverse': evaluate_calibration(calibration, raw, adverse=True)}
        save(gate / 'receipts.json', receipts)
        require(receipts['program']['eligible'] is True, 'Maintained program did not qualify')
        require(receipts['program_adverse']['eligible'] is False and
                {o['scenario'] for o in receipts['program_adverse']['outcomes'] if not o['task_success']}
                == {'routing', 'lost_ack'}, 'Valid adverse program did not fail declared recovery cases')
        registry = ProgramRegistry(gate / 'admission.sqlite')
        rejected = registry.promote(calibration, raw, expected_revision=0, adverse=True)
        require(rejected['kind'] == 'rejected' and registry.state()['active'] is None, 'Adverse policy became active')
        accepted = registry.promote(calibration, raw, expected_revision=1)
        require(accepted['kind'] == 'promoted', 'Qualified program did not activate')
        ledger['calibration'] = {'status': 'passed', 'rejected': rejected, 'promoted': accepted}
        save(gate / 'result.json', ledger)
        for spec in specs:
            case_name = spec['program_lifecycle_case']
            case = gate / case_name
            case.mkdir()
            save(case / 'declaration.json', spec)
            ledger['cases'][case_name] = {'status': 'running'}
            save(gate / 'result.json', ledger)
            try:
                if case_name == 'uncertain':
                    ambiguous_case(case, spec, manifest=ROOT / spec['manifest'], calibration=calibration,
                                   at_barrier=withdraw, evaluator=captured_evaluate)
                else:
                    refresh_case(case, spec, calibration=calibration, at_preflight=before_release,
                                 evaluator=captured_evaluate)
            except BaseException as error:
                ledger['cases'][case_name] = {'status': 'failed', 'error_type': type(error).__name__}
                if not isinstance(error, Exception):
                    raise
            else:
                ledger['cases'][case_name] = {'status': 'passed'}
            save(gate / 'result.json', ledger)
        ledger['status'] = 'passed' if all(r['status'] == 'passed' for r in ledger['cases'].values()) else 'failed'
        require(ledger['status'] == 'passed', 'A declared program lifecycle case failed; no retry')
    except BaseException as error:
        ledger.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        ledger['finished_at'] = time.time()
        save(gate / 'result.json', ledger)
        print(gate, flush=True)
    return gate


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--calibration', type=Path)
    run(parser.parse_args().calibration)
