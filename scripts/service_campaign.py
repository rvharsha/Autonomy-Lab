"""Systemd owns bounded campaign cleanup after the original process group dies."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from service_experiment import remaining_resources

from autonomy_lab.campaign import Contract, operation_rows, own, read
from autonomy_lab.campaign_report import scorecard
from autonomy_lab.harness import save
from autonomy_lab.janitor import cleanup, process_identity
from autonomy_lab.kubernetes import ROOT


def source_files():
    paths = [*sorted((ROOT / 'src/autonomy_lab').glob('*.py')), ROOT / 'scripts/service_campaign.py',
             ROOT / 'scripts/service_experiment.py', ROOT / 'fixtures/expectations.json', ROOT / 'fixtures/database.sql',
             ROOT / 'infra/toolchain.json', ROOT / 'infra/kind.yaml']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def prepare(manifest):
    contract = Contract.model_validate(read(manifest))
    identity = uuid.uuid4().hex[:8]
    directory = ROOT / 'artifacts' / ('campaign-service-' + identity)
    directory.mkdir(parents=True, mode=0o700)
    save(directory / 'contract.json', contract.model_dump())
    save(directory / 'job.json', {'id': identity, 'contract': contract.model_dump(), 'source_files': source_files(), 'prepared_at': time.time()})
    return directory


def load_job(directory):
    if (not directory.is_absolute() or directory.resolve() != directory or directory.parent != ROOT / 'artifacts'
            or re.fullmatch(r'campaign-service-[a-f0-9]{8}', directory.name) is None):
        raise ValueError('Expected a prepared campaign service in this checkout')
    job = read(directory / 'job.json')
    if job['id'] != directory.name.removeprefix('campaign-service-'):
        raise ValueError('Campaign service identity mismatch')
    if Contract.model_validate(read(directory / 'contract.json')).model_dump() != job['contract']:
        raise ValueError('Campaign contract changed after preparation')
    return job, directory / 'campaign'


def run(directory):
    job, campaign = load_job(directory)
    # Never retry an identity, including a torn or partially completed invocation.
    with (directory / 'launch-claim.json').open('x') as stream:
        json.dump({'pid': os.getpid(), 'identity': process_identity(os.getpid()),
                   'at': time.time(), 'invocation_id': os.environ.get('INVOCATION_ID')}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if source_files() != job['source_files']:
        raise ValueError('Campaign source changed after preparation')
    own(directory / 'contract.json', campaign)


def finalize(directory):
    job, campaign = load_job(directory)
    with (directory / 'post-stop.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / 'post-stop.json'
        if path.exists():
            return read(path)  # A refused restart cannot overwrite the original evidence.
        if not os.environ.get('SERVICE_RESULT'):
            raise RuntimeError('Campaign recovery requires the systemd post-stop phase')
        result = {'status': 'failed', 'started_at': time.time(), 'service_result': os.environ['SERVICE_RESULT'],
                  'invocation_id': os.environ.get('INVOCATION_ID'),
                  'accounting': 'unknown', 'cleanup': 'unknown', 'errors': []}
        save(directory / 'post-stop-started.json', result)
        try:
            if campaign.resolve() != campaign:
                raise ValueError('Campaign directory is not canonical')
            if (campaign / 'owner.json').exists():
                owner, claim = read(campaign / 'owner.json'), read(directory / 'launch-claim.json')
                if any(owner[k] != claim[k] for k in ['pid', 'identity']):
                    raise ValueError('Campaign owner differs from launched invocation')
                if type(owner['pid']) is not int or owner['pid'] <= 1 or not owner['identity']:
                    raise ValueError('Invalid owner identity')
                if process_identity(owner['pid']) == owner['identity']:
                    raise RuntimeError('Original campaign owner is still alive')
                if re.fullmatch(r'[a-f0-9]{8}', owner['run_id']) is None:
                    raise ValueError('Invalid campaign resource identity')
                cluster = 'autolab-' + owner['run_id']
            else:
                cluster = None
            environment = campaign / 'environment.json'
            if environment.exists() and (cluster is None or read(environment)['cluster'] != cluster):
                raise ValueError('Campaign resource ownership mismatch')
            before = operation_rows(campaign)
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (campaign / 'samples').glob('*.json')}
            try:
                if (campaign / 'window.json').exists():
                    save(directory / 'post-stop-scorecard-a.json', scorecard(campaign))
                    result['accounting'] = 'recorded'
                else:
                    result['accounting'] = 'measurement_not_started'
            except Exception as error:
                result['errors'].append({'stage': 'accounting', 'error_type': type(error).__name__})
            # Accounting failure must not prevent independently owned cleanup.
            try:
                if environment.exists():
                    deleted = cleanup(campaign, {'cluster': cluster})
                    if deleted['status'] != 'deleted':
                        raise RuntimeError('Campaign cleanup incomplete')
                    result['remaining'] = remaining_resources(campaign, cluster)
                    if any(result['remaining'].values()):
                        raise RuntimeError('Owned containers remain')
                    result['cleanup'] = 'deleted'
                else:
                    result['cleanup'] = 'not_provisioned'
            except Exception as error:
                result['errors'].append({'stage': 'cleanup', 'error_type': type(error).__name__})
            try:
                if before != operation_rows(campaign) or hashes != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (campaign / 'samples').glob('*.json')}:
                    raise RuntimeError('Recovery modified operation or measurement evidence')
                result['original_evidence_unchanged'] = True
                result['sample_sha256'] = hashes
                if result['accounting'] == 'recorded':
                    save(directory / 'post-stop-scorecard-b.json', scorecard(campaign))
                    if (directory / 'post-stop-scorecard-a.json').read_bytes() != (directory / 'post-stop-scorecard-b.json').read_bytes():
                        raise RuntimeError('Post-stop exports differ')
                    result['scorecard_sha256'] = hashlib.sha256((directory / 'post-stop-scorecard-a.json').read_bytes()).hexdigest()
            except Exception as error:
                result['errors'].append({'stage': 'evidence', 'error_type': type(error).__name__})
        except Exception as error:
            result['errors'].append({'stage': 'ownership', 'error_type': type(error).__name__})
        result.update(status='finished' if not result['errors'] else 'failed', finished_at=time.time())
        save(path, result)
        return result


def launch_command(directory, user):
    job, _ = load_job(directory)
    python, script = str(Path(sys.executable).absolute()), str(ROOT / 'scripts/service_campaign.py')
    if any(re.fullmatch(r'[A-Za-z0-9_/.-]+', value) is None for value in [python, script, str(directory)]):
        raise ValueError('Campaign service requires simple absolute Linux paths')
    if re.fullmatch(r'[a-z_][a-z0-9_-]*', user) is None:
        raise ValueError('Invalid campaign service user')
    return ['systemd-run', '--unit=autolab-campaign-' + job['id'], '--uid=' + user, '--gid=' + user,
            '--property=Type=exec', '--property=Restart=no', '--property=KillMode=control-group',
            '--property=KillSignal=SIGTERM', '--property=TimeoutStopSec=180', '--property=RuntimeMaxSec=1800',
            '--property=UMask=0077', '--property=WorkingDirectory=' + str(ROOT),
            '--setenv=PYTHONPATH=' + str(ROOT / 'src'), '--setenv=PATH=/usr/local/bin:/usr/bin:/bin',
            '--setenv=PYTHONDONTWRITEBYTECODE=1',
            '--property=ExecStopPost=' + ' '.join([python, script, 'finalize', str(directory)]),
            python, script, 'run', str(directory)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare').add_argument('manifest', type=Path)
    for command in ['run', 'finalize', 'launch']:
        p = commands.add_parser(command)
        p.add_argument('directory', type=Path)
        if command == 'launch':
            p.add_argument('--user', default='autolab')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.manifest))
    elif args.command == 'run':
        run(args.directory.absolute())
    elif args.command == 'launch':
        subprocess.run(launch_command(args.directory.absolute(), args.user), check=True, timeout=30)
    else:
        result = finalize(args.directory.absolute())
        print(json.dumps(result))
        return 0 if result['status'] == 'finished' else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
