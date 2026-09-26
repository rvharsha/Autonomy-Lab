"""Journal coordination tests; stub responses are not Kubernetes evidence."""

import copy
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from autonomy_lab.audit import assess
from autonomy_lab.broker import ActionBroker, BrokerPolicy, Proposal
from autonomy_lab.durable_contract import LEGACY, PRECISE, binding_for, patch_for_binding
from autonomy_lab.operation_contract import AUTHORITY, HEARTBEAT


class Crash(BaseException):
    pass


class RecordingTransport:
    """Record sends; do not emulate or validate JSON Patch semantics."""
    def __init__(self):
        self.service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {
            'namespace': 'autonomy-lab', 'name': 'inventory', 'uid': 'authored-uid',
            'resourceVersion': '10', 'annotations': {HEARTBEAT: 'zero', AUTHORITY: 'enabled'}},
            'spec': {'selector': {'app': 'inventory'}, 'ports': [
                {'name': 'http', 'port': 80, 'targetPort': 9999, 'protocol': 'TCP'}]}, 'status': {}}
        self.sent = []
        self.reads = 0
        self.unavailable = False

    def get_service(self, namespace, name):
        self.reads += 1
        if self.unavailable:
            raise ConnectionError('authored read failure')
        return copy.deepcopy(self.service)

    def patch_service(self, namespace, name, patch):
        self.sent.append(copy.deepcopy(patch))
        response = copy.deepcopy(self.service)
        response['metadata']['resourceVersion'] = '12'
        response['spec']['ports'][0]['targetPort'] = 8080
        return response


@pytest.fixture
def setup(tmp_path):
    policy = BrokerPolicy('authored-run', 'autonomy-lab', 'inventory', 'authored-uid',
                          operation_contract=PRECISE)
    request = Proposal(run_id=policy.run_id, operation_id='authored-op', namespace=policy.namespace,
                       service_name=policy.service_name, service_uid=policy.service_uid,
                       resource_version='10', expected_target_port=9999, target_port=8080,
                       evidence_ids=['authored-observation'])
    adapter = RecordingTransport()
    broker = ActionBroker(tmp_path / 'journal.sqlite', policy, adapter)
    return broker, policy, adapter, request


def pause(broker, request, stage):
    def hook(point):
        if point == stage:
            raise Crash()
    broker.hook = hook
    with pytest.raises(Crash):
        broker.propose(request)
    broker.hook = None


def test_agent_cannot_select_contract_or_supply_conditions(setup):
    broker, _, adapter, request = setup
    for field, value in [('operation_contract', PRECISE), ('snapshot', adapter.service)]:
        with pytest.raises(ValidationError):
            broker.propose({**request.model_dump(), field: value})
    assert adapter.reads == 0 and not adapter.sent


def test_snapshot_is_durable_before_dispatch_and_resume_does_not_reread(setup):
    broker, policy, adapter, request = setup
    pause(broker, request, 'before_dispatch')
    original = broker.contract_binding(request.operation_id)
    assert original == binding_for(request.model_dump(), PRECISE, adapter.service)
    adapter.service['metadata']['annotations'][HEARTBEAT] = 'later'
    adapter.unavailable = True
    reopened = ActionBroker(broker.journal_path, policy, adapter)
    assert reopened.resume_prepared(request.operation_id)['status'] == 'acknowledged'
    assert adapter.reads == 1
    assert broker.contract_binding(request.operation_id) == original
    assert adapter.sent == [patch_for_binding(request.model_dump(), original)]


@pytest.mark.parametrize('stage', ['after_intent', 'before_dispatch'])
def test_contract_change_on_restart_refuses_without_spend(setup, stage):
    broker, policy, adapter, request = setup
    pause(broker, request, stage)
    policy.operation_contract = LEGACY
    result = ActionBroker(broker.journal_path, policy, adapter).resume_prepared(request.operation_id)
    assert result['reason'] == 'operation_contract_changed'
    assert result['budget_used'] == 0 and not adapter.sent
    assert broker.contract_binding(request.operation_id)['contract_id'] == PRECISE


@pytest.mark.parametrize('change,reason', [
    ('contract', 'operation_contract_changed'), ('withdraw', 'policy_disabled'),
    ('budget', 'budget_revoked'), ('binding', 'operation_binding_invalid')])
def test_atomic_claim_rechecks_conditions_and_authority(setup, change, reason):
    broker, policy, adapter, request = setup
    def hook(stage):
        if stage != 'before_dispatch':
            return
        if change == 'contract':
            policy.operation_contract = LEGACY
        elif change == 'withdraw':
            policy.enabled = False
        elif change == 'budget':
            policy.max_dispatches = 0
        else:
            with sqlite3.connect(broker.journal_path) as db:
                db.execute("UPDATE operation_contracts SET binding='{}'")
    broker.hook = hook
    result = broker.propose(request)
    assert result['reason'] == reason and result['budget_used'] == 0
    assert not adapter.sent


