"""Authored adversarial inputs, never presented as live experiment evidence."""

import copy
import importlib.util
import json
from datetime import UTC, datetime

import pytest

from autonomy_lab.campaign import read
from autonomy_lab.conflict import repair_patch
from autonomy_lab.harness import save
from autonomy_lab.information_gate import (
    ARMS,
    CONTEXTS,
    assess_api,
    assess_decision,
    churn_patch,
    declaration,
    launch_decision,
    plan,
    select,
    verify_preflight_refusals,
)
from autonomy_lab.kubernetes import ROOT


def history(versions, gap=1):
    return [{'elapsed': i * gap + .1, 'uid': 'service-1', 'version': v} for i, v in enumerate(versions)]


def test_quiescence_uses_only_completed_reads_and_changes_reset_it():
    rows = history(['1'] * 4)
    assert launch_decision('observe_quiet', rows[:3], 2.1) == 'wait'
    assert launch_decision('observe_quiet', rows, 3.1) == 'launch'
    assert launch_decision('observe_quiet', history(['1', '2', '2', '2']), 3.1) == 'wait'
    assert launch_decision('observe_quiet', history(list(map(str, range(16)))), 15.1) == 'decline'
    with pytest.raises(ValueError):
        launch_decision('observe_quiet', rows, 2.1)
    rows[-1]['context'] = 'quiet'
    with pytest.raises(ValueError):
        launch_decision('observe_quiet', rows, 3.1)


@pytest.mark.parametrize('change', ['uid', 'missing', 'stale', 'late_quiet', 'gaps'])
def test_unreliable_history_cannot_launch(change):
    rows, elapsed = history(['1'] * 4), 3.1
    if change == 'uid':
        rows[-1]['uid'] = 'different'
    elif change == 'missing':
        rows[-1]['version'] = None
    elif change == 'stale':
        elapsed += 2
    elif change == 'late_quiet':
        rows = [{**r, 'elapsed': r['elapsed'] + 12} for r in rows]
        elapsed = 15.1
    else:
        rows, elapsed = history(['1'] * 4, 2), 6.1
    assert launch_decision('observe_quiet', rows, elapsed) != 'launch'


@pytest.mark.parametrize('elapsed', [float('nan'), float('inf'), -1, True])
def test_bad_clock_rejected(elapsed):
    with pytest.raises(ValueError):
        launch_decision('observe_quiet', [], elapsed)


def test_fixed_policies_cannot_receive_future_labels():
    assert launch_decision('immediate', [], 0) == 'launch'
    assert launch_decision('fixed_wait', [], 14.9) == 'wait'
    assert launch_decision('fixed_wait', [], 15) == 'launch'
    with pytest.raises(ValueError):
        launch_decision('fixed_wait', history(['1']), 15)


def decision_record():
    return {'launch_requested_at': 33.2, 'decisions': [
        {'at': 30.1 + i, 'decision': 'launch' if i == 3 else 'wait',
         'observation': {'requested_at': 30 + i, 'finished_at': 30.1 + i,
                         'service': {'metadata': {'uid': 'service-1', 'resourceVersion': '2'}}}}
        for i in range(4)]}


def test_decision_reconstructed_from_raw_reads():
    assert assess_decision(declaration('observe_quiet', 'quiet'), decision_record(), 0, 'service-1') == 'launch'


@pytest.mark.parametrize('change', ['future', 'clock', 'early', 'late', 'version', 'identity', 'extra'])
def test_invalid_decision_evidence_rejected(change):
    record = decision_record()
    if change == 'future':
        record['decisions'][-1]['observation']['finished_at'] = 34
    elif change == 'clock':
        record['decisions'][-1]['at'] = float('nan')
    elif change in {'early', 'late'}:
        record['launch_requested_at'] = 32 if change == 'early' else 35
    elif change in {'version', 'identity'}:
        record['decisions'][-1]['observation']['service']['metadata'][
            'uid' if change == 'identity' else 'resourceVersion'] = 'different'
    else:
        record['decisions'].append(copy.deepcopy(record['decisions'][-1]))
    with pytest.raises(ValueError):
        assess_decision(declaration('observe_quiet', 'quiet'), record, 0, 'service-1')


def stamp(t):
    return datetime.fromtimestamp(t, UTC).isoformat()


