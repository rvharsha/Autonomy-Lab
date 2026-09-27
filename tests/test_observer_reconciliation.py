"""Authored gate tests, separate from the real original-evidence corruption controls."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

with patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1]), *sys.path]):
    from experiments.observer_reconciliation.gate import GROUPS, VARIANTS, config, decide
    from experiments.observer_reconciliation.run import export, verify_export

from autonomy_lab.experiments import planned_trials, validate_config
from autonomy_lab.procedures import Refused


def authored_rows():
    rows = []
    for group in GROUPS:
        for scenario in group:
            for variant in VARIANTS:
                for repetition in range(2):
                    healthy = scenario in {'observer_outage', 'observer_verifier'} or (
                        variant == 'desired_state' and scenario in {'observer_routing', 'observer_routing_verifier'})
                    rows.append({'scenario': scenario, 'variant': variant, 'repetition': repetition,
                                 'trial_id': f'authored-trial-{len(rows)}', 'service_uid': f'authored-service-{len(rows)}',
                                 'final_verdict': 'verified_success' if healthy else 'verified_failure', 'dispatches': 0})
    return rows


def test_full_matched_population_and_existing_maintained_policy():
    for shard in range(4):
        cfg = config(shard)
        validate_config(cfg)
        assert len(planned_trials(cfg)) == 8
        assert cfg['procedure_programs']['program'] == Path('procedures/bounded-refresh.json').read_text()
    assert decide(authored_rows())['decision'] == 'conventional_benefit_observed'
    assert decide(authored_rows())['experience_value_demonstrated'] is False


@pytest.mark.parametrize('mutation', ['tie', 'single_repeat', 'regression', 'unknown'])
def test_gains_do_not_hide_missing_replication_regression_or_unknowns(mutation):
    rows = authored_rows()
    target = next(r for r in rows if r['scenario'] == 'observer_routing' and r['variant'] == 'desired_state')
    if mutation == 'tie':
        for row in rows:
            if row['scenario'] == 'observer_routing':
                row['final_verdict'] = 'verified_success'
    elif mutation == 'single_repeat':
        target['final_verdict'] = 'verified_failure'
    elif mutation == 'regression':
        next(r for r in rows if r['scenario'] == 'observer_outage' and r['variant'] == 'desired_state')['final_verdict'] = 'verified_failure'
    else:
        target['final_verdict'] = 'indeterminate'
    assert decide(rows)['decision'] != 'conventional_benefit_observed'


@pytest.mark.parametrize('mutation', ['missing', 'duplicate_identity', 'wrong_population'])
def test_incomplete_or_aliased_population_is_refused(mutation):
    rows = authored_rows()
    if mutation == 'missing':
        rows.pop()
    elif mutation == 'duplicate_identity':
        rows[1]['trial_id'] = rows[0]['trial_id']
    else:
        rows[1]['scenario'] = 'invented'
    with pytest.raises(Refused):
        decide(rows)


def test_export_preserves_original_bytes_and_excludes_credentials(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'manifest.json').write_bytes(b'{"authored":true}\n')
    (original / 'kubeconfig').write_text('test-only private file, no credentials')
    exported = tmp_path / 'export'
    hashes = export(original, exported)
    verify_export(exported, hashes)
    assert not (exported / 'kubeconfig').exists()
    (exported / 'extra.json').write_text('{}')
    with pytest.raises(Refused):
        verify_export(exported, hashes)


def test_trial_labels_cannot_override_the_plan(tmp_path):
    from autonomy_lab.harness import save
    from experiments.observer_reconciliation.gate import evaluate_trial

    trial = {'scenario': 'observer_outage', 'variant': 'desired_state', 'status': 'recorded'}
    save(tmp_path / 'trial.json', trial)
    expected = {'scenario': 'observer_routing', 'variant': 'desired_state', 'repetition': 0}
    with pytest.raises(Refused, match='Trial identity differs from plan'):
        evaluate_trial(tmp_path, expected, {**expected, **trial}, {}, 'unused', 1)


def test_separate_retention_never_changes_original_failure(tmp_path, monkeypatch):
    from autonomy_lab.harness import save
    from experiments.observer_reconciliation import run as runner

    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    original = tmp_path / 'artifacts/experiment-1234abcd'
    original.mkdir(parents=True)
    (original / 'accounting.json').write_text('{"authored_partial_attempt": true}')
    (original / 'trial-001').mkdir()
    (original / 'trial-001/operations.sqlite-journal').write_bytes(b'authored hot-journal bytes')
    destination = tmp_path / 'retention'
    destination.mkdir()
    ledger = {'status': 'failed', 'experiment_id': '1234abcd'}
    save(destination / 'result.json', ledger)
    before = (destination / 'result.json').read_bytes()
    runner.retain_after_step(destination)
    assert (destination / 'result.json').read_bytes() == before
    assert (destination / 'retained-after-step/accounting.json').read_bytes() == (original / 'accounting.json').read_bytes()
    assert (destination / 'retained-after-step/trial-001/operations.sqlite-journal').read_bytes() == b'authored hot-journal bytes'


def test_retention_records_setup_failure_without_inventing_an_attempt(tmp_path):
    from autonomy_lab.campaign import read
    from experiments.observer_reconciliation.run import retain_after_step

    retain_after_step(tmp_path)
    assert read(tmp_path / 'retained-after-step.json')['status'] == 'no_live_ledger'
    assert not (tmp_path / 'result.json').exists()
