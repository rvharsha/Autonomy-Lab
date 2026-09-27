"""Replay the pinned original cohort after diagnosing the WAL reader side effect.

This entry point preserves the original failed workflow status. It uses the exact
original evaluator/criteria in a scratch tree; it cannot execute a workload or
retry/replace a trial. Original archives and exported file digests remain intact.
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def file_hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def original_inputs(directory, ledger):
    """Accept only the observed, exactly diagnosed integrity-check failure."""
    expected = ledger['raw_sha256']
    if not (ledger['status'] == 'failed' and ledger['stage'] == 'independent_reproduction'
            and ledger['error_type'] == 'Refused' and len(ledger['rows']) == 8):
        raise ValueError('Not the diagnosed post-evaluation reader failure')
    actual = file_hashes(directory / 'raw')
    if not expected or any(actual.get(name) != sha for name, sha in expected.items()):
        raise ValueError('Original exported bytes changed or disappeared')
    extras = set(actual) - set(expected)
    databases = [n for n in expected if n.endswith('/operations.sqlite')]
    allowed = {n + suffix for n in databases for suffix in ('-wal', '-shm')}
    if len(databases) != 8 or extras != allowed:
        raise ValueError('Additional files are not the diagnosed SQLite sidecars')
    for name in extras:
        required_size = 0 if name.endswith('-wal') else 32768
        if (directory / 'raw' / name).stat().st_size != required_size:
            raise ValueError('Unexpected SQLite sidecar content size')
    retained = json.loads((directory / 'retained-after-step.json').read_text())
    if (retained['original_ledger_status'] != 'failed' or retained['raw_sha256'] != expected
            or file_hashes(directory / 'retained-after-step') != expected):
        raise ValueError('Independent post-step copy does not preserve the original export')
    return {'original_status': 'failed', 'original_files_verified': len(expected),
            'extra_sidecars': sorted(extras), 'independent_copy_matches': True}


def replay(frozen_source, archives, destination):
    frozen_source = frozen_source.resolve()
    # Import only the exact frozen evaluator. The corrective wrapper and original
    # source are separately retained; current policy/evaluator edits cannot enter.
    sys.path[:0] = [str(frozen_source / 'src'), str(frozen_source)]
    from autonomy_lab.campaign import read
    from autonomy_lab.harness import save
    from autonomy_lab.procedures import require
    from experiments.observer_reconciliation import gate, negative

    require(Path(gate.__file__).resolve().is_relative_to(frozen_source), 'Original evaluator was not isolated')
    spec = json.loads(Path(__file__).with_name('original-artifacts.json').read_text())
    require(spec['source_commit'] == 'd19fa2e868b70feb22f368f0ae3a6b2dfe3d65b2'
            and spec['workflow_run'] == 36345940967, 'Unexpected recovery source')
    destination.mkdir(parents=True, exist_ok=False)
    result = {'status': 'incomplete', 'kind': 'corrected_offline_audit',
              'original_workflow_status': 'failed', 'live_retries': 0,
              'shards': {}, 'diagnosis': {}, 'errors': {}, 'decision': None}
    save(destination / 'reproduction.json', result)
    try:
        with tempfile.TemporaryDirectory(prefix='observer-original-replay-') as temporary:
            scratch = Path(temporary)
            original = scratch / 'original'
            working = scratch / 'working'
            for item in spec['artifacts']:
                path = archives / (str(item['id']) + '.zip')
                require(hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], 'Original ZIP digest differs')
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        name = PurePosixPath(member.filename)
                        require(not name.is_absolute() and '..' not in name.parts and '\\' not in member.filename,
                                'Unsafe original archive path')
                    archive.extractall(original / item['name'])
            before = file_hashes(original)
            declared = read(original / 'observer-reconciliation-plan/plan.json')
            require(declared == gate.plan(declared['frozen_at']), 'Frozen source or original plan differs')
            failed = read(original / 'observer-reconciliation-reproduction/reproduction.json')
            require(failed['status'] == 'incomplete' and failed['decision'] is None,
                    'Original reproduction did not withhold its decision')
            rows = []
            for shard in range(4):
                name = 'observer-reconciliation-shard-' + str(shard)
                directory = original / name
                ledger = read(directory / 'result.json')
                require(read(directory / 'plan.json') == declared and ledger['shard'] == shard,
                        'Original shard identity differs')
                result['diagnosis'][str(shard)] = original_inputs(directory, ledger)
                target = working / name / 'raw'
                shutil.copytree(directory / 'retained-after-step', target)
                actual = gate.evaluate(target, shard, declared['frozen_at'])
                require(actual == ledger['rows'], 'Original evaluated rows differ from reconstruction')
                result['shards'][str(shard)] = actual
                rows.extend(actual)
            result['negative_controls'] = negative.controls(working, declared['frozen_at'], scratch / 'controls')
            result['decision'] = gate.decide(rows)
            require(file_hashes(original) == before, 'Original extraction changed during replay')
            result['original_members_verified'] = len(before)
            result['status'] = 'complete'
    except Exception as error:
        result['errors']['recovery'] = {'error_type': type(error).__name__, 'reason': str(error)}
        raise
    finally:
        save(destination / 'reproduction.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frozen_source', type=Path)
    parser.add_argument('archives', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    replay(args.frozen_source, args.archives, args.destination)
