"""Real executor checks on authored inputs; never empirical service outcomes."""

import sys
from pathlib import Path

from autonomy_lab.harness import save
from autonomy_lab.procedures import Refused, require

from .runtime import image, invoke


def check(destination):
    results = []
    image_id = image()
    observation = {'step': 0, 'memory': {}, 'previous': None}
    probes = {
        'valid': 'def step(o): return {"action": 4, "memory": {"seen": o["step"]}}',
        'compact_memory': 'def step(o): return {"action":4,"memory":{"v":[0]*8000,"padding":"x"*364}}',
        'root_write': 'def step(o):\n open("/escape", "w").write("x")\n return {"action":4,"memory":{}}',
        'network': 'import socket\ndef step(o):\n socket.create_connection(("1.1.1.1", 443), timeout=1)\n return {"action":4,"memory":{}}',
        'loop': 'while True: pass',
        'stdout_flood': 'print("x" * 40000)\ndef step(o): return {"action":4,"memory":{}}',
        'oversized_memory': 'def step(o): return {"action":4,"memory":{"x":"a"*17000}}',
        'invalid_action': 'def step(o): return {"action":True,"memory":{}}',
        'missing_step': 'x = 4',
    }
    try:
        source = 'def step(o): return {"action":1+(hash("x")%16),"memory":{}}'
        first, second = (invoke(source, observation, image_id) for _ in range(2))
        require(first['result'] == second['result'] and first['stdout_sha256'] == second['stdout_sha256'], 'Hash seed changed between containers')
        results.append({'probe': 'hash_replay', 'reproduced': True})
        for name, source in probes.items():
            try:
                result = invoke(source, observation, image_id)
            except Exception as error:
                results.append({'probe': name, 'rejected': True, 'error_type': type(error).__name__})
                require(name not in ('valid', 'compact_memory') and isinstance(error, Refused), 'Executor infrastructure or valid decision failed')
            else:
                results.append({'probe': name, 'rejected': False, 'result': result['result']})
                require(name in ('valid', 'compact_memory'), 'Boundary probe unexpectedly accepted')
    finally:
        save(destination, {'kind': 'authored_executor_checks_not_service_outcomes', 'image': image_id, 'probes': results})


if __name__ == '__main__':
    check(Path(sys.argv[1]))