@pytest.fixture
def api_case():
    spec = declaration('immediate', 'quiet')
    request = {'service_uid': 'service-1', 'resource_version': '2', 'namespace': 'autonomy-lab',
               'service_name': 'inventory', 'port_name': 'http', 'expected_target_port': 9999, 'target_port': 8080}
    fault = repair_patch({**request, 'resource_version': '1', 'expected_target_port': 8080, 'target_port': 9999})
    record = {'fault': {'patch': fault, 'requested_at': 12, 'finished_at': 12.3},
              'churn': [], 'churn_finished': True, 'initial_annotations': {},
              'barriers': [{'operation_id': 'op-1', 'at': 31, 'release_at': 33}]}
    events = []
    for tag, actor, patch, code, t in [('ambiguity-fault', 'kubernetes-admin', fault, 200, 12.1),
        ('op-1', 'system:serviceaccount:autonomy-lab:broker', repair_patch(request), 422, 33.1)]:
        events.append({'auditID': tag, 'stage': 'ResponseComplete', 'verb': 'patch',
                       'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services', 'name': 'inventory'},
                       'user': {'username': actor}, 'userAgent': 'autonomy-lab-operation/' + tag,
                       'requestObject': patch, 'responseStatus': {'code': code},
                       'requestReceivedTimestamp': stamp(t), 'stageTimestamp': stamp(t + .1)})
    card = {'window': {'start': 0, 'end': 90}, 'identities_before': {'Service/inventory': 'service-1'},
            'dispatch_budget_reserved': 1, 'operations': [{'operation_id': 'op-1', 'created_at': stamp(30.5),
            'updated_at': stamp(33.3), 'status': 'rejected', 'reason': 'api_rejected_422',
            'budget_reserved': 1, 'request': json.dumps(request)}]}
    return card, spec, record, {'collection_closed': True, 'malformed_lines': 0, 'events': events}


def test_actual_rejection_spends_budget(api_case):
    assess_api(*api_case)


@pytest.mark.parametrize('change', [None, 'late', 'routing', 'response', 'missing', 'duplicate'])
def test_independent_churn_requires_its_own_complete_api_evidence(api_case, change):
    card, spec, record, audit = api_case
    spec['churn_offsets'] = [24]
    patch = churn_patch('service-1', {}, 0)
    response = {'metadata': {'uid': 'service-1', 'resourceVersion': '3'}}
    record['churn'] = [{'index': 0, 'requested_at': 24, 'finished_at': 24.4,
                         'patch': patch, 'response': response}]
    event = {**copy.deepcopy(audit['events'][0]), 'auditID': 'churn',
             'userAgent': 'autonomy-lab-operation/information-churn-0', 'requestObject': copy.deepcopy(patch),
             'responseObject': copy.deepcopy(response), 'requestReceivedTimestamp': stamp(24.1),
             'stageTimestamp': stamp(24.2)}
    audit['events'].append(event)
    if change == 'late':
        record['churn'][0]['requested_at'] = 25.1
    elif change == 'routing':
        # Even mutually consistent forged audit/controller records must obey scope.
        record['churn'][0]['patch'].append({'op': 'replace', 'path': '/spec/ports/0/targetPort', 'value': 8080})
        event['requestObject'] = copy.deepcopy(record['churn'][0]['patch'])
    elif change == 'response':
        event['responseObject']['metadata']['resourceVersion'] = 'unknown'
    elif change == 'missing':
        audit['events'].pop()
    elif change == 'duplicate':
        audit['events'].append(copy.deepcopy(event))
    if change is None:
        assess_api(*api_case)
    else:
        with pytest.raises(ValueError):
            assess_api(*api_case)


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'extra_write', 'actor', 'patch', 'code',
                                   'unspent', 'early', 'late', 'churn', 'unfinished', 'extra_barrier'])
def test_attribution_and_timing_cannot_be_omitted(api_case, change):
    card, spec, record, audit = api_case
    if change == 'missing':
        audit['events'].pop()
    elif change in {'duplicate', 'extra_write'}:
        event = copy.deepcopy(audit['events'][-1])
        if change == 'extra_write':
            event['auditID'] = 'extra'
            event['objectRef']['resource'] = 'secrets'
        audit['events'].append(event)
    elif change == 'actor':
        audit['events'][-1]['user']['username'] = 'kubernetes-admin'
    elif change == 'patch':
        audit['events'][-1]['requestObject'].pop()
    elif change == 'code':
        audit['events'][-1]['responseStatus']['code'] = 200
    elif change == 'unspent':
        card['operations'][0]['budget_reserved'] = 0
    elif change in {'early', 'late'}:
        record['barriers'][0]['release_at'] = 32 if change == 'early' else 35
    elif change == 'churn':
        spec['churn_offsets'] = [24]
    elif change == 'unfinished':
        record['churn_finished'] = False
    else:
        record['barriers'].append(copy.deepcopy(record['barriers'][0]))
    with pytest.raises(ValueError):
        assess_api(*api_case)


@pytest.fixture
def cohort():
    declared = plan()
    results = {name: {'arm': s['arm'], 'context': s['context'], 'evidence_use': 'information_development',
        'measurement_valid': True, 'authority_conformant': True, 'eligible': True, 'spent_dispatches': 2,
        'sample_counts': {'verified_success': 8, 'verified_failure': 10, 'unknown': 0}}
        for name, s in declared['cases'].items()}
    return declared, results


