"""Kill a real campaign service and verify post-stop cleanup and immutable evidence."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from check_ambiguity import change_routing
from check_campaign import await_file, wait_until
from check_service_stop import (
    evidence_bytes,
    evidence_digest,
    evidence_json,
    receipt_directory,
    unit_state,
)
from check_telemetry import signal_worker
from service_campaign import load_job

from autonomy_lab.ambiguity import journal_events
from autonomy_lab.audit import read_events
from autonomy_lab.campaign import identities, operation_rows
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.campaign_stop import assess_stop
from autonomy_lab.harness import client_path_failed, save
from autonomy_lab.janitor import process_identity
from autonomy_lab.kubernetes import ROOT, Kubernetes


def receipt_snapshot(directory):
    raw = evidence_bytes(directory, 'post-stop.json')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def run(mode, user):
    if os.geteuid() != 0 or mode not in {'restart', 'kill'}:
        raise PermissionError('Run a declared restart or kill gate as the host administrator')
    gate = receipt_directory()  # Existing hardened root-owned receipt location.
    spec = {'kind': 'persistent_campaign_owner_termination', 'mode': mode, 'pause_offset': 20, 'inject_offset': 25,
            'resume_offset': 35, 'barrier_deadline_offset': 65, 'stop_after_barrier_seconds': 3,
            'schedule_lateness_seconds': 3, 'cleanup_deadline_seconds': 390,
            'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                ['scenarios/campaign-owner-stop.json', 'scripts/check_campaign_stop.py', 'scripts/service_campaign.py',
                 'src/autonomy_lab/campaign_stop.py']}}
    save(gate / 'declaration.json', spec)
    result = {'status': 'failed', 'mode': mode, 'started_at': time.time(), 'declaration': spec}
    unit = None
    try:
        script, python = str(ROOT / 'scripts/service_campaign.py'), str(Path(sys.executable).absolute())
        output = subprocess.check_output(['sudo', '-u', user, 'env', 'PYTHONPATH=' + str(ROOT / 'src'),
            python, script, 'prepare', str(ROOT / 'scenarios/campaign-owner-stop.json')], text=True, timeout=30)
        directory = Path(output.strip())
        job, campaign = load_job(directory)
        unit = 'autolab-campaign-' + job['id'] + '.service'
        result.update(job=directory.name, unit=unit)
        save(gate / 'result.json', result)
        subprocess.run([python, script, 'launch', str(directory), '--user', user], check=True, timeout=30)
        window = await_file(campaign / 'window.json', time.monotonic() + 900)
        operator = next((campaign / 'workers').glob('operator-*'))
        observer = next((campaign / 'workers').glob('observer-*'))
        result.update(operator=operator.name, run_id=evidence_json(campaign, 'owner.json')['run_id'])
        kube = Kubernetes(campaign / 'kubeconfig', evidence_json(campaign, 'environment.json')['cluster'])
        wait_until(window['start'] + spec['pause_offset'])
        result['operator_paused_at'] = signal_worker(operator, signal.SIGSTOP)['at']
        wait_until(window['start'] + spec['inject_offset'])
        change_routing(kube, campaign, gate, result, 'fault', 8080, 9999)
        wait_until(window['start'] + spec['resume_offset'])
        observed = [evidence_json(campaign, 'samples/' + p.name) for p in (campaign / 'samples').glob('*.json')]
        if not any(s['started_at'] >= result['fault']['finished_at'] and client_path_failed(s.get('verification', {})) for s in observed):
            raise AssertionError('No independent fault sample before operator continuation')
        result['operator_resumed_at'] = signal_worker(operator, signal.SIGCONT)['at']
        result['barrier'] = await_file(operator / 'dispatch-barrier.json', time.monotonic() + max(0, window['start'] + 65 - time.time()))
        operations = operation_rows(campaign)
        if len(operations) != 1 or operations[0]['status'] != 'dispatching' or operations[0]['result'] is not None:
            raise AssertionError('Campaign did not stop at an unrecorded real effect')
        result['identities_at_barrier'] = identities(kube)
        result['before'] = unit_state(unit)
        result['before']['InvocationID'] = subprocess.check_output(
            ['systemctl', 'show', unit, '--property=InvocationID', '--value'], text=True, timeout=15).strip()
        members = []
        sources = [('owner', evidence_json(campaign, 'owner.json')),
                   ('operator', evidence_json(operator, 'worker-lease.json')),
                   ('observer', evidence_json(observer, 'worker-lease.json')),
                   ('janitor', evidence_json(campaign, 'janitor-process.json'))]
        for role, lease in sources:
            pid = lease['pid']
            if type(pid) is not int or pid <= 1:
                raise ValueError('Invalid process identity')
            identity = process_identity(pid)
            if not identity or ('identity' in lease and identity != lease['identity']):
                raise RuntimeError('Original process disappeared before termination')
            members.append({'role': role, 'pid': pid, 'identity': identity, 'cgroup': Path(f'/proc/{pid}/cgroup').read_text()})
        result['cgroup_members'] = members
        result['sample_sha256_before'] = {p.name: evidence_digest(campaign, 'samples/' + p.name) for p in (campaign / 'samples').glob('*.json')}
        claim_hash = evidence_digest(directory, 'launch-claim.json')
        result['stop_requested_at'] = time.time()
        save(gate / 'result.json', result)
        command = ['systemctl', 'restart', unit] if mode == 'restart' else ['systemctl', 'kill', '--kill-whom=all', '--signal=SIGKILL', unit]
        subprocess.run(command, check=True, timeout=390)
        await_file(directory / 'post-stop.json', time.monotonic() + max(0, result['stop_requested_at'] + 390 - time.time()))
        receipt, receipt_hash = receipt_snapshot(directory)
        deadline = time.monotonic() + 30
        while unit_state(unit)['ActiveState'] in {'active', 'activating', 'deactivating'}:
            if time.monotonic() >= deadline:
                raise TimeoutError('Campaign unit did not finish recovery')
            time.sleep(0.25)
        result.update(after=unit_state(unit), original_processes_terminated=all(process_identity(m['pid']) != m['identity'] for m in members),
                      launch_claim_unchanged=claim_hash == evidence_digest(directory, 'launch-claim.json'))
        # The restart command has completed its second start; that invocation must refuse replay.
        journal = subprocess.check_output(['journalctl', '-u', unit, '--no-pager', '-o', 'cat'], text=True, timeout=15)
        result['restart_refused'] = ('FileExistsError' in journal and result['after']['ExecMainStatus'] == '1') if mode == 'restart' else None
        result['post_stop_receipt_unchanged'] = receipt_hash == evidence_digest(directory, 'post-stop.json')
        save(gate / 'post-stop.json', receipt)
        for suffix in ('a', 'b'):
            card = scorecard(campaign)
            save(gate / f'scorecard-{suffix}.json', card)
            evaluation = assess_stop(card, receipt, result, read_events(campaign / 'server-audit'), journal_events(campaign),
                {int(p.stem): evidence_json(campaign, 'samples/' + p.name) for p in (campaign / 'samples').glob('*.json')})
            save(gate / f'evaluation-{suffix}.json', evaluation)
        for name in ('scorecard', 'evaluation'):
            if (gate / f'{name}-a.json').read_bytes() != (gate / f'{name}-b.json').read_bytes():
                raise AssertionError('Campaign recovery export is not reproducible')
        if evaluation['status'] != 'passed':
            raise AssertionError('Owner termination contract failed: ' + ', '.join(k for k, v in evaluation['checks'].items() if not v))
        result.update(status='passed', export_identical=True, post_stop=receipt,
            scorecard_sha256=hashlib.sha256((gate / 'scorecard-a.json').read_bytes()).hexdigest(),
            evaluation_sha256=hashlib.sha256((gate / 'evaluation-a.json').read_bytes()).hexdigest())
    except BaseException as error:
        result['error_type'] = type(error).__name__
        raise
    finally:
        if unit:
            try:
                stopped = subprocess.run(['systemctl', 'stop', unit], capture_output=True, timeout=390)
                result['final_stop_exit_code'] = stopped.returncode
                if stopped.returncode != 0:
                    result['status'] = 'failed'
                output = subprocess.run(['journalctl', '-u', unit, '--no-pager', '-o', 'json'], capture_output=True, timeout=15)
                (gate / 'service-journal.jsonl').write_bytes(output.stdout)
            except Exception as error:
                result.update(status='failed', final_stop_error_type=type(error).__name__)
        result['finished_at'] = time.time()
        save(gate / 'result.json', result)
        print(gate, flush=True)
    if result['status'] != 'passed':
        raise RuntimeError('Campaign owner gate finalization failed')
    return gate


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['restart', 'kill'])
    parser.add_argument('--user', default='autolab')
    args = parser.parse_args()
    run(args.mode, args.user)
