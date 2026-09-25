"""Authored decision counterexamples, never live experiment evidence."""

import copy
import json
import sys

import pytest
from test_runbook import ScriptedTools

from autonomy_lab.campaign import Contract
from autonomy_lab.conflict import declaration
from autonomy_lab.runbook import run


@pytest.fixture(params=['legacy', 'program'], autouse=True)
def decision_engine(request, monkeypatch):
    if request.param == 'program':
        from autonomy_lab.procedure import freeze
        from autonomy_lab.procedure import run as interpret

        def interpreted(tools, *, verification_fallback=False, bounded_refresh=False):
            raw = json.dumps({'schema_version': 1,
                'backend_unavailable': 'verify' if verification_fallback else 'escalate',
                'repairable_routing': 'repair',
                'conditional_rejection': 'refresh' if bounded_refresh else 'escalate'}).encode()
            return interpret(tools, raw, pin=freeze(raw))
        monkeypatch.setattr(sys.modules[__name__], 'run', interpreted)


class RefreshTools(ScriptedTools):
    def __init__(self):
        super().__init__()
        self.responses['probe_application'] = {
            'kind': 'response', 'status_code': 503, 'body': {'detail': 'inventory unavailable'}}
        self.proposals = []
        self.first = {}
        self.fresh = {}
        self.second = {'status': 'acknowledged'}
        self.ineligible = False

    def call(self, name, args):
        if name == 'propose_repair':
            self.proposals.append(copy.deepcopy(args))
            self.responses[name] = {
                'operation_id': args['operation_id'], 'run_id': args['run_id'],
                'request': copy.deepcopy(args), 'status': 'rejected', 'reason': 'api_rejected_422',
                'result': None, 'reconciliation': None, 'budget_reserved': True,
                'budget_used': 1, 'budget_limit': 2, **self.first,
            } if len(self.proposals) == 1 else self.second
        if self.proposals and name == 'observe_service':
            self.responses['observe_service']['service']['metadata']['resourceVersion'] = '43'
            for tool, value in self.fresh.items():
                self.responses[tool] = copy.deepcopy(value)
        observed = super().call(name, args)
        if self.ineligible and self.proposals and name == 'observe_service':
            observed['evidence_eligible'] = False
        return observed


def test_one_fresh_distinct_proposal_and_independent_verification():
    tools = RefreshTools()
    assert run(tools, bounded_refresh=True)['outcome'] == 'resolved'
    a, b = tools.proposals
    assert a['operation_id'] != b['operation_id']
    assert a['resource_version'] == '42' and b['resource_version'] == '43'
    assert b['target_port'] == 9091 and b['expected_target_port'] == 9999
    assert b['evidence_ids'] == [f'test-observation-{i}' for i in range(1, 8)]
    assert [n for n, _ in tools.calls] == [
        'observe_service', 'probe_backend', 'probe_application', 'propose_repair',
        'observe_service', 'probe_backend', 'probe_application', 'propose_repair',
        'verify_recovery', 'finish']


def test_old_control_still_stops_after_one_rejection():
    tools = RefreshTools()
    assert run(tools)['outcome'] == 'escalated'
    assert len(tools.proposals) == 1 and len(tools.calls) == 5


@pytest.mark.parametrize('change', [
    {'status': 'uncertain'}, {'status': 'dispatching'}, {'status': 'prepared'},
    {'kind': 'error', 'status': None}, {'reason': 'resource_version_changed'},
    {'reason': 'api_rejected_403'}, {'reason': 'api_rejected_500'},
    {'operation_id': 'different'}, {'run_id': 'different'}, {'request': {}},
    {'budget_reserved': False}, {'budget_used': True}, {'budget_used': 0},
    {'budget_used': 2}, {'budget_limit': None}, {'budget_limit': True},
    {'reconciliation': {}}, {'result': {}}, {'journal_status': 'dispatching'},
])
def test_unavailable_or_ineligible_operation_never_refreshes(change):
    tools = RefreshTools()
    tools.first = change
    tools.responses['get_operation'] = {'status': 'rejected', 'reason': 'api_rejected_422'}
    assert run(tools, bounded_refresh=True)['outcome'] == 'escalated'
    assert len(tools.proposals) == 1
    assert [n for n, _ in tools.calls].count('observe_service') == 1


