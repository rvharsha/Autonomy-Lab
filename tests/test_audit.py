"""Authored audit records test correlation, not actual system safety."""

import os
from pathlib import Path

import pytest

from autonomy_lab.audit import assess, configure, read_events


def test_configure_creates_private_controller_owned_log_before_server_start(tmp_path):
    configure(tmp_path, Path(__file__).parents[1] / 'infra/kind.yaml')
    directory = tmp_path / 'server-audit'
    log = directory / 'events.jsonl'
    assert directory.stat().st_mode & 0o777 == 0o700
    assert log.stat().st_mode & 0o777 == 0o600
    assert log.stat().st_uid == os.getuid()
    assert log.read_bytes() == b''
    log.write_text('retained evidence')
    with pytest.raises(FileExistsError):
        configure(tmp_path, Path(__file__).parents[1] / 'infra/kind.yaml')
    assert log.read_text() == 'retained evidence'


def test_truncated_tail_preserves_complete_events_and_marks_assessment_incomplete(tmp_path):
    (tmp_path / 'events.jsonl').write_text('{"auditID":"complete","stage":"ResponseComplete"}\n{"partial":')
    captured = read_events(tmp_path)
    assert captured['events'][0]['auditID'] == 'complete'
    assert captured['malformed_lines'] == 1
    result = assess(captured['events'], [], started_at='1', finished_at='3', malformed_lines=1)
    assert result['status'] == 'incomplete'


def test_missing_acknowledged_write_cannot_be_reported_as_assessed():
    read = {'auditID': 'read', 'verb': 'get', 'requestReceivedTimestamp': '2',
            'objectRef': {'namespace': 'autonomy-lab'}}
    result = assess([read], [{'operation_id': 'missing', 'status': 'acknowledged'}], started_at='1', finished_at='3')
    assert result['status'] == 'incomplete'
    assert result['missing_acknowledged_operations'] == ['missing']


def test_successful_observer_write_is_detected_but_denied_write_is_not_execution():
    event = {'auditID': 'write', 'verb': 'patch', 'requestReceivedTimestamp': '2',
             'objectRef': {'namespace': 'autonomy-lab'}, 'responseStatus': {'code': 200},
             'user': {'username': 'system:serviceaccount:autonomy-lab:observer'}}
    assert assess([event], [], started_at='1', finished_at='3')['successful_unmatched_mutations'] == 1
    event['responseStatus']['code'] = 403
    assert assess([event], [], started_at='1', finished_at='3')['successful_unmatched_mutations'] == 0
