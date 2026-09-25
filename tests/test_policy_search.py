"""Authored adversarial fixtures for selection; never live experiment evidence."""

import copy
import importlib.util
import itertools
import json
import sqlite3
from pathlib import Path

import pytest

from autonomy_lab.campaign import operation_rows, read
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.policy_search import (
    BASELINE,
    CONTEXTS,
    SHARDS,
    plan,
    programs,
    require_controller_separation,
    select,
)
from autonomy_lab.procedure import CHOICES


@pytest.fixture
def selection_case():
    declared = plan()
    results = {}
    for name, spec in declared['cases'].items():
        results[name] = {'policy': spec['policy'], 'context': spec['context'],
                         'program_version': spec['program_pin']['version'],
                         'evidence_use': 'finite_development', 'measurement_valid': True,
                         'authority_conformant': True, 'eligible': True, 'spent_dispatches': 2,
                         'sample_counts': {'verified_success': 10, 'verified_failure': 11, 'unknown': 0}}
    return declared, results


def healthy(results, policy, context, count):
    results[policy + '-' + context]['sample_counts'].update(verified_success=count, verified_failure=21 - count)


def test_exhaustive_bytes_no_static_equivalence_pruning():
    actual = programs()
    assert len(actual) == len(set(actual.values())) == 8
    assert {tuple(json.loads(raw)[key] for key in CHOICES) for raw in actual.values()} == set(itertools.product(*CHOICES.values()))
    frozen = plan()
    assert len(frozen['cases']) == len(frozen['order']) == 16
    assert len(frozen['shards']) == SHARDS
    assert sorted(itertools.chain.from_iterable(frozen['shards'])) == sorted(frozen['cases'])
    contracts = []
    for spec in frozen['cases'].values():
        contract = copy.deepcopy(spec['contract'])
        contract.pop('procedure_program')
        contracts.append(contract)
    assert all(c == contracts[0] for c in contracts)
    assert frozen['uncovered_choices'] == ['backend_unavailable']
    assert frozen['cost_budget']['proposer_requests'] == 0


def test_ties_keep_maintained_policy_without_execution_authority(selection_case):
    value = select(*selection_case)
    assert value['selected'] == BASELINE and value['qualifying_challengers'] == []
    assert not value['selection_confers_authority'] and not value['promotion']


def test_aggregate_gain_cannot_hide_a_context_regression(selection_case):
    declared, results = selection_case
    healthy(results, 'p000', 'stable', 9)
    healthy(results, 'p000', 'continuing', 21)
    assert select(declared, results)['selected'] == BASELINE


def test_dispatch_regression_disqualifies_an_outcome_gain(selection_case):
    declared, results = selection_case
    for context in CONTEXTS:
        results[BASELINE + '-' + context]['spent_dispatches'] = 1
    healthy(results, 'p000', 'stable', 11)
    assert select(declared, results)['selected'] == BASELINE


def test_strict_gain_with_no_regression_requires_confirmation(selection_case):
    declared, results = selection_case
    healthy(results, 'p010', 'stable', 11)
    value = select(declared, results)
    assert value['selected'] == 'p010'
    assert value['decision'] == 'candidate_requires_fresh_confirmation'
    assert not value['confirmation_run'] and not value['promotion']


def test_multiple_improvements_use_frozen_canonical_order(selection_case):
    declared, results = selection_case
    for policy in ('p010', 'p001'):
        healthy(results, policy, 'stable', 11)
    assert select(declared, dict(reversed(list(results.items()))))['selected'] == 'p001'


def test_late_candidate_cannot_qualify_but_does_not_erase_measurements(selection_case):
    declared, results = selection_case
    healthy(results, 'p000', 'stable', 21)
    results['p000-continuing']['eligible'] = False
    assert select(declared, results)['selected'] == BASELINE
    assert select(declared, results)['evaluations']['p000-stable']['sample_counts']['verified_success'] == 21


@pytest.mark.parametrize('change', ['missing', 'extra', 'unsafe', 'invalid', 'unknown', 'boolean_count',
                                   'negative', 'total', 'version', 'context', 'policy', 'purpose',
                                   'budget', 'budget_bool', 'eligibility', 'baseline_ineligible', 'plan'])
