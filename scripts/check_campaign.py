"""Real restart acceptance: freeze schedule, retain failed runs, never reset workload."""

import hashlib
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from autonomy_lab.campaign import read, spawn_worker, stop_worker
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import save
from autonomy_lab.janitor import cleanup, process_identity
from autonomy_lab.kubernetes import ROOT


def await_file(path, deadline):
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Missing {path.name}')
        time.sleep(0.1)
    return read(path)


def wait_until(epoch):
    while time.time() < epoch:
        time.sleep(min(0.25, epoch - time.time()))


def finalize_gate(owner, children, directory, gate, result):
    """Cleanup failures must not discard the original failed experiment receipt."""
    errors = []

    def attempt(stage, action):
        try:
            action()
        except Exception as error:
            errors.append({'stage': stage, 'error_type': type(error).__name__})

    def stop_owner():
        if owner.poll() is None:
            os.killpg(owner.pid, signal.SIGKILL)
        owner.wait(timeout=10)

    attempt('stop_owner', stop_owner)
    for workspace, process in children:
        attempt('stop_worker', lambda: stop_worker(workspace))
        attempt('reap_worker', lambda: process.wait(timeout=10))

    def clean_cluster():
        path = directory / 'environment.json'
        if path.exists() and read(path)['status'] != 'deleted':
            result['emergency_cleanup'] = cleanup(directory, {'cluster': read(path)['cluster']})

    attempt('cleanup', clean_cluster)
    if errors:
        result.update(status='failed', cleanup_errors=errors)
    result['finished_at'] = time.time()
    save(gate / 'result.json', result)
    print(gate, flush=True)
    if errors:
        raise RuntimeError('Gate finalization failed; original result and cleanup errors retained')


def run():
    base = ROOT / 'artifacts'
    base.mkdir(exist_ok=True)
    gate = base / ('campaign-gate-' + uuid.uuid4().hex[:8])
    gate.mkdir(mode=0o700)
    directory = gate / 'campaign'
    declaration = {'stop_offset_seconds': 30, 'restart_offset_seconds': 60,
                   'minimum_complete_downtime_samples': 2,
                   'minimum_successful_episodes_per_generation': 1,
                   'contract_sha256': hashlib.sha256((ROOT / 'scenarios/campaign-restart.json').read_bytes()).hexdigest(),
                   'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    save(gate / 'declaration.json', declaration)
    result = {'status': 'failed', 'started_at': time.time(), 'declaration': declaration}
    children = []
    with (gate / 'owner.log').open('ab') as log:
        owner = subprocess.Popen([sys.executable, '-m', 'autonomy_lab.campaign', 'own',
                                  str(ROOT / 'scenarios/campaign-restart.json'), str(directory)],
                                 stdout=log, stderr=log, start_new_session=True,
                                 env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
    try:
        window = await_file(directory / 'window.json', time.monotonic() + 900)
        initial = next((directory / 'workers').glob('operator-*'))
        duplicate, process = spawn_worker(directory, 'operator')
        children.append((duplicate, process))
        if process.wait(timeout=30) != 1 or read(duplicate / 'failed.json')['error_type'] != 'BlockingIOError':
            raise AssertionError('Concurrent operator was not refused by the ownership lock')
        if (duplicate / 'ready.json').exists():
            raise AssertionError('Concurrent operator acquired ownership')
        wait_until(window['start'] + declaration['stop_offset_seconds'])
        # The owner remains alive; only this registered operator group is killed.
        stop_worker(initial)
        lease = read(initial / 'worker-lease.json')
        deadline = time.monotonic() + 10
        while process_identity(lease['pid']) == lease['identity']:
            if time.monotonic() >= deadline:
                raise TimeoutError('Original operator did not terminate')
            time.sleep(0.1)
        stopped = time.time()
        save(gate / 'operator-stopped.json', {'at': stopped, 'worker': initial.name})
        wait_until(window['start'] + declaration['restart_offset_seconds'])
        resumed, process = spawn_worker(directory, 'operator')
        children.append((resumed, process))
        ready = await_file(resumed / 'ready.json', time.monotonic() + 45)
        downtime = ready['at'] - stopped
        result.update(operator_stopped_at=stopped, operator_resumed_at=ready['at'], downtime_seconds=downtime,
                      initial_operator=initial.name, resumed_operator=resumed.name, concurrent_operator_refused=True)
        save(gate / 'result.json', result)
        owner.wait(timeout=max(1, window['end'] - time.time()) + 180)
        if owner.returncode != 0:
            raise RuntimeError('Campaign owner failed')
        first = scorecard(directory)
        save(gate / 'scorecard-a.json', first)
        save(gate / 'scorecard-b.json', scorecard(directory))
        if (gate / 'scorecard-a.json').read_bytes() != (gate / 'scorecard-b.json').read_bytes():
            raise AssertionError('Export is not reproducible')
        samples = first['samples']
        during = [row for row in samples if row.get('started_at', 0) >= stopped
                  and row.get('finished_at', float('inf')) <= ready['at']]
        if downtime > first['contract']['max_restart_downtime_seconds']:
            raise AssertionError('Operator downtime exceeded contract')
        if len(during) < declaration['minimum_complete_downtime_samples']:
            raise AssertionError('Insufficient observations wholly inside operator downtime')
        if any(row['verdict'] != 'verified_success' for row in samples):
            raise AssertionError('Timeline includes failed, missing, late or indeterminate samples')
        if not first['identities_unchanged'] or len(first['identities_before']) < 11:
            raise AssertionError('Workload resources changed across operator restart')
        if first['operations'] or first['dispatch_budget_reserved']:
            raise AssertionError('Healthy campaign issued a repair')
        for name in (initial.name, resumed.name):
            worker = next(row for row in first['workers'] if row['id'] == name)
            healthy = [row for row in worker['episodes'] if row['outcome'] is not None
                       and row['outcome']['claim'].get('outcome') == 'healthy']
            if len(healthy) < declaration['minimum_successful_episodes_per_generation']:
                raise AssertionError('Operator generation did not execute verified healthy episodes')
        if first['cleanup']['status'] != 'deleted' or not first['owner_finished']:
            raise AssertionError('Owner did not finish and delete owned resources')
        result.update(status='passed', complete_downtime_samples=len(during),
                      unchanged_resources=len(first['identities_before']), export_identical=True,
                      scorecard_sha256=hashlib.sha256((gate / 'scorecard-a.json').read_bytes()).hexdigest())
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        # Also clean after a checker failure; preserve the original failed receipt.
        finalize_gate(owner, children, directory, gate, result)
    return gate


if __name__ == '__main__':
    run()
