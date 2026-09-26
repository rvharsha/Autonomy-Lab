"""Versioned, trusted operation conditions; no agent-selected permissions."""

import hashlib
import json

from autonomy_lab.operation_contract import repair_patch

LEGACY = 'service-resource-version-v1'
PRECISE = 'service-routing-heartbeat-v1'
CONTRACTS = (LEGACY, PRECISE)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def binding_for(request, contract_id, snapshot=None):
    if contract_id not in CONTRACTS or (contract_id == LEGACY and snapshot is not None):
        raise ValueError('Invalid operation contract')
    value = {'operation_id': request['operation_id'], 'request_sha256': digest(request),
             'contract_id': contract_id, 'snapshot': snapshot}
    return {**value, 'binding_sha256': digest(value)}


def validate_binding(request, binding):
    if not isinstance(binding, dict) or binding != binding_for(
            request, binding.get('contract_id'), binding.get('snapshot')):
        raise ValueError('Operation conditions do not match their durable binding')


def patch_for_binding(request, binding):
    """Recognize this complete versioned action, never a partial patch allowlist."""
    validate_binding(request, binding)
    snapshot = binding['snapshot']
    if binding['contract_id'] != PRECISE or not isinstance(snapshot, dict):
        raise ValueError('Precise conditions have not been recorded')
    for name, expected in {'namespace': 'autonomy-lab', 'service_name': 'inventory',
                           'port_name': 'http', 'expected_target_port': 9999,
                           'target_port': 8080}.items():
        if type(request.get(name)) is not type(expected) or request[name] != expected:
            raise ValueError('Action outside the precise contract')
    for key, field in [('uid', 'service_uid'), ('resourceVersion', 'resource_version'),
                       ('namespace', 'namespace'), ('name', 'service_name')]:
        if snapshot.get('metadata', {}).get(key) != request[field]:
            raise ValueError('Conditions differ from the original proposal')
    return repair_patch(snapshot, 'contract')
