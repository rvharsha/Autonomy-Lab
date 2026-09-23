"""Real Gemini agent in AX, with host-owned broker/verifier and Kubernetes app."""

import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

root = Path(os.environ['SPIKE_ROOT'])
project = root.parents[1]
sys.path.insert(0, str(project / 'src'))
from autonomy_lab.environment import image_tag, manifests  # noqa: E402
from autonomy_lab.experiments import run_trial  # noqa: E402
from autonomy_lab.harness import save  # noqa: E402
from autonomy_lab.kubernetes import Kubernetes, command  # noqa: E402

out = root / 'logs' / ('ax-agent-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
out.mkdir(mode=0o700)
kube = Kubernetes(root / 'runtime/kubeconfig', 'autonomy-ax-spike')
tools = json.loads((project / 'infra/toolchain.json').read_text())
image = image_tag()
command(['docker', 'build', '--build-arg', f"PYTHON_IMAGE={tools['python_image']}", '-t', image, str(project)], timeout=420)
command([str(project / '.tools/kind'), 'load', 'docker-image', '--name', 'autonomy-ax-spike', image], timeout=180)
kube.call('apply', '-f', '-', input=yaml.safe_dump_all(manifests(image, tools['postgres_image'])))
for name in ['postgres', 'inventory', 'quote']:
    kube.call('rollout', 'status', f'deployment/{name}', '--timeout=120s')
forward_log = out / 'server-forward.log'
with forward_log.open('w') as log:
    forward = subprocess.Popen(kube.args('-n', 'ax-system', 'port-forward', '--address', '127.0.0.1', 'svc/ax-server', ':8080'),
                               stdout=log, stderr=subprocess.STDOUT)
try:
    deadline = time.monotonic() + 30
    while True:
        match = re.search(r'Forwarding from 127\.0\.0\.1:(\d+) ->', forward_log.read_text())
        if match:
            break
        if forward.poll() is not None or time.monotonic() >= deadline:
            raise TimeoutError('AX server forward deadline')
        time.sleep(.2)
    config = {
        'runtime': 'ax', 'model': 'gemini-3.8-flash', 'max_turns': 12, 'max_tokens': 32000,
        'max_output_tokens': 2048, 'window_seconds': 30, 'trial_timeout_seconds': 750,
        'audit_directory': (root / 'runtime/audit-directory.txt').read_text(),
        'repetitions': 1, 'scenarios': ['lost_ack'], 'variants': ['basic'], 'expected_behavior': {'lost_ack': 'repair'},
        'ax_config': {'binary': str(root / 'tools/bin/ax'), 'kubeconfig': str(kube.kubeconfig),
                      'server': f'http://127.0.0.1:{match[1]}', 'config_home': str(root / 'runtime/config'),
                      'image': json.loads((root / 'runtime/ax-images.json').read_text())['ax-task-runner']},
    }
    save(out / 'manifest.json', config)
    trial = run_trial(kube, out / 'trial', 'lost_ack', 'basic', config,
                      env_file=Path(os.environ['AX_LAB_INTEGRATION_ENV_FILE']))
    save(out / 'result.json', trial)
    if trial['status'] != 'recorded' or not trial['score']['task_success'] or not trial['interruption_triggered']:
        raise RuntimeError('AX live-agent gate did not pass')
finally:
    forward.terminate()
    try:
        forward.wait(timeout=5)
    except subprocess.TimeoutExpired:
        forward.kill()
        forward.wait(timeout=5)
    print(out, flush=True)
