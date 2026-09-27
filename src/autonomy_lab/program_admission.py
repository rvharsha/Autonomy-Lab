"""Evaluated finite programs and serialized, one-use dispatch authorization.

Controller, evaluator, runtime and ledger storage are trusted. A durable episode
pin selects a definition; only a fresh authorization can precede a new dispatch.
Withdrawal and authorizations take the same SQLite write lock. Already committed
authorizations may have in-flight effects and are never automatically replayed.
"""

import hashlib
import json
import re
import time

from autonomy_lab.broker import Proposal
from autonomy_lab.durable_contract import LEGACY, validate_binding
from autonomy_lab.procedure import parse, validate_pin
from autonomy_lab.procedures import (
    Refused,
    Registry,
    calibration_config,
    digest,
    encoded,
    evaluate_evidence,
    require,
)

ADVERSE = b'{"schema_version":1,"backend_unavailable":"verify","repairable_routing":"escalate","conditional_rejection":"refresh"}'
ADVERSE_FAILURES = {'routing', 'lost_ack'}


def configuration(raw):
    parse(raw)
    return {**calibration_config(), 'name': 'program-admission-calibration',
            'variants': ['program', 'program_adverse', 'no_agent'],
            'procedure_programs': {'program': raw.decode('utf-8'), 'program_adverse': ADVERSE.decode('utf-8')}}


def evaluate(directory, raw, *, adverse=False):
    config = configuration(raw)
    control = legacy_receipt(evaluate_evidence(directory, 'program_adverse', config, program=ADVERSE))
    require(control['eligible'] is False and
            {o['scenario'] for o in control['outcomes'] if not o['task_success']} == ADVERSE_FAILURES
            and {o['scenario'] for o in control['outcomes'] if not o['environment_matches']} == ADVERSE_FAILURES,
            'Adverse calibration control does not discriminate the declared recovery cases')
    receipt = control if adverse else legacy_receipt(evaluate_evidence(directory, 'program', config, program=raw))
    return {**receipt, 'adverse_control': {'version': control['version'], 'receipt_sha256': digest(control),
                                         'failed_scenarios': sorted(ADVERSE_FAILURES)}}


def legacy_receipt(receipt):
    definition = {**receipt['definition'], 'operation_contract': LEGACY}
    return {**receipt, 'definition': definition, 'version': digest(definition)}


def request_digest(proposal):
    request = Proposal.model_validate(proposal).model_dump()
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def execution_conditions(proposal, binding, patch):
    """Only the calibrated legacy semantics are admitted by this registry.

    The trusted broker supplies its stored binding and the exact constructed
    patch, while holding its claim lock. No agent-supplied condition is accepted.
    The precise contract requires its own raw qualification and admission path.
    """
    request = Proposal.model_validate(proposal).model_dump()
    try:
        validate_binding(request, binding)
    except (ValueError, TypeError, KeyError) as error:
        raise Refused('Durable binding does not match the proposal') from error
    require(binding['contract_id'] == LEGACY, 'Execution contract has not been admitted')
    require(type(patch) is list and len(patch) == 5 and type(patch[2]) is dict,
            'Dispatch patch differs from admitted semantics')
    match = re.fullmatch(r'/spec/ports/(0|[1-9][0-9]*)/name', str(patch[2].get('path')))
    require(match is not None, 'Dispatch patch differs from admitted semantics')
    path = '/spec/ports/' + match[1]
    expected = [
        {'op': 'test', 'path': '/metadata/uid', 'value': request['service_uid']},
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': request['resource_version']},
        {'op': 'test', 'path': path + '/name', 'value': request['port_name']},
        {'op': 'test', 'path': path + '/targetPort', 'value': request['expected_target_port']},
        {'op': 'replace', 'path': path + '/targetPort', 'value': request['target_port']},
    ]
    require(encoded(patch) == encoded(expected), 'Dispatch patch differs from admitted semantics')
    return {'operation_id': request['operation_id'], 'binding': encoded(binding).decode(),
            'patch': encoded(patch).decode()}


