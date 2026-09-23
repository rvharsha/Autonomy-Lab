"""Authored janitor failure cases; real controller-kill evidence is separate."""

import json
import subprocess

from autonomy_lab import janitor


def test_watch_survives_transient_metadata_and_process_errors(tmp_path, monkeypatch):
    (tmp_path / 'janitor-lease.json').write_text(json.dumps({'controller_pid': 5, 'controller_identity': 'start',
                                                         'expires_at': 100, 'cluster': 'autolab-12345678'}))
    (tmp_path / 'environment.json').write_text('partial')
    monkeypatch.setattr(janitor.time, 'time', lambda: 1)
    sleeps = []
    def sleep(_):
        sleeps.append(1)
        (tmp_path / 'environment.json').write_text('{"status":"running"}')
    def identity(_):
        if len(sleeps) == 1:
            raise subprocess.TimeoutExpired('ps', 5)
        return ''
    monkeypatch.setattr(janitor.time, 'sleep', sleep)
    monkeypatch.setattr(janitor, 'process_identity', identity)
    cleaned = []
    monkeypatch.setattr(janitor, 'cleanup', lambda path, lease: cleaned.append(lease['cluster']))
    janitor.main(tmp_path)
    assert len(sleeps) == 2
    assert cleaned == ['autolab-12345678']


def test_process_identity_uses_fixed_timezone_and_locale(monkeypatch):
    seen = []
    def run(*args, **kwargs):
        seen.append(kwargs['env'])
        return subprocess.CompletedProcess(args, 0, stdout='same start\n')
    monkeypatch.setattr(janitor.subprocess, 'run', run)
    monkeypatch.setenv('TZ', 'Pacific/Honolulu')
    assert janitor.process_identity(1) == 'same start'
    assert seen[0]['TZ'] == 'UTC'
    assert seen[0]['LC_ALL'] == 'C'
