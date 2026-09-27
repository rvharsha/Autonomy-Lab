"""Authored adversarial selection inputs; never real campaign outcomes."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from autonomy_lab.customer_benefit import plan as training_plan
from autonomy_lab.procedures import Refused
from experiments.shadow_selection import gate, training


def training_values():
    return {
        name: {
            **{k: spec[k] for k in ('arm', 'context', 'candidate', 'evidence_use')},
            'measurement_valid': True, 'authority_conformant': True, 'eligible': True,
            'sample_counts': {'verified_success': 11 if name == 'precise-heartbeat_after' else 10,
                              'verified_failure': 10 if name == 'precise-heartbeat_after' else 11,
                              'unknown': 0},
            'spent_dispatches': 2, 'actual_api_attempts': 2,
        } for name, spec in training_plan()['cases'].items()
    }


def declared():
    return gate.plan(training.select_training(training_values()), 1000)


def measurements():
    return {
        name: {
            **{k: spec[k] for k in ('arm', 'context', 'candidate', 'evidence_use')},
            'measurement_valid': True, 'authority_conformant': True, 'eligible': True,
            'sample_counts': {'verified_success': 10, 'verified_failure': 11, 'unknown': 0},
            'spent_dispatches': 2, 'actual_api_attempts': 2,
            'run_id': 'authored-run-' + name, 'workload_uid': 'authored-uid-' + name,
        } for name, spec in declared()['cases'].items()
    }


def test_frozen_choice_controls_execution_and_preserves_stronger_comparator():
    p = declared()
    assert len(p['cases']) == 9 and sorted(sum(p['shards'], [])) == sorted(p['cases'])
    assert p['selection']['selected'] == 'precise'
    for name, spec in p['cases'].items():
        expected = 'legacy' if name.startswith('legacy-') else 'precise'
        assert spec['execution_arm'] == expected
        assert spec['contract']['max_dispatches'] == 2
        assert not spec['contract']['admit_program'] and spec['contract']['admitted_procedure'] is None
    assert p['cases']['selected-heartbeat_final']['candidate'] == p['cases']['maintained-heartbeat_final']['candidate']
    tied = training_values()
    tied['precise-heartbeat_after']['sample_counts'].update(verified_success=10, verified_failure=11)
    p = gate.plan(training.select_training(tied), 1000)
    assert p['cases']['selected-heartbeat_final']['execution_arm'] == 'legacy'
    assert p['cases']['maintained-heartbeat_final']['execution_arm'] == 'precise'


def test_only_complete_eligible_training_can_choose():
    for damage in ('missing', 'ineligible', 'unknown', 'wrong_identity'):
        values = training_values()
        first = values['legacy-quiet']
        if damage == 'missing':
            del values['legacy-quiet']
        elif damage == 'ineligible':
            first['eligible'] = False
        elif damage == 'unknown':
            first['sample_counts'].update(unknown=1, verified_failure=10)
        else:
            first['candidate'] = {}
        with pytest.raises(Refused):
            training.select_training(values)


def test_selection_cannot_be_changed_independently_of_training():
    value = declared()['selection']
    value['selected'] = 'legacy'
    with pytest.raises(Refused, match='Training selection changed'):
        gate.plan(value, 1000)


def test_noise_between_identical_policies_cannot_establish_strategy_value():
    values = measurements()
    assert gate.select(declared(), values)['decision'] == 'no_update_benefit_observed'
    values['selected-heartbeat_final']['sample_counts'].update(verified_success=11, verified_failure=10)
    result = gate.select(declared(), values)
    assert result['decision'] == 'bounded_update_observed'
    assert result['comparisons']['maintained']['dominates']
    assert result['same_policy_as_maintained']
    assert not any(result[k] for k in ('incremental_strategy_value_demonstrated',
                                       'autonomous_discovery_demonstrated', 'promotion',
                                       'selection_confers_authority', 'confirmation_run'))


@pytest.mark.parametrize('damage', ['missing', 'unsafe', 'unknown', 'duplicate', 'same_workload',
                                   'wrong_candidate', 'bool_budget', 'bool_attempts'])
def test_bad_evidence_blocks_benefit(damage):
    values = measurements()
    value = values['selected-heartbeat_final']
    if damage == 'missing':
        del values['maintained-protected_before']
    elif damage == 'unsafe':
        value['authority_conformant'] = False
    elif damage == 'unknown':
        value['sample_counts'].update(unknown=1, verified_failure=10)
    elif damage in {'duplicate', 'same_workload'}:
        key = 'run_id' if damage == 'duplicate' else 'workload_uid'
        value[key] = values['maintained-heartbeat_final'][key]
    elif damage == 'wrong_candidate':
        value['candidate'] = values['legacy-heartbeat_final']['candidate']
    elif damage == 'bool_budget':
        value['spent_dispatches'] = True
    else:
        value['actual_api_attempts'] = True
    with pytest.raises(Refused):
        gate.select(declared(), values)


@pytest.mark.parametrize('name', list(measurements()))
def test_every_case_is_required_to_be_eligible(name):
    values = measurements()
    values['selected-heartbeat_final']['sample_counts'].update(verified_success=11, verified_failure=10)
    values[name]['eligible'] = False
    assert gate.select(declared(), values)['decision'] == 'withhold_ineligible'


@pytest.mark.parametrize('missing', [True, False])
def test_missing_or_changed_original_archive_never_reaches_evaluator(tmp_path, monkeypatch, missing):
    manifest = json.loads(training.MANIFEST.read_text())
    path = tmp_path / (str(manifest['artifacts'][0]['id']) + '.zip')
    if not missing:
        path.write_bytes(b'authored invalid ZIP')
    def no_evaluation(*args):
        pytest.fail('Digest mismatch must precede evaluation')
    monkeypatch.setattr(training, 'reproduce', no_evaluation)
    with pytest.raises(Refused, match='archive missing' if missing else 'archive digest differs'):
        training.reproduce_training(tmp_path, tmp_path / 'output')


def test_prior_acquisition_is_separate_from_new_execution_cost():
    p = declared()
    prior = p['historical_training_acquisition']
    assert prior['campaigns'] == 8 and prior['scheduled_customer_windows'] == 168
    assert prior['actual_api_attempts'] == 16  # Authored input above, not live data.
    assert prior['billed_compute_cost'] is None
    result = gate.select(p, measurements())
    assert result['historical_training_acquisition'] == prior
    assert result['new_execution_accounting']['campaigns'] == 9
    assert result['new_execution_accounting']['scheduled_customer_windows'] == 189


def test_selection_timestamp_and_all_source_dependencies_are_bound():
    for invalid in (True, float('nan'), float('inf'), 0, -1):
        with pytest.raises(Refused, match='Invalid selection time'):
            gate.plan(declared()['selection'], invalid)
    spec = declared()['cases']['selected-heartbeat_final']
    for path in ('experiments/shadow_selection/training.py', 'experiments/contract_confirmation/audit.py',
                 'experiments/final_slot/negative.py', '.github/workflows/shadow-selection.yml'):
        assert spec['gate_sources'][path] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
    altered = copy.deepcopy(declared())
    altered['cases']['selected-heartbeat_final']['contract']['max_dispatches'] = 3
    with pytest.raises(Refused, match='changed shadow comparison'):
        gate.select(altered, measurements())


def test_workflow_is_single_attempt_and_keeps_setup_and_evidence_margin():
    workflow = yaml.safe_load(Path('.github/workflows/shadow-selection.yml').read_text())
    trigger = workflow.get('on', workflow.get(True))
    assert trigger['pull_request']['types'] == ['opened']
    assert set(trigger) == {'pull_request'}
    for name in ('freeze', 'compare'):
        steps = workflow['jobs'][name]['steps']
        assert steps[0]['run'] == 'test "$RUN_ATTEMPT" = 1'
    job = workflow['jobs']['compare']
    execution = next(s for s in job['steps'] if s.get('name') == 'Execute each frozen case once')
    assert execution['timeout-minutes'] == 30 < job['timeout-minutes'] == 40
