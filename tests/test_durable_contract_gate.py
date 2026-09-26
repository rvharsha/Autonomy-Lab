"""Evidence-shape counterexamples, not fabricated live experiment results."""

import copy
import fnmatch
import runpy

import pytest
import yaml

from autonomy_lab.durable_contract_gate import adversarial_checks, assess, verification_valid
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.verifier import evaluate_snapshot, load_expectations


def test_empty_cohort_or_audit_cannot_pass_or_seed_corruption_tests():
    captured = {'events': [], 'collection_closed': True, 'malformed_lines': 0}
    assert assess([], captured, 'deleted')['status'] == 'failed'
    with pytest.raises(ValueError, match='positive control'):
        adversarial_checks([], captured, 'deleted')


def test_single_probe_does_not_establish_a_complete_window():
    value = {'probes': [], 'verdict': 'verified_success', 'window_seconds': 3}
    assert verification_valid(value, {'quotes': [], 'products': []}) is False


@pytest.mark.parametrize('defect', ['database_outage', 'damaged_data', 'missing_case', 'wrong_body', 'summary'])
def test_known_customer_failure_cannot_conceal_missing_or_damaged_evidence(defect):
    expectations = load_expectations()
    snapshot = {'quote_control': {'kind': 'response', 'status_code': 200},
                'inventory_control': {'kind': 'response', 'status_code': 200},
                'database': {'kind': 'rows', 'rows': copy.deepcopy(expectations['products'])},
                'service': {'kind': 'resource', 'resource': {'metadata': {'name': 'inventory'},
                    'spec': {'selector': {'app': 'inventory'}, 'ports': [
                        {'name': 'http', 'port': 80, 'targetPort': 9999, 'protocol': 'TCP'}]}}},
                'quotes': [{'case_id': case['id'], 'kind': 'response', 'status_code': 503} for case in expectations['quotes']]}
    def window(observation):
        assessment = evaluate_snapshot(observation, expectations)
        return {**assessment, 'window_seconds': 3, 'started_at': '2026-09-26T00:00:00Z',
                'finished_at': '2026-09-26T00:00:04Z', 'probes': [
                    {**assessment, 'offset_seconds': offset, 'observations': observation} for offset in (0, 3)]}
    assert verification_valid(window(snapshot), expectations)
    if defect == 'database_outage':
        snapshot['database'] = {'kind': 'error'}
    elif defect == 'damaged_data':
        snapshot['database']['rows'][0]['stock'] += 1
    elif defect == 'missing_case':
        snapshot['quotes'].pop()
    elif defect == 'wrong_body':
        selected = next(c for c in expectations['quotes'] if c['status_code'] == 200 and 'body' in c)
        next(q for q in snapshot['quotes'] if q['case_id'] == selected['id']).update(status_code=200, body={})
    result = window(snapshot)
    if defect == 'summary':
        result['reasons'] = []
    assert result['verdict'] == 'verified_failure'
    assert verification_valid(result, expectations) is False


def test_ci_covers_all_frozen_inputs_and_direct_dependencies(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    runner = runpy.run_path(str(ROOT / 'scripts/check_durable_contract.py'))
    workflow = yaml.load((ROOT / '.github/workflows/durable-contract.yml').read_text(), Loader=yaml.BaseLoader)
    patterns = workflow['on']['pull_request']['paths']
    inputs = {*runner['source_receipt'](), 'uv.lock', 'pyproject.toml',
              'tests/test_durable_contract.py', 'tests/test_durable_contract_gate.py',
              '.github/workflows/durable-contract.yml'}
    assert all(any(fnmatch.fnmatch(path, pattern) for pattern in patterns) for path in inputs)
