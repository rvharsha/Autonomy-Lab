"""Reproduce the fixed historical training cohort, never trust its summary alone."""

import hashlib
import zipfile
from pathlib import PurePosixPath

from autonomy_lab.campaign import read
from autonomy_lab.customer_benefit import plan, select
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from scripts.check_customer_benefit import reproduce

MANIFEST = ROOT / 'experiments/shadow_selection/training-artifacts.json'


def select_training(evaluations):
    result = select(plan(), evaluations)
    require(result['selected'] in {'legacy', 'precise'}, 'Training did not qualify a choice')
    return {
        'schema_version': 1,
        'method': 'exhaustive_two_contract_selection',
        'training_artifacts': read(MANIFEST),
        'evaluations': evaluations,
        'selected': result['selected'],
        'decision': result['decision'],
        'historical_training_acquisition': {
            'campaigns': len(evaluations),
            'scheduled_customer_windows': sum(sum(v['sample_counts'].values()) for v in evaluations.values()),
            'actual_api_attempts': sum(v['actual_api_attempts'] for v in evaluations.values()),
            'source_workflow_run': read(MANIFEST)['run_id'],
            'billed_compute_cost': None, 'human_active_seconds': None,
            'scope': 'Prior acquisition, additional to the nine new campaigns. Review, setup, replay and full request costs are not measured here.',
        },
        'selection_confers_authority': False,
    }


def reproduce_training(archives, destination):
    """Only digest-pinned original ZIPs may supply the known development data."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    manifest = read(MANIFEST)
    for artifact in manifest['artifacts']:
        path = archives / (str(artifact['id']) + '.zip')
        require(path.is_file(), 'Training archive missing')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == artifact['sha256'],
                'Training archive digest differs')
        target = destination / 'raw' / artifact['name']
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                name = PurePosixPath(item.filename)
                require(not name.is_absolute() and '..' not in name.parts
                        and '\\' not in item.filename
                        and (item.external_attr >> 16) & 0o170000 != 0o120000,
                        'Unsafe archive member')
            archive.extractall(target)
    raw = destination / 'raw'
    result = reproduce(raw / 'customer-benefit-plan/plan.json', raw,
                       destination / 'reproduction')
    require(result['status'] == 'complete' and result['negative_controls']['status'] == 'passed',
            'Training reproduction incomplete')
    return select_training(result['evaluations'])
