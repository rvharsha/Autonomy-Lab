"""Authored failure/accounting tests; only check_campaign supplies real evidence."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from autonomy_lab.campaign import Contract, exclusive, owner_alive, reconcile_pending
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import save

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def campaign(tmp_path):
    contract = json.loads((ROOT / 'scenarios/campaign-restart.json').read_text())
    save(tmp_path / 'contract.json', contract)
    save(tmp_path / 'window.json', {'start': 1000, 'end': 1120})
    save(tmp_path / 'source.json', {'authored_fixture': 'not_real_evidence'})
    save(tmp_path / 'identities-before.json', {'Service/inventory': 'authored-uid'})
    (tmp_path / 'samples').mkdir()
    (tmp_path / 'workers').mkdir()
    return tmp_path


def sample(root, *, started=1000, finished=1002, verdict='verified_success'):
    save(root / 'samples/0000.json', {'slot': 0, 'scheduled_at': 1000,
        'started_at': started, 'finished_at': finished,
        'verification': {'verdict': verdict, 'reasons': [], 'probes': []}})


def test_missing_calendar_slots_and_uncommitted_episodes_stay_unknown(campaign):
    sample(campaign)
    worker = campaign / 'workers/operator-authored'
    episode = worker / 'episode-authored'
    episode.mkdir(parents=True)
    save(worker / 'attempt.json', {'started_at': 1000})
    save(episode / 'attempt.json', {'started_at': 1001})
    result = scorecard(campaign)
    assert result['sample_counts'] == {'verified_success': 1, 'verified_failure': 0, 'unknown': 11}
    assert result['workers'][0]['episodes'][0]['outcome'] is None
    assert result['identities_unchanged'] is None
    assert result['measured_request_latency_seconds']['maximum'] is None
    assert result == scorecard(campaign)


@pytest.mark.parametrize('started,finished', [(1003, 1004), (1000, 1011), (999, 1002), (1001, 1000)])
def test_late_or_invalid_timing_never_credits_healthy_slot(campaign, started, finished):
    sample(campaign, started=started, finished=finished)
    row = scorecard(campaign)['samples'][0]
    assert row['observed_verdict'] == 'verified_success'
    assert row['coverage'] == 'late'
    assert row['verdict'] == 'unknown'


@pytest.mark.parametrize('verdict,expected', [('indeterminate', 'unknown'), ('verified_failure', 'verified_failure')])
def test_unknown_and_failed_observations_preserved(campaign, verdict, expected):
    sample(campaign, verdict=verdict)
    assert scorecard(campaign)['samples'][0]['verdict'] == expected


def test_calendar_cannot_be_restarted_or_backfilled(campaign):
    sample(campaign)
    save(campaign / 'window.json', {'start': 1010, 'end': 1130})
    with pytest.raises(ValueError, match='identity'):
        scorecard(campaign)


def test_extra_measurements_refused(campaign):
    save(campaign / 'samples/9999.json', {})
    with pytest.raises(ValueError, match='Unexpected'):
        scorecard(campaign)


def test_exclusive_operator_lock_rejects_second_owner(tmp_path):
    with exclusive(tmp_path / 'operator.lock'):
        with pytest.raises(BlockingIOError), exclusive(tmp_path / 'operator.lock'):
            pytest.fail('second operator acquired ownership')
    with exclusive(tmp_path / 'operator.lock'):
        pass  # Process release permits a new owner.


@pytest.mark.parametrize('fault', ['dead', 'expired', 'ending'])
def test_missing_owner_or_closed_campaign_refuses_new_work(tmp_path, fault):
    save(tmp_path / 'owner.json', {'pid': 123, 'identity': 'original', 'expires_at': 2000})
    if fault == 'ending':
        save(tmp_path / 'ending.json', {})
    with patch('autonomy_lab.campaign.time.time', return_value=2001 if fault == 'expired' else 1000), \
            patch('autonomy_lab.campaign.process_identity', return_value='replacement' if fault == 'dead' else 'original'):
        with pytest.raises(RuntimeError):
            owner_alive(tmp_path)


@pytest.mark.parametrize('key,value', [('duration_seconds', 120.0), ('max_dispatches', True),
                                     ('sample_interval_seconds', 7), ('sample_window_seconds', 9),
                                     ('max_operator_starts', 0), ('unknown_setting', 1)])
def test_contract_rejects_unbounded_or_ambiguous_schedule(campaign, key, value):
    contract = json.loads((campaign / 'contract.json').read_text())
    contract[key] = value
    with pytest.raises(ValidationError):
        Contract.model_validate(contract)


def test_restart_reconciles_all_unresolved_states_without_dispatch(campaign):
    from unittest.mock import Mock
    broker = Mock()
    rows = [{'operation_id': f'authored-{state}', 'status': state}
            for state in ['acknowledged', 'prepared', 'dispatching', 'uncertain', 'rejected']]
    with patch('autonomy_lab.campaign.operation_rows', return_value=rows):
        assert reconcile_pending(broker, campaign) == ['authored-prepared', 'authored-dispatching', 'authored-uncertain']
    assert [call.args[0] for call in broker.reconcile.call_args_list] == ['authored-prepared', 'authored-dispatching', 'authored-uncertain']
    broker.propose.assert_not_called()
    broker.resume_prepared.assert_not_called()


def test_operator_cli_readiness_surfaces_failed_child(tmp_path):
    from unittest.mock import Mock

    from autonomy_lab.campaign import wait_ready
    child = Mock()
    child.poll.return_value = 1
    with pytest.raises(RuntimeError, match='refused'):
        wait_ready(tmp_path, child)


def test_gate_preserves_original_failure_even_when_cleanup_and_reaping_fail(tmp_path):
    import importlib.util
    import subprocess
    from unittest.mock import Mock
    spec = importlib.util.spec_from_file_location('check_campaign', ROOT / 'scripts/check_campaign.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    directory = tmp_path / 'campaign'
    directory.mkdir()
    save(directory / 'environment.json', {'cluster': 'autolab-12345678', 'status': 'running'})
    owner = Mock()
    owner.poll.return_value = 0
    child = Mock()
    child.wait.side_effect = subprocess.TimeoutExpired('authored-child', 10)
    result = {'status': 'failed', 'error_type': 'OriginalAssertionError'}
    with patch.object(checker, 'stop_worker'), patch.object(checker, 'cleanup', side_effect=OSError):
        with pytest.raises(RuntimeError, match='finalization'):
            checker.finalize_gate(owner, [(tmp_path / 'worker', child)], directory, tmp_path, result)
    recorded = json.loads((tmp_path / 'result.json').read_text())
    assert recorded['error_type'] == 'OriginalAssertionError'
    assert {row['stage'] for row in recorded['cleanup_errors']} == {'reap_worker', 'cleanup'}
    assert 'finished_at' in recorded


def test_broker_journal_budget_survives_new_operator_instance(tmp_path):
    from test_broker import MemoryAdapter

    from autonomy_lab.broker import ActionBroker, BrokerPolicy
    from autonomy_lab.campaign import operation_rows
    adapter = MemoryAdapter()
    policy = BrokerPolicy('authored-campaign', 'lab-test', 'inventory', 'service-uid', max_dispatches=1)
    proposal = {'run_id': policy.run_id, 'operation_id': 'authored-first', 'namespace': policy.namespace,
                'service_name': 'inventory', 'service_uid': 'service-uid', 'resource_version': '10',
                'expected_target_port': 9999, 'target_port': 8080, 'evidence_ids': ['authored-evidence']}
    first = ActionBroker(tmp_path / 'operations.sqlite', policy, adapter)
    assert first.propose(proposal)['status'] == 'acknowledged'
    restarted = ActionBroker(tmp_path / 'operations.sqlite', policy, adapter)
    result = restarted.propose({**proposal, 'operation_id': 'authored-recurrence', 'resource_version': '11'})
    assert result['reason'] == 'budget_exhausted'
    assert len(adapter.patch_calls) == 1
    assert sum(row['budget_reserved'] for row in operation_rows(tmp_path)) == 1
