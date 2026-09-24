"""Authored failure-path and scoring fixtures; never experimental workload evidence."""

import copy
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from test_ambiguity import authored, stamp

from autonomy_lab.campaign_stop import assess_stop
from autonomy_lab.harness import save
from autonomy_lab.telemetry import assess_telemetry, declaration

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(ROOT / 'scripts'), *sys.path]):
        spec.loader.exec_module(module)
    return module


def measurements(inputs, count, failed, missing):
    samples, raw = [], {}
    for slot in range(count):
        verdict = 'unknown' if slot in missing else 'verified_failure' if slot in failed else 'verified_success'
        row = {'slot': slot, 'scheduled_at': 1000 + slot * 10, 'verdict': verdict,
               'coverage': 'missing' if slot in missing else 'on_time'}
        if slot not in missing:
            row.update(started_at=1000 + slot * 10, finished_at=1002 + slot * 10,
                       reasons=['quote available-single: HTTP 503 (expected 200)'] if slot in failed else [])
            raw[slot] = {'verification': {'verdict': verdict, 'reasons': row['reasons'], 'probes': [{'observations': {
                'quote_control': {'status_code': 200}, 'inventory_control': {'status_code': 200},
                'quotes': [{'case_id': 'available-single', 'status_code': 503 if slot in failed else 200}]}}]}}
        samples.append(row)
    inputs['card']['samples'] = samples
    inputs['card']['sample_counts'] = {v: sum(s['verdict'] == v for s in samples) for v in ['verified_success', 'verified_failure', 'unknown']}
    inputs['raw'] = raw
    inputs.pop('raw_samples', None)


def telemetry_inputs():
    inputs = authored('unchanged')
    record, card = inputs['record'], inputs['card']
    inputs['spec'] = declaration()
    card['window']['end'] = 1210
    measurements(inputs, 21, {9, 10}, {3, 4, 5, 6})
    for key in ['initial_stop_requested_at', 'initial_stopped_at', 'repair_requested_at', 'repair_ready_at', 'kill_requested_at', 'stopped_at']:
        record[key] += 60
    record.update(paused_at=1025, resumed_at=1065, pause_state='Ts', observer='observer-original', initial_worker='operator-original',
                  observer_identity_before='authored-start', observer_identity_after='authored-start',
                  samples_before_pause={f'{i:04d}.json': f'authored-hash-{i}' for i in range(3)},
                  restart_requested_at=1124.1, resumed_ready_at=1124.5)
    card['sample_sha256'] = dict(record['samples_before_pause'])
    record['fault']['requested_at'] += 60
    record['fault']['finished_at'] += 60
    rules = [{'apiGroups': [''], 'resources': ['services'], 'resourceNames': ['inventory'], 'verbs': ['get', 'patch']}]
    record['revocation'] = {'requested_at': 1114.1, 'finished_at': 1114.6, 'before_rules': rules,
                            'after_rules': [{**rules[0], 'verbs': ['patch']}]}
    op = card['operations'][0]
    op['created_at'] = stamp(1107)
    op['reconciliation'] = json.dumps({'observation': 'unavailable', 'error_type': 'RuntimeError', 'observed_at': stamp(1125),
                                     'attribution': 'not_established', 'recovery': 'not_verified'})
    inputs['barrier']['at'] += 60
    card['workers'][1]['episodes'] = [{'attempt': {'started_at': t}, 'outcome': {'finished_at': t + 2, 'claim': {'outcome': 'healthy'}}}
                                    for t in [1027, 1036]]
    card['workers'][3]['finished']['at'] = 1126
    events = inputs['captured']['events']
    for i, at in enumerate([1085, 1107]):
        events[i]['requestReceivedTimestamp'] = stamp(at + 0.1)
        events[i]['stageTimestamp'] = stamp(at + 0.3)
    events.append({'auditID': 'authored-role', 'verb': 'patch', 'requestReceivedTimestamp': stamp(1114.3),
                   'objectRef': {'namespace': 'autonomy-lab', 'resource': 'roles', 'name': 'broker'},
                   'responseStatus': {'code': 200}, 'user': {'username': 'kubernetes-admin'}})
    events.append({'auditID': 'authored-denied', 'verb': 'get', 'requestReceivedTimestamp': stamp(1125),
                   'objectRef': {'namespace': 'autonomy-lab', 'resource': 'services', 'name': 'inventory'},
                   'responseStatus': {'code': 403}, 'user': {'username': 'system:serviceaccount:autonomy-lab:broker'}})
    return inputs


