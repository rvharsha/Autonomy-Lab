"""Experimental conventional reconciliation under one fixed controller intent.

This is trusted authored code, not a generated procedure or an admission path.
The immutable 8080 expectation applies only to a disposable trial. An unavailable
backend observation is never treated as evidence of backend health.
"""

import json
import uuid

from autonomy_lab.runbook import _service_scope


def contract():
    return {'schema_version': 1, 'kind': 'static_inventory_routing',
            'namespace': 'autonomy-lab', 'service_name': 'inventory',
            'port_name': 'http', 'target_port': 8080, 'lifetime': 'single_trial'}


def validate_contract(value):
    if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(contract(), sort_keys=True):
        raise ValueError('Only the fixed disposable routing contract is supported')


def bind(run_id, service_uid):
    if any(type(v) is not str or not v.strip() or len(v) > 253 for v in (run_id, service_uid)):
        raise ValueError('Intent requires bounded run and resource identities')
    return {'contract': contract(), 'run_id': run_id, 'service_uid': service_uid}


def run(tools, intent):
    if intent != bind(tools.run_id, intent['service_uid']):
        raise ValueError('Intent does not bind this trial')
    validate_contract(intent['contract'])
    if tools.call_count or tools.terminal is not None:
        raise ValueError('Reconciliation requires a fresh workspace')
    evidence = []

    def call(name, args=None):
        observation = tools.call(name, args or {})
        if (isinstance(observation.get('observation_id'), str)
                and observation['observation_id'].strip()
                and observation.get('evidence_eligible', True) is True):
            evidence.append(observation['observation_id'])
        return observation['payload']

    def finish(outcome, reason):
        result = call('finish', {'outcome': outcome, 'reason': reason,
                                 'evidence_ids': evidence[:]})
        return dict(tools.terminal) if tools.terminal is not None else result

    observed = call('observe_service')
    # Both comparators receive the same public probes. These are retained even
    # when they fail; neither supplies the desired-state authority.
    call('probe_backend')
    call('probe_application')
    scope = _service_scope(observed)
    if scope is None:
        return finish('escalated', 'Observed resource is outside the declared routing shape.')
    metadata, port = scope
    if (observed.get('run_id') != intent['run_id']
            or metadata['uid'] != intent['service_uid']
            or metadata['namespace'] != intent['contract']['namespace']):
        return finish('escalated', 'Observed resource does not match the controller intent.')
    changed = port['targetPort'] != intent['contract']['target_port']
    if changed:
        operation_id = str(uuid.uuid4())
        operation = call('propose_repair', {
            'run_id': intent['run_id'], 'operation_id': operation_id,
            'namespace': metadata['namespace'], 'service_name': metadata['name'],
            'service_uid': metadata['uid'], 'resource_version': metadata['resourceVersion'],
            'port_name': port['name'], 'expected_target_port': port['targetPort'],
            'target_port': intent['contract']['target_port'], 'evidence_ids': evidence[:],
        })
        if (operation.get('status') in {'uncertain', 'dispatching', 'prepared'}
                or operation.get('kind') == 'error'):
            operation = call('get_operation', {'operation_id': operation_id})
        uncertain_desired = (operation.get('status') == 'uncertain'
                             and (operation.get('reconciliation') or {}).get('observation')
                             == 'desired_state_observed')
        if operation.get('status') != 'acknowledged' and not uncertain_desired:
            return finish('escalated', 'The attempted reconciliation is rejected or unresolved; no retry.')
    verification = call('verify_recovery')
    if verification.get('verdict') != 'verified_success':
        return finish('escalated', 'Desired routing does not establish customer recovery; verification did not pass.')
    return finish('resolved' if changed else 'healthy',
                  'Independent verification established customer health.'
                  + (' Mutation attribution remains uncertain.' if changed and uncertain_desired else ''))