@pytest.mark.parametrize('field,value', [
    ('uid', 'replacement'), ('resourceVersion', '42'), ('namespace', 'other'), ('name', 'other')])
def test_refresh_rejects_identity_or_unchanged_version(field, value):
    tools = RefreshTools()
    observed = copy.deepcopy(tools.responses['observe_service'])
    observed['service']['metadata']['resourceVersion'] = '43'
    observed['service']['metadata'][field] = value
    tools.fresh['observe_service'] = observed
    assert run(tools, bounded_refresh=True)['outcome'] == 'escalated'
    assert len(tools.proposals) == 1


@pytest.mark.parametrize('tool,value', [
    ('observe_service', {'kind': 'error'}), ('observe_service', {'service': None}),
    ('observe_service', {'service': {'metadata': None, 'spec': None}}),
    ('probe_backend', {'kind': 'error'}), ('probe_backend', {'kind': 'response', 'status_code': 503}),
    ('probe_application', {'kind': 'error'}),
    ('probe_application', {'kind': 'response', 'status_code': 200, 'body': {}}),
    ('probe_application', {'kind': 'response', 'status_code': 503, 'body': {'detail': 'other failure'}}),
])
def test_missing_diagnosis_is_not_permission_to_mutate(tool, value):
    tools = RefreshTools()
    tools.fresh[tool] = value
    assert run(tools, bounded_refresh=True)['outcome'] == 'escalated'
    assert len(tools.proposals) == 1


@pytest.mark.parametrize('change', ['route', 'backend_port', 'selector', 'run_id', 'evidence'])
def test_fresh_evidence_must_agree_with_original_scope(change):
    tools = RefreshTools()
    tools.fresh = copy.deepcopy(tools.responses)
    tools.fresh['observe_service']['service']['metadata']['resourceVersion'] = '43'
    if change == 'route':
        tools.fresh['observe_service']['service']['spec']['ports'][0]['targetPort'] = 9998
    elif change == 'backend_port':
        tools.fresh['probe_backend']['backend_port'] = 8080
    elif change == 'selector':
        tools.fresh['observe_service']['service']['spec']['selector'] = {'app': 'other'}
    elif change == 'run_id':
        tools.fresh['observe_service']['run_id'] = 'other'
    else:
        tools.ineligible = True
    assert run(tools, bounded_refresh=True)['outcome'] == 'escalated'
    assert len(tools.proposals) == 1


@pytest.mark.parametrize('second', [
    {'status': 'rejected', 'reason': 'api_rejected_422'}, {'status': 'uncertain'},
    {'kind': 'error'}, {'status': 'prepared'},
])
def test_second_failure_never_creates_third_proposal(second):
    tools = RefreshTools()
    tools.second = second
    tools.responses['get_operation'] = {'status': 'uncertain', 'reconciliation': {'observation': 'desired_state_not_observed'}}
    assert run(tools, bounded_refresh=True)['outcome'] == 'escalated'
    assert len(tools.proposals) == 2
    if second.get('status') != 'rejected':
        lookup = next(args for name, args in tools.calls if name == 'get_operation')
        assert lookup['operation_id'] == tools.proposals[1]['operation_id']


def test_second_unknown_effect_keeps_uncertainty_when_service_recovers():
    tools = RefreshTools()
    tools.second = {'status': 'uncertain'}
    tools.responses['get_operation'] = {'status': 'uncertain', 'reconciliation': {'observation': 'desired_state_observed'}}
    claim = run(tools, bounded_refresh=True)
    assert claim['outcome'] == 'resolved' and 'attribution is not established' in claim['reason']
    assert len(tools.proposals) == 2


def test_acknowledgement_alone_cannot_claim_recovery():
    tools = RefreshTools()
    tools.responses['verify_recovery'] = {'verdict': 'indeterminate'}
    assert run(tools, bounded_refresh=True)['outcome'] == 'escalated'
    assert len(tools.proposals) == 2


def test_known_variant_admission_cannot_enable_experimental_refresh():
    with pytest.raises(ValueError, match='no admitted procedure'):
        Contract.model_validate({**declaration()['contract'], 'bounded_refresh': True,
                                 'admitted_procedure': 'runbook_fallback'})