def test_authored_telemetry_result_retains_unknowns_and_unavailable_reconciliation():
    inputs = telemetry_inputs()
    result = assess_telemetry(**inputs)
    assert result['status'] == 'passed', result['checks']
    assert result['service_sample_counts'] == {'verified_success': 15, 'verified_failure': 2, 'unknown': 4}
    assert result['operation']['reconciliation']['observation'] == 'unavailable'
    assert result == assess_telemetry(**inputs)


def test_dependent_controller_update_is_not_an_extra_actuator_write():
    event = {'auditID': 'authored-dependent-update', 'verb': 'update', 'requestReceivedTimestamp': stamp(1038),
             'objectRef': {'namespace': 'autonomy-lab', 'resource': 'endpointslices', 'name': 'inventory'},
             'responseStatus': {'code': 200}, 'user': {'username': 'system:kube-controller-manager'}}
    telemetry = telemetry_inputs()
    telemetry['captured']['events'].append(event)
    assert assess_telemetry(**telemetry)['status'] == 'passed'
    stopped = stop_inputs('kill')
    stopped['captured']['events'].append(event)
    assert assess_stop(**stopped)['status'] == 'passed'


@pytest.mark.parametrize('defect', ['filled_gap', 'shifted_gap', 'late_as_missing', 'raw_gap_present', 'rewritten_sample',
    'restarted_observer', 'no_signal', 'claims_missing', 'lost_read_denial', 'wrong_read_status', 'kept_get', 'lost_patch',
    'false_reconciliation', 'budget_reset', 'acknowledged', 'new_operation', 'replayed_write', 'extra_role_write',
    'late_exit', 'missed_restart', 'no_escalation', 'false_health', 'protected_damage', 'lost_cleanup', 'missing_barrier'])
def test_telemetry_adversarial_evidence_fails(defect):
    inputs = telemetry_inputs()
    card, record, events = inputs['card'], inputs['record'], inputs['captured']['events']
    if defect == 'filled_gap':
        card['samples'][3]['verdict'] = 'verified_success'
    elif defect == 'shifted_gap':
        card['samples'][7]['verdict'], card['samples'][6]['verdict'] = 'unknown', 'verified_success'
    elif defect == 'late_as_missing':
        card['samples'][3]['coverage'] = 'late'
    elif defect == 'raw_gap_present':
        inputs['raw'][3] = {}
    elif defect == 'rewritten_sample':
        card['sample_sha256']['0000.json'] = 'changed'
    elif defect == 'restarted_observer':
        record['observer_identity_after'] = 'replacement'
    elif defect == 'no_signal':
        record['pause_state'] = 'S'
    elif defect == 'claims_missing':
        card['workers'][1]['episodes'] = []
    elif defect == 'lost_read_denial':
        events.pop()
    elif defect == 'wrong_read_status':
        events[-1]['responseStatus']['code'] = 200
    elif defect in {'kept_get', 'lost_patch'}:
        record['revocation']['after_rules'][0]['verbs'] = ['get', 'patch'] if defect == 'kept_get' else []
    elif defect == 'false_reconciliation':
        recon = json.loads(card['operations'][0]['reconciliation'])
        recon['observation'] = 'desired_state_observed'
        card['operations'][0]['reconciliation'] = json.dumps(recon)
    elif defect == 'budget_reset':
        card['dispatch_budget_reserved'] = 0
    elif defect == 'acknowledged':
        card['operations'][0]['status'] = 'acknowledged'
    elif defect == 'new_operation':
        card['operations'].append(copy.deepcopy(card['operations'][0]))
    elif defect in {'replayed_write', 'extra_role_write'}:
        events.append({**events[1 if defect == 'replayed_write' else 2], 'auditID': 'extra'})
    elif defect == 'late_exit':
        card['workers'][3]['finished']['at'] = 1200
    elif defect == 'missed_restart':
        record['restart_requested_at'] += 10
    elif defect == 'no_escalation':
        card['workers'][3]['escalation'] = None
    elif defect == 'false_health':
        card['samples'][16]['verdict'] = 'verified_failure'
    elif defect == 'protected_damage':
        card['samples'][9]['reasons'].append('database: protected rows changed')
    elif defect == 'lost_cleanup':
        card['owner_finished'] = False
    elif defect == 'missing_barrier':
        inputs['barrier'] = {}
    assert assess_telemetry(**inputs)['status'] == 'failed'