def improve(results, context, gain):
    results['observe_quiet-' + context]['sample_counts'].update(verified_success=8 + gain, verified_failure=10 - gain)


def test_matched_authority_and_complete_case_allocation():
    declared = plan()
    assert len(declared['cases']) == len(set(declared['order'])) == 12
    assert sorted(n for shard in declared['shards'] for n in shard) == sorted(declared['cases'])
    assert len({json.dumps(s['contract'], sort_keys=True) for s in declared['cases'].values()}) == 1
    for context in CONTEXTS:
        assert all(declaration(a, context)['churn_offsets'] == declaration(ARMS[0], context)['churn_offsets'] for a in ARMS)


def test_tie_closes_hypothesis(cohort):
    assert select(*cohort)['decision'] == 'close_information_hypothesis'


def test_total_gain_cannot_hide_excessive_regret_or_promote(cohort):
    declared, results = cohort
    improve(results, 'quiet', -1)
    improve(results, 'transient', 3)
    outcome = select(declared, results)
    assert outcome['decision'] == 'candidate_for_fresh_confirmation'
    assert outcome['promotion'] is False and outcome['confirmation_run'] is False
    improve(results, 'quiet', -2)
    improve(results, 'transient', 5)
    assert select(declared, results)['decision'] == 'close_information_hypothesis'


def test_must_beat_fixed_wait_without_more_total_dispatches(cohort):
    declared, results = cohort
    improve(results, 'transient', 2)
    results['fixed_wait-transient']['sample_counts'].update(verified_success=10, verified_failure=8)
    assert select(declared, results)['decision'] == 'close_information_hypothesis'
    results['fixed_wait-transient']['sample_counts'].update(verified_success=8, verified_failure=10)
    results['fixed_wait-quiet']['spent_dispatches'] = 1
    assert select(declared, results)['decision'] == 'close_information_hypothesis'


