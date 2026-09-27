"""Authored decision counterexamples; never counted as live experiment outcomes."""

import copy

import pytest
from test_runbook import ScriptedTools

from autonomy_lab.desired_state import bind, contract, run, validate_contract
from autonomy_lab.experiments import validate_config


def tools(target=8081):
    t = ScriptedTools(target_port=target, backend_port=8080)
    t.run_id = 'test-run'
    t.responses['observe_service']['service']['metadata']['namespace'] = 'autonomy-lab'
    t.responses['probe_backend'] = {'kind': 'error', 'error': 'transport_failure', 'backend_port': 8080}
    return t


def intent():
    return bind('test-run', 'test-uid')


def test_fixed_intent_restores_routing_without_claiming_backend_health():
    t = tools()
    assert run(t, intent())['outcome'] == 'resolved'
    assert t.proposal['target_port'] == 8080
    assert t.proposal['expected_target_port'] == 8081
    assert t.proposal['service_uid'] == 'test-uid'
    assert [n for n, _ in t.calls] == ['observe_service', 'probe_backend', 'probe_application',
                                      'propose_repair', 'verify_recovery', 'finish']


@pytest.mark.parametrize('verdict', ['verified_failure', 'indeterminate', None])
def test_write_acknowledgement_does_not_establish_recovery(verdict):
    t = tools()
    t.responses['verify_recovery']['verdict'] = verdict
    assert run(t, intent())['outcome'] == 'escalated'
    assert t.proposal is not None


def test_failed_probe_port_does_not_override_trusted_intent():
    t = tools()
    t.responses['probe_backend']['backend_port'] = 9090
    run(t, intent())
    assert t.proposal['target_port'] == 8080


@pytest.mark.parametrize('field,value', [('uid', 'other-resource'), ('namespace', 'other-namespace')])
def test_intent_cannot_cross_resource_scope(field, value):
    t = tools()
    t.responses['observe_service']['service']['metadata'][field] = value
    assert run(t, intent())['outcome'] == 'escalated'
    assert t.proposal is None


def test_no_mutation_of_a_matching_target():
    t = tools(8080)
    assert run(t, intent())['outcome'] == 'healthy'
    assert t.proposal is None


@pytest.mark.parametrize('status', ['uncertain', 'dispatching', 'prepared'])
def test_unresolved_write_is_inspected_once_and_never_retried(status):
    t = tools()
    t.responses['propose_repair'] = {'status': status}
    t.responses['get_operation'] = {'status': 'uncertain', 'reconciliation': {'observation': 'desired_state_not_observed'}}
    assert run(t, intent())['outcome'] == 'escalated'
    assert [n for n, _ in t.calls].count('propose_repair') == 1
    assert [n for n, _ in t.calls].count('get_operation') == 1
    assert 'verify_recovery' not in [n for n, _ in t.calls]


def test_uncertain_effect_can_be_verified_without_claiming_attribution():
    t = tools()
    t.responses['propose_repair'] = {'status': 'uncertain'}
    t.responses['get_operation'] = {'status': 'uncertain', 'reconciliation': {'observation': 'desired_state_observed'}}
    result = run(t, intent())
    assert result['outcome'] == 'resolved'
    assert 'attribution remains uncertain' in result['reason']


def test_stale_refusal_never_triggers_a_repair_retry():
    t = tools()
    t.responses['propose_repair'] = {'status': 'rejected', 'reason': 'resource_version_changed'}
    assert run(t, intent())['outcome'] == 'escalated'
    assert [n for n, _ in t.calls].count('propose_repair') == 1


@pytest.mark.parametrize('field,value', [('target_port', 9090), ('target_port', 8080.0), ('schema_version', True),
                                        ('namespace', 'another'), ('lifetime', 'forever'), ('extra', True)])
def test_fixed_intent_rejects_scope_and_type_changes(field, value):
    value_contract = {**contract(), field: value}
    with pytest.raises(ValueError):
        validate_contract(value_contract)
    t = tools()
    value_intent = {**intent(), 'contract': value_contract}
    with pytest.raises(ValueError):
        run(t, value_intent)
    assert t.call_count == 0


def test_trial_identity_and_fresh_workspace_are_required():
    t = tools()
    with pytest.raises(ValueError):
        run(t, bind('other-trial', 'test-uid'))
    t.call_count = 1
    with pytest.raises(ValueError):
        run(t, intent())


def test_new_variant_requires_explicit_controller_contract_before_execution():
    cfg = {'scenarios': ['observer_routing'], 'variants': ['desired_state'], 'repetitions': 1,
           'window_seconds': 30, 'expected_behavior': {'observer_routing': 'repair'}}
    with pytest.raises(ValueError):
        validate_config(cfg)
    declared = {**copy.deepcopy(cfg), 'reconciliation_contract': contract()}
    validate_config(declared)


def test_maintained_program_cannot_write_after_a_backend_observer_error():
    from autonomy_lab.procedure import Decisions
    from autonomy_lab.runbook import execute

    for verdict in ('verified_success', 'verified_failure', 'indeterminate'):
        t = tools()
        t.responses['verify_recovery']['verdict'] = verdict
        result = execute(t, Decisions('verify', 'repair', 'refresh'))
        assert t.proposal is None
        assert result['outcome'] == ('healthy' if verdict == 'verified_success' else 'escalated')