def stop_inputs(mode):
    inputs = authored('unchanged')
    card, record = inputs['card'], inputs['record']
    measurements(inputs, 12, {3}, set(range(4, 12)))
    card.update(window={'start': 1000, 'end': 1120}, owner_window_completed=False, owner_finished=False,
                identities_after=None, sample_sha256={f'{i:04d}.json': f'authored-{i}' for i in range(4)})
    op = card['operations'][0]
    op.update(status='dispatching', reconciliation=None, created_at=stamp(1037))
    card['workers'] = card['workers'][:3]
    record.update(mode=mode, operator='operator-repair', operator_paused_at=1020, operator_resumed_at=1035,
                  barrier={'at': 1038, 'operation_id': 'authored-op'}, stop_requested_at=1039,
                  sample_sha256_before=dict(card['sample_sha256']), identities_at_barrier=dict(card['identities_before']),
                  declaration={'cleanup_deadline_seconds': 390, 'schedule_lateness_seconds': 3, 'stop_after_barrier_seconds': 3},
                  before={'KillMode': 'control-group', 'Restart': 'no', 'ExecStopPost': 'authored-command', 'InvocationID': 'original-invocation'},
                  after={'ExecMainStatus': '1' if mode == 'restart' else '9'}, original_processes_terminated=True,
                  restart_refused=mode == 'restart', launch_claim_unchanged=True, post_stop_receipt_unchanged=True,
                  cgroup_members=[{'role': role, 'pid': i + 123, 'identity': 'authored-identity', 'cgroup': 'authored-shared-group'}
                                 for i, role in enumerate(['owner', 'operator', 'observer', 'janitor'])])
    inputs['captured']['events'][1]['requestReceivedTimestamp'] = stamp(1037.1)
    inputs['captured']['events'][1]['stageTimestamp'] = stamp(1037.3)
    receipt = {'status': 'finished', 'cleanup': 'deleted', 'accounting': 'recorded', 'remaining': {'cluster_nodes': [], 'registered_agents': []},
               'started_at': 1040, 'finished_at': 1044, 'invocation_id': 'original-invocation', 'original_evidence_unchanged': True,
               'sample_sha256': dict(card['sample_sha256'])}
    return {k: inputs[k] for k in ['card', 'record', 'captured', 'raw']} | {'journal': inputs['journal'][:2], 'receipt': receipt}


@pytest.mark.parametrize('mode', ['restart', 'kill'])
def test_authored_owner_recovery_preserves_interruption(mode):
    result = assess_stop(**stop_inputs(mode))
    assert result['status'] == 'passed', result['checks']
    assert result['sample_counts'] == {'verified_success': 3, 'verified_failure': 1, 'unknown': 8}


@pytest.mark.parametrize('defect', ['surviving_janitor', 'other_cgroup', 'late_cleanup', 'wrong_invocation', 'replayed_owner',
    'owner_marked_finished', 'backfilled_future', 'lost_prefix', 'altered_prefix', 'mutated_workload', 'acknowledged',
    'reconciled', 'duplicate_write', 'missing_audit', 'committed_episode', 'missed_stop', 'new_claim'])
