"""One real Kubernetes API feasibility cohort, with retained evidence and replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

from autonomy_lab import environment
from autonomy_lab.audit import read_events
from autonomy_lab.broker import PatchRejected
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.operation_contract import (
    ARMS,
    AUTHORITY,
    CASES,
    HEARTBEAT,
    assess,
    intervention_patch,
    repair_patch,
)


def source_receipt():
    paths = ['docs/OPERATION_CONTRACT_GATE.md', 'src/autonomy_lab/operation_contract.py',
             'scripts/check_operation_contract.py', 'src/autonomy_lab/kubernetes.py',
             'src/autonomy_lab/environment.py', 'src/autonomy_lab/audit.py',
             'src/autonomy_lab/harness.py', 'src/autonomy_lab/janitor.py',
             'infra/toolchain.json', 'infra/kind.yaml', 'requirements.lock']
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def fresh_service(kube):
    old = kube.get_service(kube.namespace, 'inventory')
    if old['metadata'].get('finalizers'):
        kube.patch_service(kube.namespace, 'inventory', [
            {'op': 'test', 'path': '/metadata/uid', 'value': old['metadata']['uid']},
            {'op': 'remove', 'path': '/metadata/finalizers'},
        ])
    kube.call('delete', 'service', 'inventory', '--wait=true', '--timeout=20s')
    body = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {
        'namespace': kube.namespace, 'name': 'inventory',
        'annotations': {HEARTBEAT: 'tick-0', AUTHORITY: 'enabled'}},
        'spec': {'selector': {'app': 'inventory'}, 'ports': [
            {'name': 'http', 'port': 80, 'targetPort': 9999, 'protocol': 'TCP'}]}}
    kube.call('create', '-f', '-', input=json.dumps(body))
    return kube.get_service(kube.namespace, 'inventory')


def run_case(kube, broker, case, arm, owner_uid, directory):
    record = {'case': case, 'arm': arm, 'operation_id': 'contract-' + uuid.uuid4().hex,
              'owner_uid': owner_uid, 'started_at': time.time()}
    try:
        kube.audit_operation_id = record['operation_id'] + '-fixture'
        record['before'] = fresh_service(kube)
        record['patch'] = repair_patch(record['before'], arm)
        record['prepared_at'] = time.time()
        record['intervention'] = intervention_patch(case, owner_uid)
        save(directory / 'record.json', record)
        kube.audit_operation_id = record['operation_id'] + '-intervention'
        if case == 'recreated':
            fresh_service(kube)
        elif record['intervention']:
            kube.patch_service(kube.namespace, 'inventory', record['intervention'])
        record['changed'] = kube.get_service(kube.namespace, 'inventory')
        record['changed_at'] = time.time()
        broker.audit_operation_id = record['operation_id']
        save(directory / 'record.json', record)
        record['dispatch_at'] = time.time()
        try:
            record['response'] = broker.patch_service(kube.namespace, 'inventory', record['patch'])
            record['outcome'] = 'acknowledged'
        except PatchRejected as error:
            record.update(outcome='rejected', reason=error.reason)
        record['after'] = kube.get_service(kube.namespace, 'inventory')
    except Exception as error:
        record['error_type'] = type(error).__name__
    finally:
        record['finished_at'] = time.time()
        save(directory / 'record.json', record)
    return record


def reproduce(directory):
    declaration = json.loads((directory / 'declaration.json').read_text())
    if declaration != {'schema': 1, 'source': source_receipt(),
                        'matrix': [[case, arm] for case in CASES for arm in ARMS]}:
        raise ValueError('Replay must use the frozen source and declaration')
    records = [json.loads((directory / f'{case}-{arm}' / 'record.json').read_text())
               for case in CASES for arm in ARMS]
    captured = json.loads((directory / 'server-audit.json').read_text())
    cleanup = json.loads((directory / 'cleanup.json').read_text())['status']
    return assess(records, captured, cleanup)


def run(directory):
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    save(directory / 'declaration.json', {'schema': 1, 'source': source_receipt(),
         'matrix': [[case, arm] for case in CASES for arm in ARMS]})
    result = {'status': 'failed', 'started_at': time.time()}
    cleanup = {'status': 'not_provisioned'}
    try:
        kube = environment.provision(directory, uuid.uuid4().hex[:8], lease_seconds=1800)
        broker = environment.service_identity(kube, directory, 'broker')
        owner_uid = json.loads(kube.call('get', 'configmap', 'database-init', '-o', 'json'))['metadata']['uid']
        for case in CASES:
            for arm in ARMS:
                target = directory / f'{case}-{arm}'
                target.mkdir()
                record = run_case(kube, broker, case, arm, owner_uid, target)
                print(case, arm, record.get('outcome', record.get('error_type')), flush=True)
        result['execution_completed'] = True
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        try:
            if (directory / 'environment.json').exists():
                environment.teardown(directory)
                cleanup['status'] = 'deleted'
        except BaseException as error:
            cleanup.update(status='failed', error_type=type(error).__name__)
        finally:
            save(directory / 'cleanup.json', cleanup)
            try:
                captured = read_events(directory / 'server-audit')
                captured['collection_closed'] = cleanup['status'] == 'deleted'
                save(directory / 'server-audit.json', captured)
                evaluation = reproduce(directory)
                save(directory / 'evaluation.json', evaluation)
                if evaluation != reproduce(directory):
                    raise ValueError('Replay differs')
                if not result.get('error_type') and result.get('execution_completed'):
                    result['status'] = evaluation['status']
            except Exception as error:
                result['assessment_error_type'] = type(error).__name__
            result['finished_at'] = time.time()
            save(directory / 'result.json', result)
            print(directory, flush=True)
    if result['status'] != 'passed':
        raise RuntimeError('Operation-contract feasibility failed; original evidence retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'reproduce'))
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.mode == 'run':
        run(args.directory.resolve())
    else:
        result = reproduce(args.directory.resolve())
        print(json.dumps(result, indent=2))
        if result['status'] != 'passed':
            raise SystemExit(1)