def test_incomplete_or_tampered_inputs_block_selection(selection_case, change):
    declared, results = selection_case
    value = results['p000-stable']
    if change == 'missing':
        del results['p000-stable']
    elif change == 'extra':
        results['extra'] = copy.deepcopy(value)
    elif change in {'unsafe', 'invalid'}:
        value['authority_conformant' if change == 'unsafe' else 'measurement_valid'] = False
    elif change == 'unknown':
        value['sample_counts'].update(verified_failure=10, unknown=1)
    elif change == 'boolean_count':
        value['sample_counts']['unknown'] = False
    elif change == 'negative':
        value['sample_counts'].update(verified_success=-1, verified_failure=22)
    elif change == 'total':
        value['sample_counts']['verified_success'] = 11
    elif change in {'version', 'context', 'policy', 'purpose'}:
        value[{'version': 'program_version', 'purpose': 'evidence_use'}.get(change, change)] = 'different'
    elif change in {'budget', 'budget_bool'}:
        value['spent_dispatches'] = 3 if change == 'budget' else True
    elif change == 'eligibility':
        value['eligible'] = 1
    elif change == 'baseline_ineligible':
        results[BASELINE + '-stable']['eligible'] = False
    else:
        declared['selection_rule'] = 'choose a favorable subset'
    with pytest.raises(ValueError):
        select(declared, results)


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('check_policy_search', ROOT / 'scripts/check_policy_search.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_attempts_are_not_retried_or_silently_dropped(runner, tmp_path, monkeypatch):
    declared = plan()
    save(tmp_path / 'plan.json', declared)
    attempted = []

    def fail(gate, spec, *unused):
        attempted.append(spec['policy'] + '-' + spec['context'])
        raise ValueError('Authored test failure')

    monkeypatch.setattr(runner, 'run_case', fail)
    with pytest.raises(ValueError, match='incomplete'):
        runner.run_shard(tmp_path / 'plan.json', 0, tmp_path / 'shard')
    ledger = read(tmp_path / 'shard/result.json')
    assert attempted == declared['shards'][0]
    assert ledger['unrun'] == [] and ledger['status'] == 'failed'
    assert all(c['status'] == 'failed' for c in ledger['cases'].values())


def test_missing_archives_withhold_selection_and_preserve_errors(runner, tmp_path):
    save(tmp_path / 'plan.json', plan())
    with pytest.raises(ValueError, match='selection withheld'):
        runner.reproduce(tmp_path / 'plan.json', tmp_path / 'missing', tmp_path / 'replay')
    receipt = read(tmp_path / 'replay/reproduction.json')
    assert receipt['status'] == 'incomplete' and receipt['selection'] is None
    assert len(receipt['errors']) == SHARDS


def test_passing_summaries_cannot_replace_raw_evidence(runner, tmp_path, monkeypatch):
    declared = plan()
    save(tmp_path / 'plan.json', declared)
    for shard in range(SHARDS):
        path = tmp_path / 'source' / f'policy-search-shard-{shard}'
        path.mkdir(parents=True)
        save(path / 'plan.json', declared)
        save(path / 'result.json', {'shard': shard, 'status': 'passed', 'unrun': [],
                                   'cases': {c: {'status': 'passed'} for c in declared['shards'][shard]}})
        for case in declared['shards'][shard]:
            gate = path / 'cases' / case
            gate.mkdir(parents=True)
            save(gate / 'result.json', {'status': 'passed'})

    def missing_raw(gate):
        raise ValueError('Authored missing raw evidence')

    monkeypatch.setattr(runner, 'evaluate', missing_raw)
    with pytest.raises(ValueError, match='selection withheld'):
        runner.reproduce(tmp_path / 'plan.json', tmp_path / 'source', tmp_path / 'replay')
    receipt = read(tmp_path / 'replay/reproduction.json')
    assert receipt['selection'] is None and len(receipt['errors']) == 16


def empty_journal(gate):
    directory = gate / 'campaign'
    directory.mkdir()
    with sqlite3.connect(directory / 'operations.sqlite') as db:
        db.execute('CREATE TABLE operations (created_at TEXT, operation_id TEXT)')


def test_relative_destination_reaches_real_readonly_sqlite_export(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save(Path('plan.json'), plan())
    exported = []

    def export(gate, *unused):
        empty_journal(gate)
        exported.append(operation_rows(gate / 'campaign'))
        save(gate / 'result.json', {'status': 'passed'})

    monkeypatch.setattr(runner, 'run_case', export)
    runner.run_shard(Path('plan.json'), 0, Path('relative-shard'))
    assert exported == [[], [], [], []]


def test_relative_replay_source_reaches_real_readonly_sqlite_export(runner, selection_case, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    declared, results = selection_case
    save(Path('plan.json'), declared)
    for shard in range(SHARDS):
        path = Path('source') / f'policy-search-shard-{shard}'
        path.mkdir(parents=True)
        save(path / 'plan.json', declared)
        save(path / 'result.json', {'shard': shard, 'status': 'passed', 'unrun': [],
                                   'cases': {c: {'status': 'passed'} for c in declared['shards'][shard]}})
        for case in declared['shards'][shard]:
            gate = path / 'cases' / case
            gate.mkdir(parents=True)
            empty_journal(gate)
            save(gate / 'result.json', {'status': 'passed'})
            for label in ('a', 'b'):
                save(gate / f'evaluation-{label}.json', results[case])

    def export(gate):
        assert operation_rows(gate / 'campaign') == []
        return results[gate.name]

    monkeypatch.setattr(runner, 'evaluate', export)
    receipt = runner.reproduce(Path('plan.json'), Path('source'), Path('replay'))
    assert receipt['status'] == 'complete' and receipt['selection']['selected'] == BASELINE


@pytest.mark.parametrize('interval', [(80.06, 80.09), (79, 80.01), (81.18, 82), (79, 82)])
def test_controller_transition_overlapping_any_part_of_window_invalidates_comparison(interval):
    with pytest.raises(ValueError, match='overlaps'):
        require_controller_separation([{'started_at': 80.01, 'finished_at': 81.18}],
                                      {'external_restore': {'requested_at': interval[0], 'finished_at': interval[1]}})


def test_controller_transition_between_windows_is_valid():
    require_controller_separation([{'started_at': 80.01, 'finished_at': 81.18},
                                   {'started_at': 90.01, 'finished_at': 91.18}],
                                  {'external_restore': {'requested_at': 85.06, 'finished_at': 85.09}})
    spec = plan()['cases']['p111-continuing']
    assert spec['external_restore_offset'] == 85 and spec['second_fault_offset'] == 125
