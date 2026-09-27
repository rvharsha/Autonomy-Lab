"""Freeze, execute once, export original bytes, and reconstruct the comparison."""

import argparse
import hashlib
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from autonomy_lab.campaign import read
from autonomy_lab.experiments import run_experiment
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require

from .gate import GROUPS, decide, evaluate, plan
from .negative import controls

ROOT_FILES = ('release.json', 'manifest.json', 'results.json', 'accounting.json', 'cleanup.json', 'environment.json')
TRIAL_FILES = ('trial.json', 'worker-request.json', 'supervisor.json', 'baseline.json', 'fault.json',
               'semantic-fault.json', 'backend-permission.json', 'verifier-outage.json', 'program.json',
               'reconciliation-binding.json', 'final-verification.json', 'operations.json',
               'operations.sqlite', 'operations.sqlite-journal', 'operations.sqlite-wal', 'operations.sqlite-shm',
               'operation-events.json', 'server-audit.json', 'evidence.jsonl')


def export(source, destination):
    """Copy only credential-free raw artifacts without editing their contents."""
    destination.mkdir(parents=True, exist_ok=False)
    paths = [source / name for name in ROOT_FILES if (source / name).is_file()]
    for trial in source.glob('trial-*'):
        paths.extend(trial / n for n in TRIAL_FILES if (trial / n).is_file())
        paths.extend(trial.glob('verification-*.json'))
    hashes = {}
    for path in sorted(paths):
        name = str(path.relative_to(source))
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return hashes


def verify_export(source, hashes):
    actual = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in source.rglob('*') if p.is_file()}
    require(actual == hashes and bool(hashes), 'Raw export inventory or bytes differ')


def audit_copy(source, shard, frozen_at):
    """SQLite read-only WAL readers may create sidecars; isolate those effects."""
    with tempfile.TemporaryDirectory(prefix='observer-evidence-audit-') as temporary:
        scratch = Path(temporary) / 'raw'
        shutil.copytree(source, scratch)
        return evaluate(scratch, shard, frozen_at)


def retain_after_step(destination):
    """A separate CI step retains partial originals after a killed live wrapper.

    This snapshot cannot replace the original result or qualify a failed run.
    It also records an explicit not-started state when setup failed earlier.
    """
    destination.mkdir(parents=True, exist_ok=True)
    if not (destination / 'result.json').exists():
        value = {'status': 'no_live_ledger', 'raw_sha256': {}}
    else:
        ledger = read(destination / 'result.json')
        run_id = ledger['experiment_id']
        require(type(run_id) is str and re.fullmatch('[a-f0-9]{8}', run_id), 'Invalid retained experiment ID')
        source = ROOT / 'artifacts' / ('experiment-' + run_id)
        value = {'status': 'partial_snapshot_only', 'original_ledger_status': ledger['status'],
                 'atomic_database_snapshot': False,
                 'raw_sha256': export(source, destination / 'retained-after-step')}
        value['sqlite_sidecars'] = [n for n in value['raw_sha256'] if 'operations.sqlite-' in n]
    save(destination / 'retained-after-step.json', value)


def run_shard(plan_path, shard, destination):
    declared = read(plan_path)
    require(declared == plan(declared['frozen_at']) and type(shard) is int and 0 <= shard < len(GROUPS),
            'Plan or source changed')
    destination.mkdir(parents=True, exist_ok=False)
    save(destination / 'plan.json', declared)
    run_id = uuid.uuid4().hex[:8]
    source = ROOT / 'artifacts' / ('experiment-' + run_id)
    result = {'status': 'failed', 'shard': shard, 'started_at': time.time(),
              'experiment_id': run_id, 'stage': 'execution'}
    save(destination / 'result.json', result)
    try:
        run_experiment(declared['shards'][shard], run_id=run_id)
        result['raw_sha256'] = export(source, destination / 'raw')
        result['stage'] = 'independent_reproduction'
        result['rows'] = audit_copy(destination / 'raw', shard, declared['frozen_at'])
        verify_export(destination / 'raw', result['raw_sha256'])
        require(declared == plan(declared['frozen_at']), 'Source changed during execution')
        result.update(status='passed', stage='complete')
    except BaseException as error:
        result.update(error_type=type(error).__name__)
        raise
    finally:
        try:
            if not (destination / 'raw').exists():
                result['raw_sha256'] = export(source, destination / 'raw')
        except Exception as error:
            result.update(status='failed', export_error_type=type(error).__name__)
        result['finished_at'] = time.time()
        save(destination / 'result.json', result)
    require(result['status'] == 'passed', 'Shard failed; original attempts retained')


def reproduce(plan_path, source, destination):
    declared = read(plan_path)
    require(declared == plan(declared['frozen_at']), 'Plan or source changed')
    destination.mkdir(parents=True, exist_ok=False)
    result = {'status': 'incomplete', 'shards': {}, 'errors': {}, 'decision': None}
    rows = []
    save(destination / 'reproduction.json', result)
    for shard in range(len(GROUPS)):
        directory = source / ('observer-reconciliation-shard-' + str(shard))
        try:
            require(read(directory / 'plan.json') == declared, 'Shard plan differs')
            ledger = read(directory / 'result.json')
            require(ledger['status'] == 'passed' and ledger['shard'] == shard, 'Original shard failed')
            verify_export(directory / 'raw', ledger['raw_sha256'])
            actual = audit_copy(directory / 'raw', shard, declared['frozen_at'])
            require(actual == ledger['rows'], 'Shard outcome does not reproduce')
            result['shards'][str(shard)] = actual
            rows.extend(actual)
        except Exception as error:
            result['errors'][str(shard)] = {'error_type': type(error).__name__, 'reason': str(error)}
    if not result['errors']:
        try:
            result['negative_controls'] = controls(source, declared['frozen_at'], destination / 'controls')
            result['decision'] = decide(rows)
            result['status'] = 'complete'
        except Exception as error:
            result['errors']['selection'] = {'error_type': type(error).__name__, 'reason': str(error)}
    save(destination / 'reproduction.json', result)
    require(result['status'] == 'complete', 'Reproduction incomplete; benefit decision withheld')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    freeze = sub.add_parser('freeze')
    freeze.add_argument('destination', type=Path)
    run = sub.add_parser('run')
    run.add_argument('plan', type=Path)
    run.add_argument('shard', type=int)
    run.add_argument('destination', type=Path)
    replay = sub.add_parser('reproduce')
    replay.add_argument('plan', type=Path)
    replay.add_argument('source', type=Path)
    replay.add_argument('destination', type=Path)
    retain = sub.add_parser('retain')
    retain.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        require(not args.destination.exists(), 'Cannot replace frozen declaration')
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        save(args.destination, plan(time.time()))
    elif args.command == 'run':
        run_shard(args.plan, args.shard, args.destination)
    elif args.command == 'retain':
        retain_after_step(args.destination)
    else:
        reproduce(args.plan, args.source, args.destination)