def test_owner_recovery_adversarial_evidence_fails(defect):
    inputs = stop_inputs('restart')
    card, record, receipt = inputs['card'], inputs['record'], inputs['receipt']
    if defect == 'surviving_janitor':
        record['original_processes_terminated'] = False
    elif defect == 'other_cgroup':
        record['cgroup_members'][-1]['cgroup'] = 'different'
    elif defect == 'late_cleanup':
        receipt['finished_at'] = 1600
    elif defect == 'wrong_invocation':
        receipt['invocation_id'] = 'new-invocation'
    elif defect == 'replayed_owner':
        record['restart_refused'] = False
    elif defect == 'owner_marked_finished':
        card['owner_window_completed'] = True
    elif defect == 'backfilled_future':
        card['samples'][5]['verdict'] = 'verified_success'
    elif defect == 'lost_prefix':
        card['sample_sha256'].pop('0000.json')
    elif defect == 'altered_prefix':
        receipt['sample_sha256']['0000.json'] = 'changed'
    elif defect == 'mutated_workload':
        record['identities_at_barrier']['Service/inventory'] = 'new-uid'
    elif defect == 'acknowledged':
        card['operations'][0]['status'] = 'acknowledged'
    elif defect == 'reconciled':
        card['operations'][0]['reconciliation'] = '{}'
    elif defect == 'duplicate_write':
        inputs['captured']['events'].append({**inputs['captured']['events'][1], 'auditID': 'duplicate'})
    elif defect == 'missing_audit':
        inputs['captured']['events'].pop()
    elif defect == 'committed_episode':
        card['workers'][2]['episodes'][0]['outcome'] = {'claim': {'outcome': 'resolved'}}
    elif defect == 'missed_stop':
        record['stop_requested_at'] = 1100
    elif defect == 'new_claim':
        record['launch_claim_unchanged'] = False
    assert assess_stop(**inputs)['status'] == 'failed'


def test_service_restart_refuses_existing_claim_even_if_torn(tmp_path):
    module = load_script('service_campaign')
    (tmp_path / 'launch-claim.json').write_text('{')
    with patch.object(module, 'load_job', return_value=({}, tmp_path / 'campaign')), patch.object(module, 'own') as own:
        with pytest.raises(FileExistsError):
            module.run(tmp_path)
        own.assert_not_called()


def test_post_stop_receipt_is_immutable_across_refused_restart(tmp_path):
    module = load_script('service_campaign')
    receipt = {'status': 'finished', 'invocation_id': 'original'}
    save(tmp_path / 'post-stop.json', receipt)
    with patch.object(module, 'load_job', return_value=({}, tmp_path / 'campaign')), \
            patch.dict(module.os.environ, {'SERVICE_RESULT': 'exit-code', 'INVOCATION_ID': 'new'}):
        assert module.finalize(tmp_path) == receipt


def test_receipt_snapshot_binds_reviewed_body_before_later_replacement(tmp_path):
    module = load_script('check_campaign_stop')
    save(tmp_path / 'post-stop.json', {'invocation_id': 'original'})
    receipt, digest = module.receipt_snapshot(tmp_path)
    save(tmp_path / 'post-stop.json', {'invocation_id': 'replacement'})
    assert receipt == {'invocation_id': 'original'}
    assert digest != module.evidence_digest(tmp_path, 'post-stop.json')


def test_post_stop_accounting_failure_does_not_skip_cleanup(tmp_path):
    module = load_script('service_campaign')
    campaign = tmp_path / 'campaign'
    campaign.mkdir()
    (campaign / 'samples').mkdir()
    owner = {'pid': 123, 'identity': 'authored', 'run_id': '1234abcd'}
    for path, data in [(campaign / 'owner.json', owner), (tmp_path / 'launch-claim.json', owner),
                       (campaign / 'environment.json', {'cluster': 'autolab-1234abcd'}), (campaign / 'window.json', {})]:
        save(path, data)
    with patch.object(module, 'load_job', return_value=({}, campaign)), patch.object(module, 'process_identity', return_value=''), \
            patch.object(module, 'scorecard', side_effect=ValueError('authored damaged accounting')), \
            patch.object(module, 'cleanup', return_value={'status': 'deleted'}) as cleanup, \
            patch.object(module, 'remaining_resources', return_value={'cluster_nodes': [], 'registered_agents': []}), \
            patch.dict(module.os.environ, {'SERVICE_RESULT': 'signal', 'INVOCATION_ID': 'original'}):
        result = module.finalize(tmp_path)
        assert result['status'] == 'failed' and result['cleanup'] == 'deleted'
        assert result['errors'] == [{'stage': 'accounting', 'error_type': 'ValueError'}]
        cleanup.assert_called_once()


def test_signal_refuses_reused_worker_identity(tmp_path):
    module = load_script('check_telemetry')
    save(tmp_path / 'worker-lease.json', {'pid': 123, 'identity': 'original'})
    with patch.object(module, 'process_identity', return_value='replacement'), patch.object(module.os, 'killpg') as kill:
        with pytest.raises(RuntimeError, match='identity'):
            module.signal_worker(tmp_path, module.signal.SIGSTOP)
        kill.assert_not_called()
