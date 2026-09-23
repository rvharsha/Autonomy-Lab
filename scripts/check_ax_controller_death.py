"""Kill an owned AX controller after cluster creation; require detached cleanup."""

import json
import os
import signal
import subprocess
import sys
import time
import uuid

from autonomy_lab.harness import save
from autonomy_lab.janitor import process_identity
from autonomy_lab.kubernetes import ROOT


def main():
    spike = ROOT / '.state/ax-spike'
    output = ROOT / 'artifacts' / ('ax-controller-death-' + uuid.uuid4().hex[:8])
    output.mkdir(mode=0o700)
    with (output / 'controller.log').open('wb') as log:
        process = subprocess.Popen([sys.executable, str(spike / 'launch/execute_ax.py')],
                                   env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'TZ': 'Pacific/Honolulu',
                                        'AX_LAB_INTEGRATION_ENV_FILE': ''},
                                   stdout=log, stderr=log, start_new_session=True)
    result = {'controller_pid': process.pid, 'status': 'running'}
    try:
        deadline = time.monotonic() + 240
        owner = None
        while time.monotonic() < deadline:
            for lease in (spike / 'logs').glob('execution-*/janitor-lease.json'):
                if json.loads(lease.read_text())['controller_pid'] == process.pid:
                    owner = lease.parent
                    state = json.loads((owner / 'result.json').read_text())
                    if any(p['phase'] == 'install' for p in state['phases']) and (owner / 'worker-lease.json').exists():
                        worker = json.loads((owner / 'worker-lease.json').read_text())
                        if worker.get('identity') and process_identity(worker['pid']) == worker['identity']:
                            break
            else:
                owner = None
            if owner is not None:
                break
            if process.poll() is not None:
                raise RuntimeError('AX controller failed before the kill boundary')
            time.sleep(.5)
        if owner is None:
            raise TimeoutError('AX controller did not reach the kill boundary')
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        result.update(controller_exit_code=process.returncode, execution=str(owner.relative_to(ROOT)))
        deadline = time.monotonic() + 180
        while not (owner / 'janitor-result.json').exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('AX janitor did not finish')
            time.sleep(1)
        result['janitor'] = json.loads((owner / 'janitor-result.json').read_text())
        containers = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}'], text=True, timeout=15).splitlines()
        result['remaining_owned_containers'] = [name for name in containers if name.startswith('autonomy-ax-spike')]
        result['runtime_marker_removed'] = not (spike / 'runtime/kubeconfig').exists()
        if result['janitor']['status'] != 'deleted' or result['remaining_owned_containers'] or not result['runtime_marker_removed']:
            raise RuntimeError('AX detached cleanup failed')
        result['status'] = 'passed'
    except BaseException as error:
        result.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        save(output / 'result.json', result)
        print(output, flush=True)


if __name__ == '__main__':
    main()
