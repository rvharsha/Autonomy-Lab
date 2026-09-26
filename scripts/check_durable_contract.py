"""Real broker restart/authority gate, with exact-source offline reproduction."""

import argparse
import hashlib
import json
import os
import signal
import sqlite3
import sys
import time
import uuid
from pathlib import Path

from check_operation_contract import fresh_service

from autonomy_lab import environment
from autonomy_lab.audit import read_events
from autonomy_lab.broker import ActionBroker, BrokerPolicy, Proposal
from autonomy_lab.durable_contract import LEGACY, PRECISE
from autonomy_lab.durable_contract_gate import (
    ARMS,
    CASES,
    KILLS,
    adversarial_checks,
    assess,
    interventions,
)
from autonomy_lab.harness import (
    check,
    establish_fault,
    establish_recovery,
    kill_at_barrier,
    save,
    timestamp,
)
from autonomy_lab.kubernetes import ROOT, Kubernetes


def source_receipt():
    paths = [*sorted((ROOT / 'src').rglob('*.py')),
             *(ROOT / p for p in ('scripts/check_durable_contract.py', 'scripts/check_operation_contract.py',
              'docs/DURABLE_CONTRACT_GATE.md', 'infra/toolchain.json', 'infra/kind.yaml',
              'requirements.lock', 'Dockerfile', 'fixtures/database.sql', 'fixtures/expectations.json'))]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def policy_for(proposal, contract):
    return BrokerPolicy(proposal.run_id, proposal.namespace, proposal.service_name,
                        proposal.service_uid, operation_contract=contract)


def worker(settings_path):
    settings = json.loads(settings_path.read_text())
    proposal = Proposal.model_validate(settings['proposal'])
    adapter = Kubernetes(Path(settings['kubeconfig']), settings['cluster_name'])
    adapter.audit_operation_id = proposal.operation_id
    def hook(stage):
        if stage == 'before_dispatch':
            observed = adapter.get_service(proposal.namespace, proposal.service_name)
            save(Path(settings['conditions_path']), {'changed': observed, 'changed_at': time.time(),
                 'binding': broker.contract_binding(proposal.operation_id)})
        if stage == settings['stage']:
            print(json.dumps({'stage': stage, 'operation_id': proposal.operation_id, 'pid': os.getpid()}), flush=True)
            while True:
                signal.pause()
    broker = ActionBroker(settings['journal_path'], policy_for(proposal, settings['contract']), adapter, hook)
    broker.propose(proposal)
    raise RuntimeError('Worker did not reach its declared kill barrier')


def journal_row(path, operation_id):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        value = dict(db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone())
    for key in ('request', 'result', 'reconciliation'):
        value[key] = json.loads(value[key]) if value[key] else None
    return value


