"""A finite update-loop demonstration, not a new discovery or admission gate."""

import hashlib
import math
import random

from autonomy_lab.campaign import read
from autonomy_lab.customer_benefit import declaration as base_declaration
from autonomy_lab.durable_contract import digest
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedures import require
from experiments.contract_confirmation import gate as shared
from experiments.final_slot.gate import CONTEXTS, assess_operations

from .training import select_training

ROLES = ('legacy', 'maintained', 'selected')
SHARDS = 3
EVIDENCE_USE = 'known_context_shadow_update'


def validate_selection(selection):
    require(selection == select_training(selection['evaluations']), 'Training selection changed')


def declaration(role, context, selection):
    validate_selection(selection)
    return _declaration(role, context, selection)


def _declaration(role, context, selection):
    require(role in ROLES and context in CONTEXTS, 'Unknown shadow case')
    execution_arm = {'legacy': 'legacy', 'maintained': 'precise',
                     'selected': selection['selected']}[role]
    value = base_declaration(execution_arm, 'quiet')
    paths = ['experiments/__init__.py', 'docs/SHADOW_SELECTION.md',
             '.github/workflows/shadow-selection.yml',
             *[str(p.relative_to(ROOT)) for folder in ('shadow_selection', 'contract_confirmation', 'final_slot')
               for p in sorted((ROOT / 'experiments' / folder).glob('*.py'))],
             'experiments/shadow_selection/training-artifacts.json']
    value.update(arm=role, context=context, evidence_use=EVIDENCE_USE,
                 execution_arm=execution_arm, selection_digest=digest(selection),
                 provision_timeout_seconds=180, early_change_offset=135, post_ack_offset=85)
    value['gate_sources'].update({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths})
    return value


def plan(selection, frozen_at):
    validate_selection(selection)
    require(type(frozen_at) in (int, float) and math.isfinite(frozen_at) and frozen_at > 0,
            'Invalid selection time')
    cases = {r + '-' + c: _declaration(r, c, selection) for r in ROLES for c in CONTEXTS}
    order = list(cases)
    random.Random(2026092701).shuffle(order)
    return {
        'schema_version': 1, 'evidence_use': EVIDENCE_USE, 'selection': selection, 'frozen_at': frozen_at,
        'order_seed': 2026092701, 'order': order,
        'shards': [order[i::SHARDS] for i in range(SHARDS)], 'cases': cases,
        'attempts_per_case': 1,
        'historical_training_acquisition': selection['historical_training_acquisition'],
        'cost_budget': {'scope': 'New execution only; historical acquisition reported separately',
                        'campaigns': 9, 'dispatches_per_campaign': 2, 'model_requests': 0,
                        'shard_timeout_minutes': 30, 'ci_job_timeout_minutes': 40,
                        'billed_compute_cost': None, 'human_active_seconds': None},
        'limits': [
            'Previously observed, authored contexts; new executions are not sealed or novel tests.',
            'Known human-authored catalogue, automatically selected from reproduced historical evidence.',
            'The selected arm is the exhaustive selector, not evidence of model advantage.',
            'Fresh disposable workloads per case; no cross-grant persistence, admission or deployment.',
            'Sampled customer windows; no generalization, production reliability or net-cost claim.',
        ],
    }


def evaluate(path, selection, frozen_at):
    value = shared.evaluate(path,
                            declaration_fn=lambda r, c: declaration(r, c, selection),
                            operation_auditor=assess_operations)
    require(value['remaining_after_first'] == 1, 'First repair did not leave one dispatch slot')
    require(read(path / 'campaign/window.json')['start'] > frozen_at,
            'Evaluation predates frozen selection')
    value['run_id'] = read(path / 'record.json')['run_id']
    value['workload_uid'] = read(path / 'campaign/identities-before.json')['Service/inventory']
    return value


def select(declared, evaluations):
    require(declared == plan(declared['selection'], declared['frozen_at'])
            and set(evaluations) == set(declared['cases']),
            'Incomplete or changed shadow comparison')
    require(all(isinstance(v[k], str) and v[k] for v in evaluations.values()
                for k in ('run_id', 'workload_uid'))
            and all(len({v[k] for v in evaluations.values()}) == len(evaluations)
                    for k in ('run_id', 'workload_uid')),
            'Comparators must have distinct real executions')
    for name, value in evaluations.items():
        spec = declared['cases'][name]
        require(all(value[k] == spec[k] for k in ('arm', 'context', 'candidate', 'evidence_use')),
                'Candidate identity differs')
        require(value['measurement_valid'] is True and value['authority_conformant'] is True,
                'Invalid or unsafe evidence')
        counts = value['sample_counts']
        require(set(counts) == {'verified_success', 'verified_failure', 'unknown'}
                and all(type(n) is int and n >= 0 for n in counts.values())
                and sum(counts.values()) == 21 and counts['unknown'] == 0,
                'Invalid customer calendar')
        require(type(value['eligible']) is bool and type(value['spent_dispatches']) is int
                and type(value['actual_api_attempts']) is int
                and 0 <= value['spent_dispatches'] == value['actual_api_attempts'] <= 2,
                'Invalid authority accounting')
    eligible = all(v['eligible'] for v in evaluations.values())
    comparisons = {}
    for comparator in ('legacy', 'maintained'):
        pairs = [(evaluations['selected-' + c], evaluations[comparator + '-' + c]) for c in CONTEXTS]
        comparisons[comparator] = {
            'healthy_window_deltas': {c: a['sample_counts']['verified_success'] - b['sample_counts']['verified_success']
                                     for c, (a, b) in zip(CONTEXTS, pairs, strict=True)},
            'dominates': eligible and all(a['sample_counts']['verified_success'] >= b['sample_counts']['verified_success']
                                         and a['spent_dispatches'] <= b['spent_dispatches'] for a, b in pairs)
            and any(a['sample_counts']['verified_success'] > b['sample_counts']['verified_success'] for a, b in pairs),
        }
    # Identical policy/runtime bytes cannot establish a strategy advantage merely
    # because separately executed customer samples have favorable timing noise.
    same_as_maintained = declared['selection']['selected'] == 'precise'
    return {
        'status': 'complete', 'eligible': eligible,
        'decision': 'withhold_ineligible' if not eligible else 'bounded_update_observed'
        if comparisons['legacy']['dominates'] else 'no_update_benefit_observed',
        'selected': declared['selection']['selected'], 'comparisons': comparisons,
        'same_policy_as_maintained': same_as_maintained,
        'incremental_strategy_value_demonstrated': False,
        'autonomous_discovery_demonstrated': False,
        'selection_confers_authority': False, 'promotion': False,
        'confirmation_run': False, 'evaluations': evaluations, 'limits': declared['limits'],
        'historical_training_acquisition': declared['historical_training_acquisition'],
        'new_execution_accounting': {
            'campaigns': len(evaluations),
            'scheduled_customer_windows': sum(sum(v['sample_counts'].values()) for v in evaluations.values()),
            'actual_api_attempts': sum(v['actual_api_attempts'] for v in evaluations.values()),
            'model_requests': 0, 'billed_compute_cost': None, 'human_active_seconds': None,
            'scope': 'Complete new cohort only; excludes historical acquisition, reviews, setup and replay.',
        },
    }
