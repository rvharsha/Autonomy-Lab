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


def test_readonly_wal_reader_cannot_add_sidecars_to_retained_evidence(tmp_path, monkeypatch):
    import hashlib
    import sqlite3
    from contextlib import closing

    from experiments.observer_reconciliation import run as runner

    # Real SQLite behavior, not a mocked filesystem or a workload measurement.
    source = tmp_path / 'original'
    source.mkdir()
    database = source / 'operations.sqlite'
    with closing(sqlite3.connect(database)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE observations (value INTEGER)')
        db.execute('INSERT INTO observations VALUES (7)')
        db.commit()
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}

    def reader(directory, shard, frozen_at):
        with closing(sqlite3.connect(f'file:{directory / "operations.sqlite"}?mode=ro', uri=True)) as db:
            assert db.execute('SELECT value FROM observations').fetchone() == (7,)
            assert (directory / 'operations.sqlite-shm').exists()
        return ['authored SQLite regression result']

    monkeypatch.setattr(runner, 'evaluate', reader)
    assert runner.audit_copy(source, 0, 1) == ['authored SQLite regression result']
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()} == before


@pytest.mark.parametrize('mutation', ['unchanged', 'changed_original', 'missing_original', 'extra_file',
                                      'nonempty_wal', 'changed_backup', 'different_failure'])
def test_recovery_accepts_only_the_exact_reader_side_effect(tmp_path, mutation):
    import hashlib

    from autonomy_lab.harness import save
    from experiments.observer_reconciliation.recover import original_inputs

    # Authored byte-guard fixture. The full replay also requires real SQLite,
    # original ZIP digests, source pins and complete independent trial evaluation.
    raw = tmp_path / 'raw'
    backup = tmp_path / 'retained-after-step'
    expected = {}
    for index in range(1, 9):
        name = f'trial-{index:03d}/operations.sqlite'
        for root in (raw, backup):
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_bytes(b'authored integrity fixture; not a database')
        expected[name] = hashlib.sha256((raw / name).read_bytes()).hexdigest()
        (raw / (name + '-wal')).write_bytes(b'')
        (raw / (name + '-shm')).write_bytes(bytes(32768))
    ledger = {'status': 'failed', 'stage': 'independent_reproduction', 'error_type': 'Refused',
              'rows': [None] * 8, 'raw_sha256': expected}
    save(tmp_path / 'retained-after-step.json', {'original_ledger_status': 'failed', 'raw_sha256': expected})
    first = next(iter(expected))
    if mutation == 'changed_original':
        (raw / first).write_bytes(b'changed')
    elif mutation == 'missing_original':
        (raw / first).unlink()
    elif mutation == 'extra_file':
        (raw / 'unrelated.json').write_text('{}')
    elif mutation == 'nonempty_wal':
        (raw / (first + '-wal')).write_bytes(b'uncommitted data')
    elif mutation == 'changed_backup':
        (backup / first).write_bytes(b'changed')
    elif mutation == 'different_failure':
        ledger['stage'] = 'execution'
    if mutation == 'unchanged':
        assert original_inputs(tmp_path, ledger)['original_status'] == 'failed'
    else:
        with pytest.raises(ValueError):
            original_inputs(tmp_path, ledger)
