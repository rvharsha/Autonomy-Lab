"""Execute the declared 44-trial comparison once; retain failed and unrun trials."""

import argparse
import hashlib
import json
import uuid
from pathlib import Path

import yaml

from autonomy_lab.experiments import release_manifest, run_experiment, validate_config
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path('~/Dev/.env'))
    args = parser.parse_args()
    phases = []
    for name in ['baseline', 'treatment', 'regressions', 'heldout']:
        path = ROOT / 'scenarios' / ('context-' + name + '.yaml')
        config = yaml.safe_load(path.read_text())
        validate_config(config)
        phases.append({'name': name, 'config': config, 'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'planned': len(config['scenarios']) * len(config['variants']) * config['repetitions'], 'status': 'unrun'})
    if sum(phase['planned'] for phase in phases) != 44:
        raise ValueError('Unexpected declared comparison size')
    output = ROOT / 'artifacts' / ('context-evaluation-' + uuid.uuid4().hex[:8])
    output.mkdir(mode=0o700)
    files = release_manifest(phases[0]['config'])['files']
    record = {'status': 'running', 'source_files': files, 'phases': phases, 'planned': 44}
    save(output / 'evaluation.json', record)
    print(output, flush=True)
    try:
        for phase in phases:
            if release_manifest(phase['config'])['files'] != files:
                raise RuntimeError('Source changed after evaluation freeze')
            phase['status'] = 'running'
            save(output / 'evaluation.json', record)
            run_dir = run_experiment(phase['config'], env_file=args.env_file)
            phase.update(status='finished', run_dir=str(run_dir),
                         accounting=json.loads((run_dir / 'accounting.json').read_text()))
            save(output / 'evaluation.json', record)
        record['status'] = 'finished'
    except BaseException as error:
        record.update(status='stopped', error_type=type(error).__name__)
        raise
    finally:
        save(output / 'evaluation.json', record)
        print(output, flush=True)


if __name__ == '__main__':
    main()
