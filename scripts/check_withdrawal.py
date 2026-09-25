"""Calibrate the exact release, then withdraw admission in two real campaigns."""

import argparse
import hashlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from check_ambiguity import run_case as ambiguous_case
from check_campaign import await_file, finalize_gate, wait_until
from check_procedures import check as calibrate

from autonomy_lab.campaign import read
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import Registry
from autonomy_lab.withdrawal import CASES, capture_audit, declaration, evaluate


def withdraw(gate, record):
    directory = gate / 'campaign'
    record['admission'] = read(directory / 'admission.json')
    registry = Registry(directory / 'admission.sqlite')
    record['withdrawal'] = {'requested_at': time.time()}
    save(gate / 'record.json', record)
    decision = registry.withdraw(expected_revision=record['admission']['revision'])
    record['withdrawal'].update(finished_at=time.time(), decision=decision)
    save(gate / 'record.json', record)


def captured_evaluate(gate):
    capture_audit(gate)
    return evaluate(gate)


def healthy_case(gate, spec, calibration):
    directory = gate / 'campaign'
    result = {'status': 'failed', 'started_at': time.time(), 'declaration': spec}
    record = {}
    with (gate / 'owner.log').open('ab') as log:
        owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
            str(ROOT / 'scenarios/campaign-withdrawal-healthy.json'), str(directory),
            '--calibration', str(calibration)], stdout=log, stderr=log, start_new_session=True,
            env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
    try:
        window = await_file(directory / 'window.json', time.monotonic() + 900)
        initial = next((directory / 'workers').glob('operator-*'))
        record['initial_worker'] = initial.name
        save(gate / 'record.json', record)
        barrier = await_file(initial / 'finish-barrier.json', time.monotonic() + max(
            0, window['start'] + spec['barrier_deadline_offset'] - time.time()))
        wait_until(window['start'] + spec['withdraw_offset'])
        withdraw(gate, record)
        # Record intent before release so the racing worker cannot finish first.
        record['released_at'] = time.time()
        save(gate / 'record.json', record)
        save(initial / 'finish-release.json', {'episode': barrier['episode']})
        await_file(initial / 'finished.json', time.monotonic() + spec['refusal_deadline_seconds'])
        owner.wait(timeout=max(1, window['end'] - time.time()) + 180)
        if owner.returncode != 0:
            raise RuntimeError('Campaign owner failed')
        for suffix in ('a', 'b'):
            save(gate / f'scorecard-{suffix}.json', scorecard(directory))
            save(gate / f'evaluation-{suffix}.json', captured_evaluate(gate))
        for name in ('scorecard', 'evaluation'):
            if (gate / f'{name}-a.json').read_bytes() != (gate / f'{name}-b.json').read_bytes():
                raise AssertionError('Export is not reproducible')
        assessment = read(gate / 'evaluation-a.json')
        if assessment['status'] != 'passed':
            raise AssertionError('Withdrawal contract not satisfied: ' + ', '.join(k for k, v in assessment['checks'].items() if not v))
        result.update(status='passed', export_identical=True,
            scorecard_sha256=hashlib.sha256((gate / 'scorecard-a.json').read_bytes()).hexdigest(),
            evaluation_sha256=hashlib.sha256((gate / 'evaluation-a.json').read_bytes()).hexdigest())
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        try:
            finalize_gate(owner, [], directory, gate, result)
        finally:
            try:
                if (directory / 'window.json').exists():
                    save(gate / 'scorecard-final.json', scorecard(directory))
                    save(gate / 'evaluation-final.json', captured_evaluate(gate))
            except Exception as error:
                result['export_error_type'] = type(error).__name__
                if result['status'] == 'passed':
                    result['status'] = 'failed'
                    raise
            finally:
                save(gate / 'result.json', result)


def run(calibration=None):
    gate = ROOT / 'artifacts' / ('withdrawal-gate-' + uuid.uuid4().hex[:8])
    gate.mkdir(parents=True, mode=0o700)
    ledger = {'status': 'running', 'started_at': time.time(), 'cases': {c: {'status': 'unrun'} for c in CASES}}
    save(gate / 'result.json', ledger)
    try:
        if calibration is None:
            output = ROOT / 'artifacts' / ('procedure-gate-' + uuid.uuid4().hex[:8])
            ledger['calibration_gate'] = output.name
            save(gate / 'result.json', ledger)
            calibration = Path(calibrate(output)['experiment_directory'])
        if calibration.parent.resolve() != gate.parent.resolve():
            raise ValueError('Retain calibration beside the withdrawal study for offline reproduction')
        specs = [declaration(case, calibration.name) for case in CASES]
        save(gate / 'declaration.json', {'cases': specs})
        for spec in specs:
            case = gate / spec['withdrawal_case']
            case.mkdir()
            save(case / 'declaration.json', spec)
            ledger['cases'][spec['withdrawal_case']] = {'status': 'running'}
            save(gate / 'result.json', ledger)
            try:
                if spec['withdrawal_case'] == 'healthy':
                    healthy_case(case, spec, calibration)
                else:
                    ambiguous_case(case, spec, manifest=ROOT / 'scenarios/campaign-withdrawal-uncertain.json',
                                   calibration=calibration, at_barrier=withdraw, evaluator=captured_evaluate)
            except BaseException as error:
                ledger['cases'][spec['withdrawal_case']] = {'status': 'failed', 'error_type': type(error).__name__}
                if not isinstance(error, Exception):
                    raise
                # Preserve each failed identity; the other declared case still runs.
            else:
                ledger['cases'][spec['withdrawal_case']] = {'status': 'passed'}
            save(gate / 'result.json', ledger)
        ledger['status'] = 'passed' if all(r['status'] == 'passed' for r in ledger['cases'].values()) else 'failed'
        if ledger['status'] != 'passed':
            raise AssertionError('One or more withdrawal campaigns failed')
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
    mode.add_argument('--calibration', type=Path, help='Complete same-release calibration beside the new study')
    args = parser.parse_args()
    run(args.calibration.resolve() if args.calibration else None)