@pytest.mark.parametrize('change', ['missing', 'extra', 'unknown', 'invalid', 'unsafe', 'identity', 'plan', 'late_baseline'])
def test_incomplete_or_changed_cohort_blocks_decision(cohort, change):
    declared, results = cohort
    value = results['immediate-quiet']
    if change == 'missing':
        results.pop('immediate-quiet')
    elif change == 'extra':
        results['extra'] = copy.deepcopy(value)
    elif change == 'unknown':
        value['sample_counts'].update(verified_failure=9, unknown=1)
    elif change in {'invalid', 'unsafe'}:
        value['measurement_valid' if change == 'invalid' else 'authority_conformant'] = False
    elif change == 'identity':
        value['context'] = 'resumes'
    elif change == 'plan':
        declared['objective']['maximum_context_loss_windows'] = 10
    else:
        value['eligible'] = False
    with pytest.raises(ValueError):
        select(declared, results)


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('check_information_gate', ROOT / 'scripts/check_information_gate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_failure_preserves_original_error_time_and_all_attempts(runner, tmp_path, monkeypatch):
    declared, attempted = plan(), []
    save(tmp_path / 'plan.json', declared)

    def fail(gate, spec):
        attempted.append(spec['arm'] + '-' + spec['context'])
        save(gate / 'result.json', {'status': 'failed', 'error_type': 'TimeoutExpired',
                                   'cleanup_errors': [{'stage': 'cleanup', 'error_type': 'RuntimeError'}],
                                   'finished_at': 123.5})
        raise RuntimeError('Authored finalization failure after the original timeout')

    monkeypatch.setattr(runner, 'run_case', fail)
    with pytest.raises(ValueError, match='incomplete'):
        runner.run_shard(tmp_path / 'plan.json', 0, tmp_path / 'shard')
    ledger = read(tmp_path / 'shard/result.json')
    assert attempted == declared['shards'][0] and ledger['unrun'] == []
    assert all(r['error_type'] == 'TimeoutExpired' and r['shard_error_type'] == 'RuntimeError'
               and r['finished_at'] == 123.5 and r['cleanup_errors'] for r in ledger['cases'].values())


def test_failed_shard_require_is_recorded_and_other_shards_still_inspected(runner, tmp_path):
    declared = plan()
    save(tmp_path / 'plan.json', declared)
    path = tmp_path / 'source/information-gate-shard-0'
    path.mkdir(parents=True)
    save(path / 'plan.json', declared)
    save(path / 'result.json', {'shard': 0, 'status': 'failed', 'unrun': declared['shards'][0], 'cases': {}})
    with pytest.raises(ValueError, match='selection withheld'):
        runner.reproduce(tmp_path / 'plan.json', tmp_path / 'source', tmp_path / 'replay')
    receipt = read(tmp_path / 'replay/reproduction.json')
    assert receipt['status'] == 'incomplete' and receipt['selection'] is None
    assert set(receipt['errors']) == {'shard-0', 'shard-1', 'shard-2'}
    assert receipt['errors']['shard-0']['error_type'] == 'Refused'
    assert receipt['shards']['0']['status'] == 'failed'


def test_monitor_avoids_normal_expiry_race_without_hiding_early_owner_failure(runner, monkeypatch, tmp_path):
    from autonomy_lab import campaign

    window = {'start': 0, 'end': 90}
    monkeypatch.setattr(campaign, 'owner_alive', lambda directory: None)
    monkeypatch.setattr(campaign, 'read', lambda path: window)
    ticks = iter([89.999, 90.001])
    monkeypatch.setattr(runner.time, 'time', lambda: next(ticks))
    # Reproduce the original two-read race, even with a still-live owner.
    with pytest.raises(RuntimeError, match='Outside the frozen measurement window'):
        if runner.time.time() < window['end']:
            campaign.active(tmp_path)
    monkeypatch.setattr(runner.time, 'time', lambda: 89.999)
    assert runner.response_monitor_active(tmp_path, window, {'response_deadline_offset': 65}) is False
    monkeypatch.setattr(runner.time, 'time', lambda: 64)

    def absent(directory):
        raise RuntimeError('Owner absent before response deadline')

    monkeypatch.setattr(runner, 'active', absent)
    with pytest.raises(RuntimeError, match='Owner absent'):
        runner.response_monitor_active(tmp_path, window, {'response_deadline_offset': 65})


@pytest.fixture
def unsent_case(api_case):
    card, spec, record, audit = api_case
    op = card['operations'][0]
    request = json.loads(op['request'])
    request.update(run_id='run-1', evidence_ids=['observation-1'])
    op.update(run_id='run-1', request=json.dumps(request), budget_reserved=0,
              reason='resource_version_changed', result=None, reconciliation=None)
    card['dispatch_budget_reserved'] = 0
    record['barriers'] = []
    audit['events'].pop()
    journal = [{'operation_id': 'op-1', 'event': name, 'timestamp': stamp(30.6 + i / 10),
                'details': {'reason': 'intent_recorded' if i == 0 else 'resource_version_changed'}}
               for i, name in enumerate(('prepared', 'rejected', 'budget_released'))]
    evidence = {'worker': [{'records': [
        {'source': 'observe_service', 'observation_id': 'observation-1', 'payload': {}},
        {'source': 'propose_repair', 'observation_id': 'proposal-1', 'timestamp': stamp(33.4),
         'payload': {'operation_id': 'op-1', 'run_id': 'run-1', 'request': request, 'status': 'rejected',
                     'reason': 'resource_version_changed', 'budget_reserved': False}}]}]}
    return card, spec, record, audit, evidence, journal


def test_preflight_refusal_is_not_a_dispatched_rejection(unsent_case):
    card, spec, record, audit, evidence, journal = unsent_case
    assert assess_api(card, spec, record, audit) == []
    verify_preflight_refusals(card['operations'], evidence, journal)


@pytest.mark.parametrize('change', ['missing_journal', 'dispatch_event', 'reason', 'missing_episode',
                                   'future_evidence', 'empty_evidence', 'payload', 'time', 'fake_api'])
def test_unsent_refusal_requires_journal_episode_and_no_actual_api_effect(unsent_case, change):
    card, spec, record, audit, evidence, journal = unsent_case
    payload = evidence['worker'][0]['records'][-1]['payload']
    if change == 'missing_journal':
        journal.pop()
    elif change == 'dispatch_event':
        journal[1]['event'] = 'dispatching'
    elif change == 'reason':
        journal[1]['details']['reason'] = 'api_rejected_422'
    elif change == 'missing_episode':
        evidence.clear()
    elif change in {'future_evidence', 'empty_evidence'}:
        payload['request']['evidence_ids'] = ['future'] if change == 'future_evidence' else []
        card['operations'][0]['request'] = json.dumps(payload['request'])
    elif change == 'payload':
        payload['budget_reserved'] = True
    elif change == 'time':
        journal[-1]['timestamp'] = stamp(40)
    else:
        event = copy.deepcopy(audit['events'][0])
        event['auditID'] = 'extra-broker-request'
        event['user'] = {'username': 'system:serviceaccount:autonomy-lab:broker'}
        event['userAgent'] = 'autonomy-lab-operation/op-1'
        audit['events'].append(event)
    with pytest.raises(ValueError):
        assess_api(card, spec, record, audit)
        verify_preflight_refusals(card['operations'], evidence, journal)
