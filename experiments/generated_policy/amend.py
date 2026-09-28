"""Explicit post-proposal harness correction, with no new model/service outcome."""

import sys
import time
from pathlib import Path

from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, command
from autonomy_lab.procedures import require
from experiments.experience_learning.evaluate import read

from .propose import verify_proposal
from .protocol import plan

ORIGINAL = ROOT / 'docs/validation/generated-policy-v2'


def verify_execution(declaration, proposal):
    require(declaration['plan'] == plan(), 'Execution source changed')
    original = read(ORIGINAL / 'declaration.json')
    require(declaration['proposal_declaration'] == original, 'Pre-generation declaration changed')
    verify_proposal(original, proposal)
    require(proposal == read(ORIGINAL / 'proposal.json'), 'Generated proposal changed')
    require(proposal['finished_at'] < declaration['frozen_at'], 'Amendment order differs')
    # Prevent this harness amendment from tuning schedules, criteria or budgets.
    for key, value in original['plan'].items():
        if key not in ('version', 'files'):
            require(declaration['plan'][key] == value, 'Experimental contract changed')


def freeze(destination):
    destination.mkdir(parents=True, exist_ok=False)
    proposal = read(ORIGINAL / 'proposal.json')
    declaration = {'frozen_at': time.time(), 'source_commit': command(['git', 'rev-parse', 'HEAD']).strip(),
                   'plan': plan(), 'proposal_declaration': read(ORIGINAL / 'declaration.json'),
                   'prior_failed_workflow': 36368302162,
                   'reason': 'Authored output-flood cleanup race and missing artifact directory; no service batches ran. Candidate, request, budgets, schedules and criteria unchanged.'}
    verify_execution(declaration, proposal)
    save(destination / 'declaration.json', declaration)
    save(destination / 'proposal.json', proposal)


if __name__ == '__main__':
    freeze(Path(sys.argv[1]))