@pytest.mark.parametrize('change', ['missing', 'digest', 'proposal', 'snapshot'])
def test_corrupt_binding_cannot_be_refreshed_or_repaired_on_resume(setup, change):
    broker, policy, adapter, request = setup
    pause(broker, request, 'before_dispatch')
    binding = broker.contract_binding(request.operation_id)
    if change == 'digest':
        binding['binding_sha256'] = 'incorrect'
    elif change == 'proposal':
        binding['operation_id'] = 'another'
    elif change == 'snapshot':
        binding['snapshot']['spec']['selector'] = {'app': 'elsewhere'}
    with sqlite3.connect(broker.journal_path) as db:
        if change == 'missing':
            db.execute('DELETE FROM operation_contracts')
        else:
            db.execute('UPDATE operation_contracts SET binding=?', (json.dumps(binding),))
    result = ActionBroker(broker.journal_path, policy, adapter).resume_prepared(request.operation_id)
    assert result['reason'] == 'operation_binding_invalid' and not adapter.sent


def test_old_journal_migrates_to_legacy_even_under_new_policy(setup):
    broker, policy, adapter, request = setup
    pause(broker, request, 'after_intent')
    with sqlite3.connect(broker.journal_path) as db:
        db.execute('DROP TABLE operation_contracts')
    reopened = ActionBroker(broker.journal_path, policy, adapter)
    assert reopened.contract_binding(request.operation_id) == binding_for(request.model_dump(), LEGACY)
    assert reopened.resume_prepared(request.operation_id)['reason'] == 'operation_contract_changed'
    assert not adapter.sent


@pytest.mark.parametrize('change,reason', [('stale', 'resource_version_changed'),
                                         ('action', 'contract_snapshot_out_of_scope')])
def test_initial_preflight_and_precise_action_scope_are_required(setup, change, reason):
    broker, policy, adapter, request = setup
    if change == 'stale':
        adapter.service['metadata']['resourceVersion'] = '11'
    else:
        policy.allowed_target_ports = frozenset({8082})
        request = request.model_copy(update={'target_port': 8082})
    assert broker.propose(request)['reason'] == reason
    assert not adapter.sent
    assert broker.contract_binding(request.operation_id)['snapshot'] is None


def test_concurrent_resumes_send_once_with_one_binding(setup):
    broker, policy, adapter, request = setup
    pause(broker, request, 'after_intent')
    workers = [ActionBroker(broker.journal_path, policy, adapter) for _ in range(6)]
    barrier = threading.Barrier(6)
    def resume(worker):
        barrier.wait(timeout=5)
        return worker.resume_prepared(request.operation_id)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(resume, workers))
    assert len(adapter.sent) == 1
    assert sum(e['event'] == 'conditions_recorded' for e in broker.events(request.operation_id)) == 1


def test_late_stale_read_cannot_reject_another_workers_recorded_conditions(setup):
    broker, policy, adapter, request = setup
    pause(broker, request, 'after_intent')
    reading, bound, stale_finished = threading.Event(), threading.Event(), threading.Event()
    class Slow(RecordingTransport):
        def get_service(self, namespace, name):
            reading.set()
            assert bound.wait(5)
            value = super().get_service(namespace, name)
            value['metadata']['resourceVersion'] = '11'
            return value
    slow = ActionBroker(broker.journal_path, policy, Slow())
    def hook(stage):
        if stage == 'before_dispatch':
            bound.set()
            assert stale_finished.wait(5)
    broker.hook = hook
    def stale():
        result = slow.resume_prepared(request.operation_id)
        stale_finished.set()
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(stale)
        assert reading.wait(5)
        result = broker.resume_prepared(request.operation_id)
        assert future.result()['status'] == 'prepared'
    assert result['status'] == 'acknowledged' and len(adapter.sent) == 1


def test_precise_audit_requires_exact_patch_and_valid_binding(setup):
    broker, _, adapter, request = setup
    operation = broker.propose(request)
    bindings = {request.operation_id: broker.contract_binding(request.operation_id)}
    event = {'auditID': 'authored-audit', 'verb': 'patch', 'requestReceivedTimestamp': '2',
             'objectRef': {'namespace': 'autonomy-lab', 'name': 'inventory', 'resource': 'services'},
             'user': {'username': 'system:serviceaccount:autonomy-lab:broker'},
             'userAgent': 'autonomy-lab-operation/' + request.operation_id,
             'responseStatus': {'code': 200}, 'responseObject': adapter.service,
             'requestObject': adapter.sent[0]}
    def evaluate():
        return assess([event], [operation], started_at='1', finished_at='3', contract_bindings=bindings)
    assert evaluate()['successful_unmatched_mutations'] == 0
    event['requestObject'].append({'op': 'add', 'path': '/metadata/labels', 'value': {'unsafe': 'yes'}})
    assert evaluate()['successful_unmatched_mutations'] == 1
    event['requestObject'].pop()
    bindings[request.operation_id]['binding_sha256'] = 'changed'
    assert evaluate()['successful_unmatched_mutations'] == 1
