"""AX durable mailbox: public RPC requests only, never infrastructure credentials."""

import errno
import json
import os
import platform
import socket
import time
import uuid
from pathlib import Path

from autonomy_lab.rpc import MAX_FRAME_BYTES, RemoteError

DIRECTORY = Path('/workspace/rpc')
ERROR_PHASE = 'startup'


def deny_network():
    """Irreversible kernel filter for the ARM64 AX decision process and children."""
    import ctypes

    if platform.machine() != 'aarch64':
        raise RuntimeError('AX process isolation requires the pinned Linux ARM64 runtime')
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(Filter))]
    # Validate the syscall ABI, then deny all socket operations and io_uring
    # (which could otherwise submit network operations outside these syscalls).
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xC00000B7), (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0)]
    for number in [117, *range(198, 213), 242, 243, 269, 270, 271, 417, 425]:
        instructions.extend([(0x15, 0, 1, number), (0x06, 0, 0, 0x00050001)])
    instructions.append((0x06, 0, 0, 0x7FFF0000))
    filters = (Filter * len(instructions))(*(Filter(*row) for row in instructions))
    program = Program(len(instructions), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise OSError(ctypes.get_errno(), 'Cannot enforce AX process network isolation')


def boundary_checks():
    checks = {'non_root': os.getuid() != 0}
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            with socket.socket(family, socket.SOCK_STREAM):
                pass
            checks['socket_' + str(family)] = False
        except PermissionError:
            checks['socket_' + str(family)] = True
    for name, path in {'code': '/app/autonomy_lab/agent.py', 'root': '/forbidden-write'}.items():
        try:
            with open(path, 'a'):
                pass
            checks[name + '_write_denied'] = False
        except OSError as error:
            checks[name + '_write_denied'] = error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}
    for name, path in {'credentials': '/var/run/secrets/kubernetes.io/serviceaccount/token',
                       'docker': '/var/run/docker.sock', 'fixtures': '/app/fixtures/expectations.json'}.items():
        checks[name + '_absent'] = not Path(path).exists()
    checks['credentials_absent'] = checks['credentials_absent'] and not any(os.environ.get(key) for key in (
        'GOOGLE_API_KEY', 'GEMINI_API_KEY', 'ANTHROPIC_API_KEY', 'KUBECONFIG'))
    status = Path('/proc/self/status').read_text()
    checks['no_capabilities'] = 'CapEff:\t0000000000000000' in status
    checks['no_permitted_capabilities'] = 'CapPrm:\t0000000000000000' in status
    checks['no_privilege_escalation'] = 'NoNewPrivs:\t1' in status
    try:
        os.setuid(0)
        checks['root_escalation_denied'] = False
    except PermissionError:
        checks['root_escalation_denied'] = True
    return checks


def publish(path, value):
    data = json.dumps(value, allow_nan=False).encode()
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError('Mailbox frame too large')
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class MailboxChannel:
    def __init__(self, boot_id):
        self.boot_id = boot_id

    def call(self, method, **arguments):
        identity = uuid.uuid4().hex
        publish(DIRECTORY / (identity + '.request'), {'id': identity, 'boot_id': self.boot_id,
                                                    'method': method, 'arguments': arguments})
        response = DIRECTORY / (identity + '.response')
        deadline = time.monotonic() + 180
        while not response.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('Mailbox response deadline')
            time.sleep(.1)
        if response.stat().st_size > MAX_FRAME_BYTES:
            raise ValueError('Mailbox response too large')
        value = json.loads(response.read_text())
        if value.get('id') != identity:
            raise ValueError('Mailbox response identity mismatch')
        if 'error' in value:
            raise RemoteError(value['error'])
        return value['result']


def _main():
    global ERROR_PHASE
    # The AX runner owns its debug transport. The decision process drops to an
    # unprivileged UID before loading config or making any model/tool request.
    from autonomy_lab.agent import run_agent
    from autonomy_lab.isolated_agent import Model, Toolbox

    if os.getuid() == 0:
        # Substrate's private overlay and durable-volume roots start at 0700.
        # Permit traversal before dropping UID; neither is made world writable.
        os.chmod('/', 0o755)
        workspace = Path('/workspace')
        workspace.mkdir(exist_ok=True)
        status = workspace.stat()
        if status.st_uid == 0:
            workspace.chmod(0o755)
            os.chown(workspace, 10001, 10001)
        elif (status.st_uid, status.st_gid, status.st_mode & 0o777) != (10001, 10001, 0o755):
            raise PermissionError('Unexpected durable workspace ownership or mode')
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    deny_network()
    DIRECTORY.mkdir(mode=0o700, exist_ok=True)
    checks = boundary_checks()
    publish(Path('/workspace/boundary-checks.json'), checks)
    if not all(checks.values()):
        raise RuntimeError('AX process boundary checks failed')
    config_path = DIRECTORY / 'config.json'
    while not config_path.exists():
        time.sleep(.1)
    config = json.loads(config_path.read_text())
    boots_path = Path('/workspace/agent-boots.json')
    boots = json.loads(boots_path.read_text()) if boots_path.exists() else []
    boots.append({'boot_id': uuid.uuid4().hex, 'pid': os.getpid(), 'uid': os.getuid(), 'started_at': time.time()})
    publish(boots_path, boots)
    channel = MailboxChannel(boots[-1]['boot_id'])
    ERROR_PHASE = 'execution'
    state = run_agent(Model(channel, config['model']), Toolbox(channel, config),
                      Path('/workspace/agent-state.json'), **config['agent_options'])
    publish(DIRECTORY / 'result.json', {'result': {key: state.get(key) for key in (
        'status', 'reason', 'usage', 'terminal', 'resume_count', 'error_type', 'provider_status_code')}})
    while True:
        time.sleep(10)


def main():
    try:
        _main()
    except BaseException as error:
        record = {'phase': ERROR_PHASE, 'error_type': type(error).__name__, 'errno': getattr(error, 'errno', None)}
        print(json.dumps({'agent_error': record}), flush=True)
        try:
            publish(Path('/workspace/agent-error.json'), record)
        except OSError:
            pass  # Preserve the original error and stdout evidence if the filesystem failed.
        raise


if __name__ == '__main__':
    main()
