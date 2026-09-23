"""Real AX suspension around the same agent protocol and external broker journal."""

import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path

import yaml

from autonomy_lab.harness import save
from autonomy_lab.isolated_runtime import ModelRelay, charge_rpc
from autonomy_lab.rpc import MAX_FRAME_BYTES, error_record


class ResourceLoader(yaml.SafeLoader):
    # Keep the API's nanosecond timestamp strings exact and JSON serializable.
    yaml_implicit_resolvers = {key: [(tag, regex) for tag, regex in values
                                     if tag != 'tag:yaml.org,2002:timestamp']
                               for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()}


class AX:
    def __init__(self, config):
        self.config = config
        self.env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'KUBECONFIG': config['kubeconfig'],
                    'XDG_CONFIG_HOME': config['config_home']}
        self.prefix = [config['binary'], '--server', config['server'], '--context', 'kind-autonomy-ax-spike',
                       '--atespace', 'autonomy-agents']

    def call(self, *args, timeout=40):
        result = subprocess.run([*self.prefix, *args], env=self.env, text=True, capture_output=True, timeout=timeout)
        if result.returncode:
            if self.config.get('log_path'):
                with Path(self.config['log_path']).open('a') as log:
                    log.write(json.dumps({'command': args[0], 'returncode': result.returncode,
                                          'stderr': result.stderr[:65536]}) + '\n')
            raise RuntimeError('AX command failed: ' + args[0])
        return result.stdout

    def python(self, task, code):
        # The debug transport is controller-owned, but public mailbox access
        # needs no root filesystem privileges. Isolated Python startup also
        # prevents workspace files from becoming root startup imports.
        drop = "import os;os.setgroups([]);os.setgid(10001);os.setuid(10001);"
        return self.call('ssh', task, '--', 'python3', '-I', '-c', drop + code)

    def write(self, task, name, value):
        if not re.fullmatch(r'[a-z0-9.-]+', name):
            raise ValueError('Invalid mailbox filename')
        data = json.dumps(value, allow_nan=False).encode()
        # Guest Exec argv is deliberately bounded by the upstream API. Chunk
        # uploads stay below 4 KiB per argument and publish only the complete file.
        if len(data) > MAX_FRAME_BYTES:
            raise ValueError('Mailbox frame too large')
        temporary = '/workspace/rpc/' + name + '.upload'
        self.python(task, f"from pathlib import Path;Path({temporary!r}).write_bytes(b'')")
        for offset in range(0, len(data), 1800):
            encoded = base64.b64encode(data[offset:offset + 1800]).decode()
            self.python(task, f"import base64;f=open({temporary!r},'ab');f.write(base64.b64decode({encoded!r}));f.close()")
        self.python(task, f"import os;f=open({temporary!r},'rb');os.fsync(f.fileno());f.close();os.replace({temporary!r},{('/workspace/rpc/' + name)!r})")
        self.python(task, "import os;fd=os.open('/workspace/rpc',os.O_RDONLY);os.fsync(fd);os.close(fd)")

    def wait(self, task, phase):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            resource = yaml.load(self.call('get', 'task', task), Loader=ResourceLoader)
            state = resource.get('status') or {}
            if state.get('phase') == phase and (phase != 'Running' or any(
                c.get('type') == 'Ready' and c.get('status') == 'True' for c in (state.get('conditions') or []))):
                return resource
            time.sleep(1)
        raise TimeoutError('AX readiness deadline')


def run_ax_agent(client, toolbox, state_path, *, ax_config, timeout=900, **options):
    try:
        return _run_ax_agent(client, toolbox, state_path, ax_config=ax_config, timeout=timeout, **options)
    except BaseException:
        # Export surviving guest evidence before the outer controller cleans the
        # cluster. The host provider/broker journals already live outside AX.
        path = Path(state_path)
        session = path.parent / 'ax-session.json'
        if session.exists():
            ax = AX({**ax_config, 'log_path': str(path.parent / 'ax-cli.jsonl')})
            task = json.loads(session.read_text())['task']
            failures = []
            for name in ['agent-state.json', 'agent-boots.json', 'boundary-checks.json', 'agent-error.json']:
                try:
                    value = json.loads(ax.python(task, "import json;from pathlib import Path;p=Path('/workspace/" + name + "');assert not p.exists() or p.stat().st_size<=8388608;print(p.read_text() if p.exists() else 'null')"))
                    if value is not None:
                        save(path.parent / name, value)
                except Exception as error:
                    failures.append({'file': name, 'error_type': type(error).__name__})
            if failures:
                save(path.parent / 'ax-export-errors.json', failures)
        raise