def run_case(kube, transport, verifier, case, contract, directory):
    record = {'case': case, 'contract': contract, 'started_at': time.time(), 'started_iso': timestamp(),
              'controls': [], 'authorization_checks': []}
    permit = directory / 'permit.json'
    save(permit, {'enabled': True})
    try:
        before = fresh_service(kube)
        record.update(before=before, before_at=time.time(), changed=before, changed_at=time.time())
        save(directory / 'observed-service.json', before)
        establish_fault(kube, verifier, directory)
        fault_paths = sorted(directory.glob('fault-establishment-*.json'), key=lambda p: int(p.stem.rsplit('-', 1)[1]))
        proposal = Proposal(run_id='durable-' + uuid.uuid4().hex, operation_id=uuid.uuid4().hex,
                            namespace=kube.namespace, service_name='inventory', service_uid=before['metadata']['uid'],
                            resource_version=before['metadata']['resourceVersion'], expected_target_port=9999,
                            target_port=8080, evidence_ids=[directory.name + '/observed-service.json',
                                                           directory.name + '/' + fault_paths[-1].name])
        policy = policy_for(proposal, contract)
        transport.audit_operation_id = proposal.operation_id
        journal = directory / 'operations.sqlite'

        def authorize(request):
            current = json.loads(permit.read_text())
            record['authorization_checks'].append({'operation_id': request.operation_id,
                                                   'permit': current, 'at': time.time()})
            if current['enabled'] is not True:
                raise PermissionError('Durable test permit withdrawn')

        def intervene():
            if case == 'withdrawn_aba':
                save(permit, {'enabled': False, 'withdrawn_at': time.time()})
            if case == 'budget_revoked':
                policy.max_dispatches = 0
            for index, change in enumerate(interventions(case)):
                step = {**change, 'started_at': time.time()}
                kube.audit_operation_id = proposal.operation_id + '-control-' + str(index)
                if change['verb'] == 'delete':
                    kube.call('delete', 'service', 'inventory', '--wait=false')
                else:
                    step['response'] = kube.patch_service(kube.namespace, change['name'], change['patch'])
                step['finished_at'] = time.time()
                record['controls'].append(step)
                save(directory / 'record.json', record)
            record['changed'] = kube.get_service(kube.namespace, 'inventory')
            record['changed_at'] = time.time()

        class Adapter:
            def get_service(self, namespace, name):
                return transport.get_service(namespace, name)
            def patch_service(self, namespace, name, patch):
                response = transport.patch_service(namespace, name, patch)
                if case == 'lost_ack':
                    record['dropped_response'] = response
                    save(directory / 'record.json', record)
                    raise TimeoutError('Declared acknowledgement loss after real response')
                return response

        def hook(stage):
            if stage == 'before_dispatch':
                record['conditions_at'] = time.time()
                intervene()

        if case in KILLS:
            settings_path = directory / 'worker-input.json'
            conditions_path = directory / 'worker-conditions.json'
            save(settings_path, {'stage': KILLS[case], 'proposal': proposal.model_dump(),
                 'contract': contract, 'journal_path': str(journal), 'conditions_path': str(conditions_path),
                 'kubeconfig': str(transport.kubeconfig), 'cluster_name': transport.cluster_name})
            record['kill'] = kill_at_barrier(
                [sys.executable, str(ROOT / 'scripts/check_durable_contract.py'), 'worker', str(settings_path)],
                KILLS[case], proposal.operation_id, directory / 'worker.stderr.log')
            record['journal_at_kill'] = journal_row(journal, proposal.operation_id)
            broker = ActionBroker(journal, policy, Adapter(), authorize_dispatch=authorize)
            record['binding_at_kill'] = broker.contract_binding(proposal.operation_id)
            if conditions_path.exists():
                conditions = json.loads(conditions_path.read_text())
                record.update(changed=conditions['changed'], changed_at=conditions['changed_at'])
            if case.startswith('contract_change'):
                policy.operation_contract = PRECISE if contract == LEGACY else LEGACY
            if case == 'restart_snapshot':
                intervene()
            operation = broker.resume_prepared(proposal.operation_id)
        else:
            if case == 'budget_exhausted':
                policy.max_dispatches = 0
            broker = ActionBroker(journal, policy, Adapter(), hook, authorize_dispatch=authorize)
            operation = broker.propose(proposal)
        record['binding_before_reopen'] = broker.contract_binding(proposal.operation_id)
        broker = ActionBroker(journal, policy, Adapter(), authorize_dispatch=authorize)
        record['duplicate'] = broker.propose(proposal)
        record['resumed'] = broker.resume_prepared(proposal.operation_id)
        record['reconciled'] = broker.reconcile(proposal.operation_id)
        # Reopening makes an unrecorded dispatch explicitly uncertain.
        record['operation'] = broker.lookup(proposal.operation_id)
        record['binding'] = broker.contract_binding(proposal.operation_id)
        record['journal'] = journal_row(journal, proposal.operation_id)
        record['journal_events'] = broker.events(proposal.operation_id)
        if case == 'withdrawn_aba':
            current = kube.get_service(kube.namespace, 'inventory')
            followup = proposal.model_copy(update={'operation_id': proposal.operation_id + '-withdrawn',
                                                   'resource_version': current['metadata']['resourceVersion']})
            record['followup'] = broker.propose(followup)
        record['permit'] = json.loads(permit.read_text())
        record['after'] = kube.get_service(kube.namespace, 'inventory')
        record['after_at'] = time.time()
        if operation['status'] in ('acknowledged', 'uncertain') and case != 'backend_changed':
            record['readiness'] = {}
            establish_recovery(kube, verifier, directory, 'recovery', record['readiness'])
        record['verification'] = check(kube, verifier, window_seconds=3)
        state = record['operation']['status']
        record['decision'] = ('escalate_uncertain' if state == 'uncertain' else
                              'escalate_refused' if state == 'rejected' else
                              'verified_recovery' if record['verification']['verdict'] == 'verified_success'
                              else 'escalate_verification_failed')
    except Exception as error:
        record['error_type'] = type(error).__name__
    finally:
        record['finished_at'], record['finished_iso'] = time.time(), timestamp()
        for key, pattern in [('fault_evidence', 'fault-establishment-*.json'), ('readiness_evidence', 'recovery-readiness-*.json')]:
            paths = sorted(directory.glob(pattern), key=lambda p: int(p.stem.rsplit('-', 1)[1]))
            record[key] = [json.loads(p.read_text()) for p in paths]
        save(directory / 'record.json', record)
    return record


