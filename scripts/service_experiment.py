"""One declared cloud experiment, with systemd-managed post-stop recovery.

Run prepare as the lab user; launch as its host administrator. Recovery writes a
separate accounting receipt, never replacement trial outcomes. The host and
systemd remain trusted; host/power loss during recovery is outside this boundary.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

from autonomy_lab.experiments import (
    planned_trials,
    release_manifest,
    run_experiment,
    validate_config,
)
from autonomy_lab.harness import save, timestamp
from autonomy_lab.janitor import cleanup, process_identity
from autonomy_lab.kubernetes import ROOT


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execution_files(config):
    return {**release_manifest(config)['files'],
            'scripts/service_experiment.py': digest(ROOT / 'scripts/service_experiment.py')}


def credential_path(value):
    if value is None:
        return None
    path = Path(value)
    if (not path.is_absolute() or path.resolve() != path
            or not path.is_relative_to('/run/autonomy-lab') or path.name != 'provider.env'):
        raise ValueError('Only a dedicated /run/autonomy-lab/.../provider.env may be consumed')
    return path


def prepare(manifest, env_file=None):
    config = yaml.safe_load(manifest.read_text())
    validate_config(config)
    if config.get('runtime') != 'isolated-docker':
        raise ValueError('Managed cloud jobs require isolated-docker')
    credential = credential_path(str(env_file) if env_file else None)
    if set(config['variants']) & {'basic', 'structured'} and credential is None:
        raise ValueError('A live job requires a dedicated transient credential path')
    identity = uuid.uuid4().hex[:8]
    directory = ROOT / 'artifacts' / f'service-{identity}'
    directory.mkdir(parents=True, mode=0o700)
    save(directory / 'job.json', {
        'schema_version': 1, 'run_id': identity, 'config': config,
        'owner_token': uuid.uuid4().hex,
        'plan': planned_trials(config), 'source_files': execution_files(config),
        'manifest_sha256': digest(manifest), 'prepared_at': timestamp(),
        'env_file': str(credential) if credential else None,
    })
    return directory


def load_job(directory):
    directory = directory.absolute()
    if (directory.resolve() != directory or directory.parent != ROOT / 'artifacts'
            or re.fullmatch(r'service-[a-f0-9]{8}', directory.name) is None):
        raise ValueError('Expected a prepared job in this checkout')
    job = read(directory / 'job.json')
    if job['schema_version'] != 1 or job['run_id'] != directory.name.removeprefix('service-'):
        raise ValueError('Job identity mismatch')
    if re.fullmatch(r'[a-f0-9]{32}', job.get('owner_token', '')) is None:
        raise ValueError('Missing service ownership token')
    validate_config(job['config'])
    if job['plan'] != planned_trials(job['config']):
        raise ValueError('Job plan mismatch')
    credential_path(job['env_file'])
    return job, ROOT / 'artifacts' / f"experiment-{job['run_id']}"


def run(directory):
    job, run_dir = load_job(directory)
    # The inode is the durable, fail-closed claim. Even a torn claim prohibits replay.
    with (directory / 'launch-claim.json').open('x') as stream:
        json.dump({'pid': os.getpid(), 'identity': process_identity(os.getpid()),
                   'claimed_at': timestamp(), 'invocation_id': os.environ.get('INVOCATION_ID')}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    result = {'status': 'interrupted', 'finished_at': None}
    try:
        if run_dir.exists():
            raise ValueError('Reserved experiment already exists')
        if execution_files(job['config']) != job['source_files']:
            raise ValueError('Source changed after preparation')
        run_experiment(job['config'], env_file=credential_path(job['env_file']), run_id=job['run_id'],
                       owner_token=job['owner_token'])
        result['status'] = 'returned'
    except BaseException as error:
        result.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        result['finished_at'] = timestamp()
        save(directory / 'controller-result.json', result)


def accounting(job, run_dir):
    plan = job['plan']
    manifest_path = run_dir / 'manifest.json'
    if manifest_path.exists() and read(manifest_path)['planned_trials'] != plan:
        raise ValueError('Run manifest differs from prepared plan')
    results_path = run_dir / 'results.json'
    results = read(results_path) if results_path.exists() else []
    if not isinstance(results, list) or len(results) > len(plan):
        raise ValueError('Invalid controller result prefix')
    rows = []
    for index, item in enumerate(plan, 1):
        trial = run_dir / f'trial-{index:03d}'
        if (trial / 'trial.json').exists():
            partial = read(trial / 'trial.json')
            if any(partial.get(k) != item[k] for k in ('scenario', 'variant')):
                raise ValueError('Worker trial identity differs from plan')
            if 'repetition' in partial and partial['repetition'] != item['repetition']:
                raise ValueError('Worker trial repetition differs from plan')
        row = {**item, 'index': index, 'task_success': None, 'audit_assessed': None}
        if index <= len(results):
            result = results[index - 1]
            if any(result.get(k) != v for k, v in item.items()):
                raise ValueError('Controller result identity differs from plan')
            status = result.get('status')
            if status not in {'recorded', 'interrupted', 'timed_out', 'infrastructure_error'}:
                raise ValueError('Controller result is not terminal')
            success = (result.get('score') or {}).get('task_success')
            if success is not None and type(success) is not bool:
                raise ValueError('Invalid task outcome')
            row.update(disposition='controller_recorded', status=status, task_success=success,
                       audit_assessed=(result.get('execution_audit') or {}).get('status') == 'assessed')
        elif trial.exists():
            # A launched worker may have finished, but the controller did not commit
            # it. Do not infer a score, usage, duration or clean audit from partials.
            row.update(disposition='attempted_unassessed', status='interrupted')
        else:
            row.update(disposition='unrun', status='unrun')
        rows.append(row)
    directories = {p.name for p in run_dir.glob('trial-*') if p.is_dir()}
    attempted = sum(r['disposition'] != 'unrun' for r in rows)
    if directories != {f'trial-{i:03d}' for i in range(1, attempted + 1)}:
        raise ValueError('Trial directories are not the accounted prefix')
    hashes = {str(p.relative_to(run_dir)): digest(p) for p in
              [manifest_path, results_path, run_dir / 'release.json', run_dir / 'accounting.json',
               run_dir / 'cleanup.json', *sorted(run_dir.glob('trial-*/trial*.json'))] if p.is_file()}
    return {'kind': 'post_stop_accounting', 'planned': len(plan),
            'controller_recorded': len(results), 'attempted': attempted,
            'unassessed_attempts': sum(r['disposition'] == 'attempted_unassessed' for r in rows),
            'unrun': sum(r['disposition'] == 'unrun' for r in rows),
            'controller_final_accounting_available': (run_dir / 'accounting.json').exists(),
            'original_evidence_sha256': hashes, 'trials': rows}


def remaining_resources(run_dir, cluster):
    names = subprocess.check_output(['docker', 'ps', '-a', '--filter',
        f'label=io.x-k8s.kind.cluster={cluster}', '--format', '{{.Names}}'], text=True, timeout=15).splitlines()
    registered = []
    for path in run_dir.glob('trial-*/agent-runtime.json'):
        name = read(path)['name']
        if re.fullmatch(r'autolab-agent-[a-f0-9]{12}', name) is None:
            raise ValueError('Invalid registered agent name')
        registered.append(name)
    all_names = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}'],
                                        text=True, timeout=15).splitlines()
    return {'cluster_nodes': names, 'registered_agents': sorted(set(registered) & set(all_names))}


def finalize(directory):
    job, run_dir = load_job(directory)
    with (directory / 'finalization.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        output = directory / 'post-stop.json'
        if output.exists():
            return read(output)  # Do not overwrite original interruption on a refused restart.
        if not os.environ.get('SERVICE_RESULT'):
            raise RuntimeError('Recovery must run in the systemd post-stop phase')
        result = {'kind': 'systemd_post_stop', 'run_id': job['run_id'], 'started_at': timestamp(),
                  'status': 'failed', 'cleanup': 'unknown', 'accounting': 'unknown',
                  'service_result': os.environ.get('SERVICE_RESULT', 'unknown')}
        errors = []
        # Revoke the job's provider file before any potentially slow Docker work.
        # Keep progress separate from the immutable completed recovery receipt.
        try:
            credential = credential_path(job['env_file'])
            if credential:
                credential.unlink(missing_ok=True)
            result['credential_removed'] = True
        except Exception as error:
            result['credential_removed'] = False
            errors.append({'stage': 'credential', 'error_type': type(error).__name__})
        save(directory / 'post-stop-started.json', result)
        stage = 'liveness'
        try:
            claim = directory / 'launch-claim.json'
            if claim.exists():
                try:
                    owner = read(claim)
                except ValueError:
                    owner = {}  # Torn claim prohibits launch; systemd stopped the unit.
                if owner.get('identity'):
                    if type(owner.get('pid')) is not int or owner['pid'] <= 1:
                        raise ValueError('Invalid controller identity in claim')
                    if process_identity(owner['pid']) == owner['identity']:
                        raise RuntimeError('Controller is still alive; recovery refused')
            # Unknown liveness must refuse cleanup, with a durable failure receipt
            # and credential revocation already recorded.
            stage = 'ownership'
            if run_dir.exists() and (not (run_dir / 'service-owner.json').is_file()
                    or read(run_dir / 'service-owner.json') != {'owner_token': job['owner_token']}):
                raise ValueError('Refusing recovery of an unowned experiment directory')
            try:
                selected = accounting(job, run_dir)
                save(directory / 'post-stop-accounting.json', selected)
                result['accounting'] = 'recorded'
            except Exception as error:
                errors.append({'stage': 'accounting', 'error_type': type(error).__name__})
            # Accounting errors must never prevent owned-resource cleanup.
            try:
                cluster = 'autolab-' + job['run_id']
                environment = run_dir / 'environment.json'
                if environment.exists():
                    if read(environment)['cluster'] != cluster:
                        raise ValueError('Environment ownership mismatch')
                    cleanup(run_dir, {'cluster': cluster})
                    if read(run_dir / 'janitor-result.json')['status'] != 'deleted':
                        raise RuntimeError('Janitor reported incomplete cleanup')
                remaining = remaining_resources(run_dir, cluster)
                result['remaining'] = remaining
                if any(remaining.values()):
                    raise RuntimeError('Owned resources remain')
                result['cleanup'] = 'deleted' if environment.exists() else 'not_provisioned'
            except Exception as error:
                result['cleanup'] = 'failed'
                errors.append({'stage': 'cleanup', 'error_type': type(error).__name__})
        except Exception as error:
            errors.append({'stage': stage, 'error_type': type(error).__name__})
        finally:
            result.update(status='finished' if not errors else 'failed', errors=errors, finished_at=timestamp())
            save(output, result)
        return result


def launch_command(directory, *, user, runtime_seconds):
    job, _ = load_job(directory)
    python = str(Path(sys.executable).absolute())
    script = str(ROOT / 'scripts/service_experiment.py')
    # ExecStopPost is systemd command syntax, not shell syntax. Restrict paths so
    # specifier/environment expansion or quoting cannot change its arguments.
    if any(re.fullmatch(r'[A-Za-z0-9_/.-]+', p) is None for p in (python, script, str(directory))):
        raise ValueError('Service launch requires simple absolute Linux paths')
    if re.fullmatch(r'[a-z_][a-z0-9_-]*', user) is None or not 60 <= runtime_seconds <= 14400:
        raise ValueError('Invalid service user or runtime limit')
    return ['systemd-run', '--unit=autolab-study-' + job['run_id'], '--uid=' + user, '--gid=' + user,
            '--property=Type=exec', '--property=Restart=no', '--property=KillMode=control-group',
            '--property=KillSignal=SIGTERM', '--property=TimeoutStopSec=300',
            '--property=RuntimeMaxSec=' + str(runtime_seconds), '--property=UMask=0077',
            '--property=WorkingDirectory=' + str(ROOT), '--setenv=PYTHONPATH=' + str(ROOT / 'src'),
            '--setenv=PATH=/usr/local/bin:/usr/bin:/bin', '--setenv=PYTHONDONTWRITEBYTECODE=1',
            '--property=ExecStopPost=' + ' '.join([python, script, 'finalize', str(directory)]),
            python, script, 'run', str(directory)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    p = actions.add_parser('prepare')
    p.add_argument('manifest', type=Path)
    p.add_argument('--env-file', type=Path)
    for action in ('run', 'finalize', 'launch'):
        p = actions.add_parser(action)
        p.add_argument('directory', type=Path)
        if action == 'launch':
            p.add_argument('--user', default='autolab')
            p.add_argument('--runtime-seconds', type=int, default=14400)
    args = parser.parse_args()
    if args.action == 'prepare':
        print(prepare(args.manifest, args.env_file))
    elif args.action == 'run':
        run(args.directory.absolute())
    elif args.action == 'finalize':
        result = finalize(args.directory.absolute())
        print(json.dumps(result))
        return 0 if result['status'] == 'finished' else 1
    else:
        subprocess.run(launch_command(args.directory.absolute(), user=args.user,
                                      runtime_seconds=args.runtime_seconds), check=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
