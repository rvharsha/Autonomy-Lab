"""Evidence-shape counterexamples, not fabricated live experiment results."""

import fnmatch
import runpy

import pytest
import yaml

from autonomy_lab.durable_contract_gate import adversarial_checks, assess, verification_valid
from autonomy_lab.kubernetes import ROOT


def test_empty_cohort_or_audit_cannot_pass_or_seed_corruption_tests():
    captured = {'events': [], 'collection_closed': True, 'malformed_lines': 0}
    assert assess([], captured, 'deleted')['status'] == 'failed'
    with pytest.raises(ValueError, match='positive control'):
        adversarial_checks([], captured, 'deleted')


def test_single_probe_does_not_establish_a_complete_window():
    value = {'probes': [], 'verdict': 'verified_success', 'window_seconds': 3}
    assert verification_valid(value, {'quotes': [], 'products': []}) is False


def test_ci_covers_all_frozen_inputs_and_direct_dependencies(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    runner = runpy.run_path(str(ROOT / 'scripts/check_durable_contract.py'))
    workflow = yaml.load((ROOT / '.github/workflows/durable-contract.yml').read_text(), Loader=yaml.BaseLoader)
    patterns = workflow['on']['pull_request']['paths']
    inputs = {*runner['source_receipt'](), 'uv.lock', 'pyproject.toml',
              'tests/test_durable_contract.py', 'tests/test_durable_contract_gate.py',
              '.github/workflows/durable-contract.yml'}
    assert all(any(fnmatch.fnmatch(path, pattern) for pattern in patterns) for path in inputs)