class ProgramRegistry(Registry):
    def __init__(self, path):
        super().__init__(path)
        with self.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS authorizations (
                operation_id TEXT PRIMARY KEY, episode TEXT NOT NULL, version TEXT NOT NULL,
                activation_revision INTEGER NOT NULL, decision_revision INTEGER NOT NULL,
                program_version TEXT NOT NULL, request_sha256 TEXT NOT NULL, authorized_at REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS authorization_conditions (
                operation_id TEXT PRIMARY KEY, binding TEXT NOT NULL, patch TEXT NOT NULL)''')

    def promote(self, directory, raw, *, expected_revision, adverse=False):
        """Evaluate this calibration candidate, or explicitly select its adverse control.

        raw always identifies the calibration configuration, which binds both
        byte strings. adverse=True deliberately records the fixed control's
        rejection/version, not a rejection of the positive candidate.
        """
        try:
            receipt = evaluate(directory, raw, adverse=adverse)
            return self._record_promotion(receipt, expected_revision)
        except Exception as error:
            self.record_refusal('promote_program', expected_revision, error)
            raise

    def _selection(self, definition):
        require(definition.get('kind') == 'restricted_program', 'Admission is not a restricted program')
        require(definition.get('operation_contract') == LEGACY,
                'Admission does not bind the calibrated execution contract')
        pin = definition['program']
        validate_pin(pin['definition']['program_utf8'].encode('utf-8'), pin)
        return {'program_version': pin['version']}

    def pin(self, episode):
        """Inspect an existing selection; only start_episode may create one."""
        with self.transaction() as db:
            row = db.execute('SELECT * FROM pins WHERE episode=?', (episode,)).fetchone()
            require(row is not None, 'Program episode must be started before inspecting its pin')
            return dict(row)

    def authorize(self, pin, proposal, raw, *, binding, patch):
        """Commit a new one-use authorization or retain refusal, never reuse one.

        This is called only by the trusted broker before its dispatch claim. The
        registry transaction orders authorization against withdrawal/promotion;
        no wall-clock ordering is relied on for that decision.
        """
        proposal = Proposal.model_validate(proposal)
        try:
            conditions = execution_conditions(proposal, binding, patch)
            with self.transaction() as db:
                require(type(pin) is dict and set(pin) == {'episode', 'version', 'revision', 'program_version'},
                        'Malformed admitted episode pin')
                state = db.execute('SELECT * FROM state WHERE id=1').fetchone()
                require(state['active'] == pin['version'] and state['active'] is not None
                        and type(pin['revision']) is int and state['active_revision'] == pin['revision'],
                        'Program admission no longer active')
                selected = db.execute('SELECT * FROM pins WHERE episode=?', (pin['episode'],)).fetchone()
                require(selected is not None and encoded(dict(selected)) == encoded(
                    {k: pin[k] for k in ('episode', 'version', 'revision')}), 'Episode pin differs from ledger')
                version = db.execute('SELECT * FROM versions WHERE version=?', (pin['version'],)).fetchone()
                require(version is not None and not version['withdrawn'], 'Program was withdrawn')
                definition = json.loads(version['definition'])
                require(self._selection(definition) == {'program_version': pin['program_version']},
                        'Admitted program selection changed')
                validate_pin(raw, definition['program'])
                require(db.execute('SELECT 1 FROM authorizations WHERE operation_id=?',
                                   (proposal.operation_id,)).fetchone() is None, 'Operation already authorized')
                authorization = {'operation_id': proposal.operation_id, 'episode': pin['episode'],
                    'version': pin['version'], 'activation_revision': pin['revision'],
                    'decision_revision': state['revision'], 'program_version': pin['program_version'],
                    'request_sha256': request_digest(proposal), 'authorized_at': time.time()}
                db.execute('INSERT INTO authorizations VALUES (?,?,?,?,?,?,?,?)', tuple(authorization.values()))
                db.execute('INSERT INTO authorization_conditions VALUES (?,?,?)', tuple(conditions.values()))
                return authorization
        except Exception as error:
            self.record_dispatch_refusal(proposal, error)
            raise

    def record_dispatch_refusal(self, proposal, error):
        details = {'operation_id': proposal.operation_id, 'request_sha256': request_digest(proposal),
                   'at': time.time(), 'error_type': type(error).__name__,
                   'reason': str(error) if isinstance(error, Refused) else 'Authorization unavailable or malformed'}
        with self.transaction() as db:
            db.execute('INSERT INTO refusals(action,details) VALUES (?,?)',
                       ('authorize_dispatch', encoded(details).decode()))

    def authorization(self, pin, proposal, *, binding, patch):
        """Read a committed authorization immediately before its one API call.

        Deliberately do not require current activation: withdrawal cannot cancel
        an authorization that won the transaction order. The broker's one-use
        claim and per-operation durable binding prevent execution replay.
        """
        conditions = execution_conditions(proposal, binding, patch)
        with self.transaction() as db:
            bound = db.execute('SELECT * FROM authorization_conditions WHERE operation_id=?',
                               (proposal.operation_id,)).fetchone()
            require(bound is not None and dict(bound) == conditions,
                    'Dispatch conditions differ from their authorization')
            row = db.execute('SELECT * FROM authorizations WHERE operation_id=?', (proposal.operation_id,)).fetchone()
            require(row is not None and row['request_sha256'] == request_digest(proposal)
                    and row['episode'] == pin['episode'] and row['version'] == pin['version']
                    and row['activation_revision'] == pin['revision'] and row['program_version'] == pin['program_version'],
                    'Dispatch does not match its authorization')
            return dict(row)