def retained_records(directory):
    records = []
    for case in CASES:
        for arm in ARMS:
            path = directory / f'{case}-{arm}'
            record = json.loads((path / 'record.json').read_text())
            record['journal_consistent'] = False
            try:
                operation_id = record['operation']['operation_id']
                with sqlite3.connect((path / 'operations.sqlite').as_uri() + '?mode=ro', uri=True) as db:
                    db.row_factory = sqlite3.Row
                    stored = db.execute('SELECT binding FROM operation_contracts WHERE operation_id=?', (operation_id,)).fetchone()
                    events = [{**dict(row), 'details': json.loads(row['details'])} for row in db.execute(
                        'SELECT * FROM operation_events WHERE operation_id=? ORDER BY sequence', (operation_id,))]
                    used = db.execute('SELECT count(*) FROM operations WHERE run_id=? AND budget_reserved=1',
                                      (record['operation']['run_id'],)).fetchone()[0]
                record['journal_consistent'] = (journal_row(path / 'operations.sqlite', operation_id) == record['journal']
                    and json.loads(stored['binding']) == record['binding'] and events == record['journal_events']
                    and used == record['operation']['budget_used'])
            except (sqlite3.Error, KeyError, TypeError, ValueError):
                pass
            records.append(record)
    return records


def reproduce(directory):
    declaration = json.loads((directory / 'declaration.json').read_text())
    if declaration != {'schema': 1, 'source': source_receipt(), 'matrix': [[c, a] for c in CASES for a in ARMS]}:
        raise ValueError('Replay requires the original source and complete declaration')
    return assess(retained_records(directory), json.loads((directory / 'server-audit.json').read_text()),
                  json.loads((directory / 'cleanup.json').read_text())['status'])


def run(directory):
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    save(directory / 'declaration.json', {'schema': 1, 'source': source_receipt(),
         'matrix': [[c, a] for c in CASES for a in ARMS]})
    result, cleanup = {'status': 'failed', 'started_at': time.time()}, {'status': 'not_provisioned'}
    try:
        kube = environment.provision(directory, uuid.uuid4().hex[:8], lease_seconds=1800)
        transport = environment.service_identity(kube, directory, 'broker')
        verifier = environment.verifier_identity(kube, directory)
        for case in CASES:
            for contract in ARMS:
                # Each backend case starts with a working PostgreSQL Service.
                if case == 'backend_changed':
                    kube.patch_service(kube.namespace, 'postgres', [
                        {'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 5432}])
                target = directory / f'{case}-{contract}'
                target.mkdir()
                record = run_case(kube, transport, verifier, case, contract, target)
                print(case, contract, record.get('operation', {}).get('status', record.get('error_type')), flush=True)
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
                    raise ValueError('Replay changed')
                if evaluation['status'] == 'passed':
                    negative = adversarial_checks(retained_records(directory), captured, cleanup['status'])
                    save(directory / 'adversarial.json', negative)
                    if negative['status'] != 'passed':
                        raise ValueError('Evidence corruption was not detected')
                if result.get('execution_completed') and not result.get('error_type'):
                    result['status'] = evaluation['status']
            except Exception as error:
                result['assessment_error_type'] = type(error).__name__
            result['finished_at'] = time.time()
            save(directory / 'result.json', result)
    if result['status'] != 'passed':
        raise RuntimeError('Durable contract gate failed; original evidence retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'reproduce', 'worker'))
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.mode == 'worker':
        worker(args.directory.resolve())
    elif args.mode == 'run':
        run(args.directory.resolve())
    else:
        result = reproduce(args.directory.resolve())
        print(json.dumps(result, indent=2))
        if result['status'] != 'passed':
            raise SystemExit(1)