def _run_ax_agent(client, toolbox, state_path, *, ax_config, timeout=900, **options):
    state_path = Path(state_path)
    ax = AX({**ax_config, 'log_path': str(state_path.parent / 'ax-cli.jsonl')})
    session = state_path.parent / 'ax-session.json'
    task = 'agent-' + toolbox.run_id[:20]
    config = {'run_id': toolbox.run_id, 'model': client.model, 'declarations': toolbox.declarations(),
              'terminal': toolbox.terminal, 'agent_options': options}
    if not session.exists():
        manifests = [
            {'apiVersion': 'ax.io/v1alpha1', 'kind': 'Workspace', 'metadata': {'name': task, 'atespace': 'autonomy-agents'}, 'spec': {}},
            {'apiVersion': 'ax.io/v1alpha1', 'kind': 'Gateway', 'metadata': {'name': 'closed', 'atespace': 'autonomy-agents'},
             'spec': {'egress': {'allowlist': {'hosts': []}}}},
            {'apiVersion': 'ax.io/v1alpha1', 'kind': 'Task', 'metadata': {'name': task, 'atespace': 'autonomy-agents'},
             'spec': {'image': ax_config['image'], 'command': ['python3', '-I', '-c',
                 "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,'/app');from autonomy_lab.mailbox import main;main()"],
                      'workspaces': [{'name': task, 'path': '/workspace'}], 'gateway': {'name': 'closed'}, 'debug': True}},
        ]
        path = state_path.parent / 'ax-task.yaml'
        path.write_text(yaml.safe_dump_all(manifests))
        ax.call('apply', '-f', str(path))
        resource = ax.wait(task, 'Running')
        save(session, {'task': task, 'initial': resource, 'resumes': []})
        deadline = time.monotonic() + 30
        while True:
            status = json.loads(ax.python(task, "import json;from pathlib import Path;p=Path('/workspace/agent-error.json');print(json.dumps({'ready':Path('/workspace/rpc').is_dir(),'error':json.loads(p.read_text()) if p.exists() else None}))"))
            if status['error']:
                save(state_path.parent / 'ax-agent-error.json', status['error'])
                raise RuntimeError('AX agent reported an error')
            if status['ready']:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('AX mailbox directory deadline')
            time.sleep(.2)
        ax.write(task, 'config.json', config)
    else:
        record = json.loads(session.read_text())
        if any(item.get('state') != 'complete' for item in record['resumes']):
            return {'status': 'indeterminate', 'reason': 'incomplete_AX_transition_no_automatic_retry'}
        ax.write(task, 'config.json', config)
        ax.python(task, "from pathlib import Path;Path('/workspace/rpc/result.json').unlink(missing_ok=True)")
        record['resumes'].append({'state': 'started'})
        save(session, record)
        ax.call('suspend', 'task', task)
        suspended = ax.wait(task, 'Suspended')
        record['resumes'][-1].update(state='suspended', suspended=suspended)
        save(session, record)
        ax.call('resume', 'task', task)
        resumed = ax.wait(task, 'Running')
        record['resumes'][-1].update(state='complete', resumed=resumed)
        save(session, record)
    relay = ModelRelay(client, state_path.parent / 'model-relay.json', options)
    deadline = time.monotonic() + timeout
    expected_boots = len(json.loads(session.read_text())['resumes']) + 1
    read = f"expected_boots={expected_boots}\n" + """import json
from pathlib import Path
p=Path('/workspace/rpc');r=p/'result.json'
error=Path('/workspace/agent-error.json')
if error.exists():
 print(json.dumps({'agent_error':json.loads(error.read_text())}))
elif r.exists():
 print(r.read_text())
else:
 b=Path('/workspace/agent-boots.json')
 boots=json.loads(b.read_text()) if b.exists() else []
 if len(boots) < expected_boots:
  print('{}')
 else:
  assert len(boots)==expected_boots
  boot=boots[-1]['boot_id']
  pending=[f for f in sorted(p.glob('*.request')) if not f.with_suffix('.response').exists()
           and f.stat().st_size <= 8388608 and json.loads(f.read_text()).get('boot_id')==boot]
  if pending:
   f=pending[0];assert f.stat().st_size <= 8388608; print(json.dumps({'file':f.stem,'request':json.loads(f.read_text())}))
  else: print('{}')
"""
    while time.monotonic() < deadline:
        message = json.loads(ax.python(task, read))
        if 'agent_error' in message:
            save(state_path.parent / 'ax-agent-error.json', message['agent_error'])
            raise RuntimeError('AX agent reported an error')
        if 'result' in message:
            checkpoint = ax.python(task, "from pathlib import Path;p=Path('/workspace/agent-state.json');assert p.stat().st_size<=8388608;print(p.read_text())")
            checkpoint = json.loads(checkpoint)
            boots = json.loads(ax.python(task, "from pathlib import Path;print(Path('/workspace/agent-boots.json').read_text())"))
            record = json.loads(session.read_text())
            record['boots'] = boots
            record['boundary_checks'] = json.loads(ax.python(task, "from pathlib import Path;print(Path('/workspace/boundary-checks.json').read_text())"))
            if not all(record['boundary_checks'].values()):
                raise ValueError('AX process isolation check failed')
            if len(boots) != len(record['resumes']) + 1 or len({b['boot_id'] for b in boots}) != len(boots):
                raise ValueError('AX did not reconstruct exactly one fresh agent process')
            if any(b['uid'] == 0 for b in boots):
                raise ValueError('AX agent process retained root identity')
            save(state_path, checkpoint)
            save(session, record)
            return message['result']
        if 'request' not in message:
            time.sleep(.3)
            continue
        request = message['request']
        identity = request['id']
        if not re.fullmatch(r'[a-f0-9]{32}', identity) or message.get('file') != identity:
            raise ValueError('Invalid AX RPC identity')
        charge_rpc(state_path.parent / 'rpc-budget.json', options['max_turns'] * 12)
        try:
            if request['method'] == 'tool':
                args = request['arguments']
                result = toolbox.call(args['name'], args['args'])
                value = {'observation': result, 'terminal': toolbox.terminal}
            elif request['method'] in {'generate', 'count_tokens'}:
                value = relay.call(request['method'], request['arguments'])
            else:
                raise ValueError('Unknown AX RPC method')
            response = {'id': identity, 'result': value}
        except Exception as error:
            response = {'id': identity, 'error': error_record(error)}
        ax.write(task, identity + '.response', response)
    raise TimeoutError('AX agent deadline')
