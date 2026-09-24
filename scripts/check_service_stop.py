"""Real GCP/Linux service-stop gate. Run as the host administrator; no model calls."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from service_experiment import digest, load_job, read

from autonomy_lab.harness import save, timestamp
from autonomy_lab.janitor import process_identity
from autonomy_lab.kubernetes import ROOT


def unit_state(unit):
    output = subprocess.check_output(['systemctl', 'show', unit,
        '--property=ActiveState,SubState,MainPID,ControlGroup,ExecMainCode,ExecMainStatus,Restart,KillMode,ExecStopPost'],
        text=True, timeout=15)
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def run(mode, user):
    if os.geteuid() != 0:
        raise PermissionError('System service gate requires host administrator access')
    subprocess.run(['sudo', '-u', user, 'mkdir', '-p', str(ROOT / 'artifacts')], check=True, timeout=15)
    output = ROOT / 'artifacts' / ('service-gate-' + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, mode=0o700)
    result = {'mode': mode, 'status': 'running', 'started_at': timestamp()}
    save(output / 'result.json', result)
    directory = None
    unit = None
    try:
        script = str(ROOT / 'scripts/service_experiment.py')
        python = str(Path(sys.executable).absolute())
        prepared = subprocess.check_output(['sudo', '-u', user, 'env', 'PYTHONPATH=' + str(ROOT / 'src'),
            python, script, 'prepare', str(ROOT / 'scenarios/service-stop-gate.yaml')], text=True, timeout=30)
        directory = Path(prepared.strip())
        job, run_dir = load_job(directory)
        if job['plan'] != [{'scenario': scenario, 'variant': 'runbook_fallback', 'repetition': 0}
                           for scenario in ('routing', 'healthy')]:
            raise ValueError('Gate manifest differs from its declared ordered plan')
        unit = 'autolab-study-' + job['run_id'] + '.service'
        result.update(job=directory.name, experiment=run_dir.name, unit=unit)
        save(output / 'result.json', result)
        subprocess.run([python, script, 'launch', str(directory), '--user', user, '--runtime-seconds', '1800'],
                       check=True, timeout=30)
        deadline = time.monotonic() + 900
        while True:
            path = run_dir / 'trial-001/evidence.jsonl'
            lines = path.read_bytes().splitlines() if path.exists() else []
            try:
                evidence = [json.loads(line) for line in lines]
            except ValueError:
                evidence = []  # A concurrently appended record may not yet be complete.
            dispatches = [e for e in evidence if e.get('source') == 'propose_repair'
                          and e.get('payload', {}).get('status') == 'acknowledged']
            if dispatches:
                if read(run_dir / 'trial-001/trial.json')['status'] != 'running':
                    raise RuntimeError('Missed the running trial termination boundary')
                break
            if (directory / 'post-stop.json').exists():
                raise RuntimeError('Service stopped before a repair acknowledgement')
            if time.monotonic() >= deadline:
                raise TimeoutError('No real routing repair before readiness deadline')
            time.sleep(0.25)
        state = unit_state(unit)
        janitor_pid = read(run_dir / 'janitor-process.json')['pid']
        janitor_identity = process_identity(janitor_pid)
        controller_cgroup = Path(f"/proc/{state['MainPID']}/cgroup").read_text()
        janitor_cgroup = Path(f'/proc/{janitor_pid}/cgroup').read_text()
        if not janitor_identity or controller_cgroup != janitor_cgroup:
            raise RuntimeError('Gate did not establish the original shared control group')
        if state['KillMode'] != 'control-group' or state['Restart'] != 'no' or not state['ExecStopPost']:
            raise RuntimeError('Unexpected service termination policy')
        claim_hash = digest(directory / 'launch-claim.json')
        result.update(before=state, controller_cgroup=controller_cgroup, janitor_cgroup=janitor_cgroup,
                      acknowledged_repairs_before_stop=len(dispatches), trigger_at=timestamp())
        save(output / 'result.json', result)
        if mode == 'kill':
            command = ['systemctl', 'kill', '--kill-whom=all', '--signal=SIGKILL', unit]
        else:
            command = ['systemctl', mode, unit]
        # Wait for the restart job's new start phase, not the transient inactive
        # state between its stop and start. Both stop phases have a 300s budget.
        subprocess.run(command, check=True, timeout=630)
        # TimeoutStopSec bounds process termination and ExecStopPost separately.
        deadline = time.monotonic() + 630
        while not (directory / 'post-stop.json').exists() or unit_state(unit)['ActiveState'] in {'active', 'activating', 'deactivating'}:
            if time.monotonic() >= deadline:
                raise TimeoutError('Post-stop phase did not finish')
            time.sleep(0.5)
        receipt = read(directory / 'post-stop.json')
        result['post_stop'] = receipt
        if receipt['status'] != 'finished' or receipt['cleanup'] != 'deleted' or any(receipt['remaining'].values()):
            raise RuntimeError('Post-stop cleanup failed')
        accounting = read(directory / 'post-stop-accounting.json')
        if (accounting['planned'], accounting['controller_recorded'], accounting['attempted'],
                accounting['unassessed_attempts'], accounting['unrun']) != (2, 0, 1, 1, 1):
            raise RuntimeError('Interruption accounting differs from the declared gate')
        if any(row['task_success'] is not None or row['audit_assessed'] is not None for row in accounting['trials']):
            raise RuntimeError('Interrupted trial received an invented assessment')
        for name, sha in accounting['original_evidence_sha256'].items():
            if digest(run_dir / name) != sha:
                raise RuntimeError('Recovery rewrote original evidence')
        if digest(directory / 'launch-claim.json') != claim_hash:
            raise RuntimeError('Launch claim changed during restart')
        if process_identity(janitor_pid) == janitor_identity:
            raise RuntimeError('Original detached janitor is still alive')
        if mode == 'restart':
            journal = subprocess.check_output(['journalctl', '-u', unit, '--no-pager', '-o', 'cat'], text=True, timeout=15)
            if 'FileExistsError' not in journal or unit_state(unit)['ExecMainStatus'] != '1':
                raise RuntimeError('No recorded refusal of the restarted invocation')
        result.update(status='passed', after=unit_state(unit), post_stop=receipt,
                      accounting=accounting, original_janitor_terminated=True,
                      launch_claim_unchanged=True, original_evidence_unchanged=True,
                      restart_refused=True if mode == 'restart' else None)
    except BaseException as error:
        result.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        # A failed gate must still trigger its supervised cleanup; never leave a
        # running study because the test's own assertion or readiness check failed.
        if unit:
            try:
                stopped = subprocess.run(['systemctl', 'stop', unit], capture_output=True, timeout=630)
                result['final_stop_exit_code'] = stopped.returncode
                journal = subprocess.run(['journalctl', '-u', unit, '--no-pager', '-o', 'json'],
                                         capture_output=True, timeout=15)
                (output / 'service-journal.jsonl').write_bytes(journal.stdout)
            except Exception as error:
                result.update(status='failed', final_stop_error_type=type(error).__name__)
        result['finished_at'] = timestamp()
        save(output / 'result.json', result)
        print(output, flush=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['stop', 'restart', 'kill'])
    parser.add_argument('--user', default='autolab')
    arguments = parser.parse_args()
    run(arguments.mode, arguments.user)
