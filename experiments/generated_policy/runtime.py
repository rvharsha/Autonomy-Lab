"""The candidate executes only in a fresh, credential-free Docker container."""

import hashlib
import json
import os
import select
import subprocess
import sys
import time
import uuid

from autonomy_lab.kubernetes import ROOT, command
from autonomy_lab.procedures import require
from autonomy_lab.rpc import PipeWriter

from .protocol import MEMORY_LIMIT, OUTPUT_LIMIT, POLICY_SECONDS, SOURCE_LIMIT

# These are limits inside the container, not a Python-language sandbox. The
# controller independently limits stdout, elapsed time, action and returned state.
WRAPPER = '''import json, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
resource.setrlimit(resource.RLIMIT_AS, (128*1024*1024, 128*1024*1024))
request = json.loads(sys.stdin.buffer.readline(65537))
namespace = {}
exec(compile(request["source"], "candidate.py", "exec"), namespace)
result = namespace["step"](request["observation"])
sys.stdout.write(json.dumps(result, allow_nan=False, separators=(",", ":")))
'''


def source_for(arm, candidate):
    if arm in ('candidate', 'erased'):
        return candidate
    if arm == 'fixed-4':
        return 'def step(observation):\n    return {"action": 4, "memory": {}}\n'
    require(arm == 'legacy', 'Unknown policy')
    # Exact unchanged PR29 implementation, with an interface-only adapter.
    return (ROOT / 'experiments/experience_learning/policy.py').read_text() + '''
def step(observation):
    state = observation["memory"] or initial()
    if observation["previous"] is not None:
        last = observation["previous"]
        state = learn(state, last["action"], last["feedback"])
    return {"action": choose("retained", state), "memory": state}
'''


def validate_result(value):
    require(type(value) is dict and set(value) == {'action', 'memory'}, 'Invalid result schema')
    require(type(value['action']) is int and 1 <= value['action'] <= 16, 'Invalid concurrency')
    require(type(value['memory']) is dict, 'Memory must be an object')
    require(len(json.dumps(value['memory'], allow_nan=False, separators=(',', ':')).encode()) <= MEMORY_LIMIT, 'State too large')
    return value


def image():
    pinned = json.loads((ROOT / 'infra/toolchain.json').read_text())['python_image']
    command(['docker', 'pull', pinned], timeout=240)
    return command(['docker', 'image', 'inspect', '--format', '{{.Id}}', pinned]).strip()


def container_args(image_id, name):
    require(len(image_id) == 71 and image_id.startswith('sha256:'), 'Immutable image required')
    return ['docker', 'run', '--rm', '--name', name, '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=16',
            '--memory=256m', '--cpus=1', '--user=10001:10001', '--log-driver=none',
            '--env=PYTHONHASHSEED=0', '-i', image_id, 'python', '-s', '-B', '-P', '-c', WRAPPER]


def invoke(source, observation, image_id):
    require(type(source) is str and len(source.encode()) <= SOURCE_LIMIT, 'Invalid source size')
    payload = {'source': source, 'observation': observation}
    require(len(json.dumps(payload).encode()) < 65536, 'Input too large')
    name = 'autolab-policy-' + uuid.uuid4().hex[:16]
    started = time.monotonic()
    process = subprocess.Popen(container_args(image_id, name), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    output = bytearray()
    try:
        deadline = started + POLICY_SECONDS
        PipeWriter(process.stdin).write(payload, deadline)
        process.stdin.close()
        fd = process.stdout.fileno()
        os.set_blocking(fd, False)
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and select.select([fd], [], [], remaining)[0], 'Policy time limit')
            chunk = os.read(fd, OUTPUT_LIMIT + 1 - len(output))
            if not chunk:
                break
            output.extend(chunk)
            require(len(output) <= OUTPUT_LIMIT, 'Policy output limit')
        require(process.wait(timeout=max(.001, deadline - time.monotonic())) == 0, 'Policy failed')
        result = validate_result(json.loads(output))
        require(time.monotonic() - started <= POLICY_SECONDS, 'Policy time limit')
        return {'result': result, 'seconds': time.monotonic() - started,
                'stdout_sha256': hashlib.sha256(output).hexdigest()}
    finally:
        # Preserve the original failure type if infrastructure cleanup also fails.
        primary = sys.exc_info()[1]
        cleanup_error = None
        if not process.stdin.closed:
            process.stdin.close()
        try:
            removed = subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, timeout=30)
            require(removed.returncode == 0 or b'No such container' in removed.stderr,
                    'Policy container cleanup uncertain')
        except Exception as error:
            cleanup_error = error
        finally:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            except Exception as error:
                cleanup_error = error
            process.stdout.close()
        if cleanup_error is not None:
            error = RuntimeError('Policy container cleanup uncertain')
            error.policy_error_type = type(primary).__name__ if primary else None
            error.cleanup_error_type = type(cleanup_error).__name__
            raise error from primary
