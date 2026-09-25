"""Finite policy language over trusted runbook decisions, not generated code.

There are eight configurations. Parsing is not admission: execution is permitted
only by the caller's existing experimental authority. The broker and verifier
remain mandatory. Source hashes detect drift on the trusted host, not tampering
by that host or a sandbox escape.
"""

import hashlib
import json
import math
from dataclasses import dataclass

MAX_BYTES = 4096
CHOICES = {
    'backend_unavailable': ('escalate', 'verify'),
    'repairable_routing': ('escalate', 'repair'),
    'conditional_rejection': ('escalate', 'refresh'),
}


@dataclass(frozen=True)
class Decisions:
    backend_unavailable: str
    repairable_routing: str
    conditional_rejection: str


def parse(raw: bytes) -> Decisions:
    """Reject extensions, duplicate keys, coercions and oversized input up front."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('Procedure requires bounded UTF-8 bytes')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate procedure key')
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        valid = (type(value) is dict and set(value) == {'schema_version', *CHOICES}
                 and type(value['schema_version']) is int and value['schema_version'] == 1
                 and all(type(value[k]) is str and value[k] in choices for k, choices in CHOICES.items()))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError('Malformed procedure') from error
    if not valid:
        raise ValueError('Unsupported procedure schema or decision')
    return Decisions(**{k: value[k] for k in CHOICES})


def freeze(raw: bytes) -> dict:
    """Bind exact bytes and the existing release dependency manifest."""
    from autonomy_lab.experiments import release_manifest

    parse(raw)
    definition = {'schema_version': 1, 'program_utf8': raw.decode('utf-8'),
                  'program_sha256': hashlib.sha256(raw).hexdigest(),
                  'runtime_files': release_manifest({})['files']}
    version = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    return {'version': version, 'definition': definition}


def validate_pin(raw: bytes, pin: dict) -> Decisions:
    expected = freeze(raw)
    try:
        matches = type(pin) is dict and json.dumps(pin, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True)
    except (TypeError, ValueError):
        matches = False
    if not matches:
        raise ValueError('Procedure bytes or runtime differ from frozen definition')
    return parse(raw)


def run(toolbox, raw: bytes, *, pin: dict) -> dict:
    from autonomy_lab.runbook import execute

    # A different definition cannot adopt or resume another workspace's claim.
    decisions = validate_pin(raw, pin)
    if toolbox.terminal is not None or toolbox.call_count:
        raise ValueError('Program execution requires a fresh workspace')
    return execute(toolbox, decisions)


def verify_bindings(directory, spec, card, evidence, journal, audit, *, refused_operations=()):
    """Independently bind every actual dispatch to its prior frozen episode."""
    from autonomy_lab.campaign import read
    from autonomy_lab.procedures import require
    from autonomy_lab.recurrence import epoch

    raw = spec['contract']['procedure_program'].encode('utf-8')
    expected = freeze(raw)
    validate_pin(raw, spec['program_pin'])
    validate_pin(raw, read(directory / 'program-definition.json'))
    operations = {op['operation_id']: op for op in card['operations']}
    for operation_id in refused_operations:
        require(operation_id in operations and operations[operation_id]['status'] == 'rejected'
                and operations[operation_id]['reason'] == 'dispatch_authorization_refused'
                and operations[operation_id]['budget_reserved'] == 0,
                'Only a refused unsent authorization can lack a dispatch binding')
        del operations[operation_id]
    seen = set()
    for worker in card['workers']:
        for episode in worker['episodes']:
            path = directory / 'workers' / worker['id'] / episode['id']
            observed = next(e for e in evidence[worker['id']] if e['id'] == episode['id'])
            records = observed['records']
            # A scheduled kill may land between the attempt and pin writes.
            # That empty attempt makes no claim and cannot own any operation.
            if not (path / 'program.json').exists():
                require(not records and type(observed.get('uncommitted_bytes')) is int
                        and observed['uncommitted_bytes'] == 0
                        and episode.get('outcome') is None and not list(path.glob('operation-*.json')),
                        'Missing pin for an episode with execution evidence')
                continue
            pin = read(path / 'program.json')
            require(type(pin) is dict and set(pin) == {'at', 'pin'}, 'Malformed program pin record')
            validate_pin(raw, pin['pin'])
            require(set(pin) == {'at', 'pin'} and pin['pin'] == expected
                    and type(pin['at']) in {int, float} and math.isfinite(pin['at'])
                    and episode['attempt']['started_at'] <= pin['at']
                    and all(pin['at'] <= epoch(r['timestamp']) for r in records),
                    'Program was not pinned before episode evidence')
            observation_ids = {r['observation_id'] for r in records}
            for file in path.glob('operation-*.json'):
                binding = read(file)
                require(type(binding) is dict and set(binding) == {'at', 'operation_id', 'episode', 'program_version'}
                        and type(binding['operation_id']) is str, 'Malformed operation program binding')
                operation_id = binding['operation_id']
                require(set(binding) == {'at', 'operation_id', 'episode', 'program_version'}
                        and operation_id in operations and operation_id not in seen
                        and file.name == 'operation-' + operation_id + '.json'
                        and binding['episode'] == episode['id'] and binding['program_version'] == expected['version']
                        and type(binding['at']) in {int, float} and math.isfinite(binding['at'])
                        and binding['at'] >= pin['at'], 'Operation program binding differs')
                request = json.loads(operations[operation_id]['request'])
                require(type(request) is dict and type(request.get('evidence_ids')) is list
                        and bool(request['evidence_ids']) and all(type(e) is str for e in request['evidence_ids'])
                        and set(request['evidence_ids']) <= observation_ids,
                        'Operation belongs to a different episode')
                dispatched = [e for e in journal if e['operation_id'] == operation_id and e['event'] == 'dispatching']
                api = [e for e in audit['events'] if e.get('stage') == 'ResponseComplete'
                       and e.get('userAgent') == 'autonomy-lab-operation/' + operation_id
                       and e.get('user', {}).get('username') == 'system:serviceaccount:autonomy-lab:broker']
                require(len(dispatched) == len(api) == 1
                        and epoch(dispatched[0]['timestamp']) <= binding['at'] <= epoch(api[0]['requestReceivedTimestamp']),
                        'Binding was not durable before the actual API request')
                seen.add(operation_id)
    require(seen == set(operations), 'Missing operation program binding')
    return True
