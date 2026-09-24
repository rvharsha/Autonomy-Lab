"""Real GCP/Linux service-stop gate. Run as the host administrator; no model calls."""

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from service_experiment import load_job

from autonomy_lab.harness import save, timestamp
from autonomy_lab.janitor import process_identity
from autonomy_lab.kubernetes import ROOT


def evidence_bytes(root, name):
    """Read only regular evidence files, without root following lab-owned symlinks."""
    relative = Path(name)
    if not root.is_absolute() or relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise ValueError('Invalid evidence path')
    parts = (*root.parts[1:], *relative.parts)
    if '..' in parts:
        raise ValueError('Invalid evidence root')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open('/', flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Evidence must be a regular file')
            return stream.read()
    finally:
        os.close(directory)


def evidence_digest(root, name):
    return hashlib.sha256(evidence_bytes(root, name)).hexdigest()


def evidence_json(root, name):
    return json.loads(evidence_bytes(root, name))


def unit_state(unit):
    output = subprocess.check_output(['systemctl', 'show', unit,
        '--property=ActiveState,SubState,MainPID,ControlGroup,ExecMainCode,ExecMainStatus,Restart,KillMode,ExecStopPost'],
        text=True, timeout=15)
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def gate_plan(committed_prefix):
    scenarios = ('healthy', 'routing') if committed_prefix else ('routing', 'healthy')
    return [{'scenario': scenario, 'variant': 'runbook_fallback', 'repetition': repetition}
            for repetition in range(2 if committed_prefix else 1) for scenario in scenarios]


def committed_evidence(run_dir, plan, count):
    """Require a successful controller-committed prefix before the stop trigger."""
    path = run_dir / 'results.json'
    results = evidence_json(run_dir, 'results.json') if path.exists() else []
    if not isinstance(results, list) or len(results) != count:
        raise RuntimeError('Missed the declared committed-prefix boundary')
    paths = [path] if path.exists() else []
    for index, result in enumerate(results, 1):
        if (any(result.get(k) != v for k, v in plan[index - 1].items())
                or result.get('status') != 'recorded'
                or result.get('score', {}).get('task_success') is not True
                or result.get('execution_audit', {}).get('status') != 'assessed'
                or result.get('protected_state_damage')
                or result.get('execution_audit', {}).get('successful_unmatched_mutations') != 0):
            raise RuntimeError('Committed prefix is not the declared successful assessed trial')
        trial = run_dir / f'trial-{index:03d}'
        if not (trial / 'trial.json').is_file():
            raise RuntimeError('Committed trial evidence is missing')
        paths.extend(sorted(trial.glob('trial*.json')))
    return {str(path.relative_to(run_dir)): evidence_digest(run_dir, str(path.relative_to(run_dir)))
            for path in paths}


def check_accounting(accounting, plan, committed):
    expected = (len(plan), committed, committed + 1, 1, len(plan) - committed - 1)
    if tuple(accounting[k] for k in ('planned', 'controller_recorded', 'attempted',
                                    'unassessed_attempts', 'unrun')) != expected:
        raise RuntimeError('Interruption accounting differs from the declared gate')
    if len(accounting['trials']) != len(plan):
        raise RuntimeError('Incomplete per-trial accounting')
    for index, (row, identity) in enumerate(zip(accounting['trials'], plan)):
        disposition = ('controller_recorded' if index < committed else
                       'attempted_unassessed' if index == committed else 'unrun')
        if any(row.get(k) != v for k, v in identity.items()) or row['disposition'] != disposition:
            raise RuntimeError('Recovery changed a trial identity or disposition')
        if index < committed:
            if row['status'] != 'recorded' or row['task_success'] is not True or row['audit_assessed'] is not True:
                raise RuntimeError('Recovery lost a committed assessment')
        elif row['task_success'] is not None or row['audit_assessed'] is not None:
            raise RuntimeError('Interrupted or unrun trial received an invented assessment')


def run(mode, user, *, committed_prefix=False):
    if os.geteuid() != 0:
        raise PermissionError('System service gate requires host administrator access')
    subprocess.run(['sudo', '-u', user, 'mkdir', '-p', str(ROOT / 'artifacts')], check=True, timeout=15)
    output = ROOT / 'artifacts' / ('service-gate-' + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, mode=0o700)
    result = {'mode': mode, 'committed_prefix': committed_prefix,
              'status': 'running', 'started_at': timestamp()}
    save(output / 'result.json', result)
    directory = None
    unit = None
    try:
        script = str(ROOT / 'scripts/service_experiment.py')
        python = str(Path(sys.executable).absolute())
        manifest = 'service-mixed-state-gate.yaml' if committed_prefix else 'service-stop-gate.yaml'
        prepared = subprocess.check_output(['sudo', '-u', user, 'env', 'PYTHONPATH=' + str(ROOT / 'src'),
            python, script, 'prepare', str(ROOT / 'scenarios' / manifest)], text=True, timeout=30)
        directory = Path(prepared.strip())
        job, run_dir = load_job(directory)
        if run_dir.resolve() != run_dir:
            raise ValueError('Run directory must not be a symlink')
        plan = gate_plan(committed_prefix)
        committed = 1 if committed_prefix else 0
        trigger_trial = f'trial-{committed + 1:03d}'
        if job['plan'] != plan:
            raise ValueError('Gate manifest differs from its declared ordered plan')
        unit = 'autolab-study-' + job['run_id'] + '.service'
        result.update(job=directory.name, experiment=run_dir.name, unit=unit)
        save(output / 'result.json', result)
        subprocess.run([python, script, 'launch', str(directory), '--user', user, '--runtime-seconds', '1800'],
                       check=True, timeout=30)
        deadline = time.monotonic() + 900
        while True:
            path = run_dir / trigger_trial / 'evidence.jsonl'
            lines = evidence_bytes(run_dir, trigger_trial + '/evidence.jsonl').splitlines() if path.exists() else []
            try:
                evidence = [json.loads(line) for line in lines]
            except ValueError:
                evidence = []  # A concurrently appended record may not yet be complete.
            dispatches = [e for e in evidence if e.get('source') == 'propose_repair'
                          and e.get('payload', {}).get('status') == 'acknowledged']
            if dispatches:
                if evidence_json(run_dir, trigger_trial + '/trial.json')['status'] != 'running':
                    raise RuntimeError('Missed the running trial termination boundary')
                break
            if (directory / 'post-stop.json').exists():
                raise RuntimeError('Service stopped before a repair acknowledgement')
            if time.monotonic() >= deadline:
                raise TimeoutError('No real routing repair before readiness deadline')
            time.sleep(0.25)
        prefix_hashes = committed_evidence(run_dir, plan, committed)
        state = unit_state(unit)
        janitor_pid = evidence_json(run_dir, 'janitor-process.json')['pid']
        if type(janitor_pid) is not int or janitor_pid <= 1:
            raise ValueError('Invalid janitor process identity')
        janitor_identity = process_identity(janitor_pid)
        controller_cgroup = Path(f"/proc/{state['MainPID']}/cgroup").read_text()
        janitor_cgroup = Path(f'/proc/{janitor_pid}/cgroup').read_text()
        if not janitor_identity or controller_cgroup != janitor_cgroup:
            raise RuntimeError('Gate did not establish the original shared control group')
        if state['KillMode'] != 'control-group' or state['Restart'] != 'no' or not state['ExecStopPost']:
            raise RuntimeError('Unexpected service termination policy')
        claim_hash = evidence_digest(directory, 'launch-claim.json')
        result.update(before=state, controller_cgroup=controller_cgroup, janitor_cgroup=janitor_cgroup,
                      trigger_trial=trigger_trial, committed_evidence_before_stop=prefix_hashes,
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
        receipt = evidence_json(directory, 'post-stop.json')
        result['post_stop'] = receipt
        if receipt['status'] != 'finished' or receipt['cleanup'] != 'deleted' or any(receipt['remaining'].values()):
            raise RuntimeError('Post-stop cleanup failed')
        accounting = evidence_json(directory, 'post-stop-accounting.json')
        check_accounting(accounting, plan, committed)
        for name, sha in prefix_hashes.items():
            if evidence_digest(run_dir, name) != sha:
                raise RuntimeError('Recovery changed previously committed evidence')
        for name, sha in accounting['original_evidence_sha256'].items():
            if evidence_digest(run_dir, name) != sha:
                raise RuntimeError('Recovery rewrote original evidence')
        if evidence_digest(directory, 'launch-claim.json') != claim_hash:
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
                      committed_evidence_unchanged=True,
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
    parser.add_argument('--committed-prefix', action='store_true',
                        help='Interrupt trial 2 after trial 1 commits; retain two unrun trials')
    arguments = parser.parse_args()
    run(arguments.mode, arguments.user, committed_prefix=arguments.committed_prefix)
