"""Bounded persistent workload with separately restartable trusted workers.

This first slice uses the existing deterministic runbook, not an untrusted model
actor. Processes share a trusted host account; this is lifecycle separation,
not a new security sandbox. No trial reset is used inside a campaign.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autonomy_lab.broker import ActionBroker, BrokerPolicy
from autonomy_lab.environment import provision, service_identity
from autonomy_lab.harness import save
from autonomy_lab.janitor import cleanup, process_identity
from autonomy_lab.kubernetes import ROOT, Kubernetes
from autonomy_lab.runbook import run as runbook
from autonomy_lab.toolbox import ObservationTools
from autonomy_lab.verifier import verify

Seconds = Annotated[int, Field(strict=True, ge=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    duration_seconds: Annotated[int, Field(strict=True, ge=60, le=900)]
    sample_interval_seconds: Seconds
    sample_window_seconds: Seconds
    sample_lateness_seconds: Seconds
    request_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=5)]
    operator_interval_seconds: Seconds
    max_operator_starts: Annotated[int, Field(strict=True, ge=1, le=10)]
    max_dispatches: Annotated[int, Field(strict=True, ge=0, le=10)]
    max_restart_downtime_seconds: Seconds
    # Lease includes provisioning and bounds this first local-process campaign.
    lease_seconds: Annotated[int, Field(strict=True, ge=1200, le=3600)]

    @model_validator(mode='after')
    def valid_schedule(self):
        if (self.duration_seconds % self.sample_interval_seconds
                or self.sample_window_seconds + self.sample_lateness_seconds >= self.sample_interval_seconds
                or self.max_restart_downtime_seconds >= self.duration_seconds
                or self.operator_interval_seconds >= self.duration_seconds):
            raise ValueError('Invalid campaign schedule')
        return self


def read(path):
    return json.loads(Path(path).read_text())


@contextmanager
def exclusive(path):
    # Descriptors are non-inheritable: kubectl must not retain the operator lock.
    with Path(path).open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def owner_alive(directory):
    owner = read(directory / 'owner.json')
    if time.time() >= owner['expires_at'] or process_identity(owner['pid']) != owner['identity']:
        raise RuntimeError('Campaign owner absent or lease expired')
    if (directory / 'ending.json').exists():
        raise RuntimeError('Campaign is ending')


def active(directory):
    owner_alive(directory)
    window = read(directory / 'window.json')
    if not window['start'] <= time.time() < window['end']:
        raise RuntimeError('Outside the frozen measurement window')


def identities(kube):
    resources = json.loads(kube.call('get', 'service,deployment,pvc,pod', '-o', 'json'))
    resources['items'].append(json.loads(kube.call('get', 'namespace/autonomy-lab', '-o', 'json')))
    return {f"{item['kind']}/{item['metadata']['name']}": item['metadata']['uid'] for item in resources['items']}


def spawn_worker(directory, role):
    owner_alive(directory)
    contract = Contract.model_validate(read(directory / 'contract.json'))
    with exclusive(directory / f'{role}-launch.lock'):
        existing = list((directory / 'workers').glob(role + '-*'))
        limit = contract.max_operator_starts if role == 'operator' else 1
        if len(existing) >= limit:
            raise RuntimeError('Worker start budget exhausted')
        workspace = directory / 'workers' / (role + '-' + uuid.uuid4().hex)
        workspace.mkdir(mode=0o700)
        save(workspace / 'attempt.json', {'role': role, 'started_at': time.time()})
        with (workspace / 'worker.log').open('ab') as log:
            process = subprocess.Popen(
                [sys.executable, '-m', 'autonomy_lab.campaign', 'worker', str(directory), str(workspace), role],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'src')})
        try:
            identity = process_identity(process.pid)
            if not identity:
                raise RuntimeError('Cannot establish worker identity')
            save(workspace / 'worker-lease.json', {'pid': process.pid, 'identity': identity})
        except BaseException:
            process.kill()
            process.wait()
            raise
    return workspace, process


def stop_worker(workspace):
    if not (workspace / 'worker-lease.json').exists():
        return
    lease = read(workspace / 'worker-lease.json')
    pid = lease['pid']
    try:
        if process_identity(pid) == lease['identity'] and os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@contextmanager
def connections(directory):
    environment = read(directory / 'environment.json')
    kube = Kubernetes(directory / 'kubeconfig', environment['cluster'])
    verifier = Kubernetes(directory / 'verifier-kubeconfig', environment['cluster'])
    with ExitStack() as stack:
        quote = stack.enter_context(kube.forward('deployment/quote', 8080))
        inventory = stack.enter_context(kube.forward('deployment/inventory', 8080))
        database = stack.enter_context(kube.forward('deployment/postgres', 5432))
        yield kube, {
            'quote_url': f'http://127.0.0.1:{quote}',
            'inventory_control_url': f'http://127.0.0.1:{inventory}',
            'database_url': f'postgresql://verifier_reader:verifier-test-only@127.0.0.1:{database}/lab',
            'service_reader': lambda: verifier.get_service(kube.namespace, 'inventory'),
        }


def operation_rows(directory):
    path = directory / 'operations.sqlite'
    if not path.exists():
        return []
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute('SELECT * FROM operations ORDER BY created_at,operation_id')]


def reconcile_pending(broker, directory):
    """Never replay prepared or ambiguous work on operator restart.

    Reconciliation records current state; it cannot manufacture attribution.
    This first implementation requires escalation for every unresolved outcome.
    """
    unresolved = []
    for row in operation_rows(directory):
        if row['status'] in {'prepared', 'dispatching', 'uncertain'}:
            broker.reconcile(row['operation_id'])
            unresolved.append(row['operation_id'])
    return unresolved


def operator(directory, workspace, contract, kube, verification):
    broker_kube = Kubernetes(directory / 'broker-kubeconfig', kube.cluster_name)

    class Adapter:
        def get_service(self, namespace, name):
            return broker_kube.get_service(namespace, name)

        def patch_service(self, namespace, name, patch):
            active(directory)  # Recheck immediately before the bounded API write.
            return broker_kube.patch_service(namespace, name, patch)

    policy = BrokerPolicy(read(directory / 'owner.json')['run_id'], kube.namespace, 'inventory',
                          read(directory / 'identities-before.json')['Service/inventory'],
                          max_dispatches=contract.max_dispatches)
    broker = ActionBroker(directory / 'operations.sqlite', policy, Adapter())
    unresolved = reconcile_pending(broker, directory)
    if unresolved:
        save(workspace / 'escalation.json', {'reason': 'unresolved_prior_operations', 'operation_ids': unresolved})
        return
    observer_kube = Kubernetes(directory / 'observer-kubeconfig', kube.cluster_name)
    window = read(directory / 'window.json')
    while time.time() < window['end']:
        active(directory)
        if pending := reconcile_pending(broker, directory):
            save(workspace / 'escalation.json', {'reason': 'unresolved_operations', 'operation_ids': pending})
            return
        episode = workspace / ('episode-' + uuid.uuid4().hex)
        episode.mkdir()
        save(episode / 'attempt.json', {'started_at': time.time()})

        def verify_current():
            result = verify(**verification, window_seconds=contract.sample_window_seconds,
                            interval_seconds=contract.sample_window_seconds,
                            request_timeout=contract.request_timeout_seconds)
            save(episode / ('verification-' + uuid.uuid4().hex + '.json'), result)
            return result

        tools = ObservationTools(observer_kube, broker, verification['quote_url'],
                                 verification['inventory_control_url'], verify_current, episode, policy.run_id)
        outcome = runbook(tools, verification_fallback=True)
        save(episode / 'outcome.json', {'finished_at': time.time(), 'claim': outcome})
        # An escalation requires explicit follow-up; do not create new IDs forever.
        if outcome.get('outcome') == 'escalated':
            return
        time.sleep(min(contract.operator_interval_seconds, max(0, window['end'] - time.time())))


def observe(directory, contract, verification):
    window = read(directory / 'window.json')
    for index in range(contract.duration_seconds // contract.sample_interval_seconds):
        scheduled = window['start'] + index * contract.sample_interval_seconds
        time.sleep(max(0, scheduled - time.time()))
        owner_alive(directory)
        started = time.time()
        # Never backfill missed scheduled measurements with a later healthy sample.
        if started - scheduled > contract.sample_lateness_seconds:
            continue
        record = {'slot': index, 'scheduled_at': scheduled, 'started_at': started}
        try:
            record['verification'] = verify(**verification, window_seconds=contract.sample_window_seconds,
                interval_seconds=contract.sample_window_seconds, request_timeout=contract.request_timeout_seconds)
        except Exception as error:
            record['error_type'] = type(error).__name__
        record['finished_at'] = time.time()
        save(directory / 'samples' / f'{index:04d}.json', record)


def worker(directory, workspace, role):
    contract = Contract.model_validate(read(directory / 'contract.json'))
    try:
        # The worker cannot create descendants until its cleanup lease is durable.
        deadline = time.monotonic() + 10
        while not (workspace / 'worker-lease.json').exists():
            owner_alive(directory)
            if time.monotonic() > deadline:
                raise TimeoutError('Unregistered worker')
            time.sleep(0.05)
        lease = read(workspace / 'worker-lease.json')
        if lease != {'pid': os.getpid(), 'identity': process_identity(os.getpid())}:
            raise RuntimeError('Worker identity mismatch')
        with exclusive(directory / f'{role}.lock'), connections(directory) as (kube, verification):
            owner_alive(directory)
            save(workspace / 'ready.json', {'pid': os.getpid(), 'at': time.time()})
            while not (directory / 'window.json').exists():
                owner_alive(directory)
                time.sleep(0.1)
            window = read(directory / 'window.json')
            time.sleep(max(0, window['start'] - time.time()))
            if role == 'observer':
                observe(directory, contract, verification)
            else:
                operator(directory, workspace, contract, kube, verification)
        save(workspace / 'finished.json', {'at': time.time()})
    except BaseException as error:
        save(workspace / 'failed.json', {'at': time.time(), 'error_type': type(error).__name__})
        raise


def own(manifest, directory):
    contract = Contract.model_validate(read(manifest))
    directory.mkdir(mode=0o700)  # Existing campaigns cannot be resumed as owners.
    run_id = uuid.uuid4().hex[:8]
    identity = process_identity(os.getpid())
    if not identity:
        raise RuntimeError('Cannot establish owner identity')
    save(directory / 'owner.json', {'pid': os.getpid(), 'identity': identity, 'run_id': run_id,
                                   'expires_at': time.time() + contract.lease_seconds})
    save(directory / 'contract.json', contract.model_dump())
    sources = [*sorted((ROOT / 'src/autonomy_lab').glob('*.py')), ROOT / 'fixtures/expectations.json',
               ROOT / 'fixtures/database.sql', ROOT / 'infra/toolchain.json']
    save(directory / 'source.json', {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (directory / 'workers').mkdir()
    (directory / 'samples').mkdir()
    processes = []
    try:
        kube = provision(directory, run_id, lease_seconds=contract.lease_seconds)
        for role in ('broker', 'verifier', 'observer'):
            service_identity(kube, directory, role)
        save(directory / 'identities-before.json', identities(kube))
        for role in ('observer', 'operator'):
            workspace, process = spawn_worker(directory, role)
            processes.append((workspace, process))
        deadline = time.monotonic() + 100
        while not all((workspace / 'ready.json').exists() for workspace, _ in processes):
            if any(process.poll() is not None for _, process in processes):
                raise RuntimeError('Initial worker failed')
            if time.monotonic() > deadline:
                raise TimeoutError('Workers did not become ready')
            time.sleep(0.1)
        start = time.time() + 2
        save(directory / 'window.json', {'start': start, 'end': start + contract.duration_seconds})
        while time.time() < start + contract.duration_seconds:
            owner_alive(directory)
            time.sleep(0.25)
        save(directory / 'ending.json', {'at': time.time()})
        for workspace in (directory / 'workers').glob('*'):
            stop_worker(workspace)
        save(directory / 'identities-after.json', identities(kube))
        save(directory / 'finished.json', {'at': time.time()})
    except BaseException as error:
        save(directory / 'failed.json', {'at': time.time(), 'error_type': type(error).__name__})
        raise
    finally:
        save(directory / 'ending.json', {'at': time.time()})
        if (directory / 'environment.json').exists():
            save(directory / 'cleanup.json', cleanup(directory, {'cluster': 'autolab-' + run_id}))
        for _, process in processes:
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    owner = commands.add_parser('own')
    owner.add_argument('manifest', type=Path)
    owner.add_argument('directory', type=Path)
    launch = commands.add_parser('start-operator')
    launch.add_argument('directory', type=Path)
    child = commands.add_parser('worker')
    child.add_argument('directory', type=Path)
    child.add_argument('workspace', type=Path)
    child.add_argument('role', choices=['observer', 'operator'])
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.command == 'own':
        own(args.manifest, directory)
    elif args.command == 'start-operator':
        print(spawn_worker(directory, 'operator')[0], flush=True)
    else:
        worker(directory, args.workspace.resolve(), args.role)


if __name__ == '__main__':
    main()
