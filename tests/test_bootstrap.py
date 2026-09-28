"""Authored download-failure checks, not service experiment outcomes."""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('bootstrap_under_test', Path('scripts/bootstrap.py'))
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_transient_download_retries_are_bounded_and_preserve_bytes(monkeypatch):
    attempts, delays = [], []

    def fetch(url, timeout):
        attempts.append((url, timeout))
        if len(attempts) < 3:
            raise urllib.error.HTTPError(url, 500, 'authored server failure', {}, None)
        return io.BytesIO(b'authored tool bytes')

    monkeypatch.setattr(bootstrap.urllib.request, 'urlopen', fetch)
    monkeypatch.setattr(bootstrap.time, 'sleep', delays.append)
    assert bootstrap.download('https://example.invalid/authored') == b'authored tool bytes'
    assert len(attempts) == 3 and delays == [1, 2]


@pytest.mark.parametrize('status,expected_attempts', [(500, 3), (429, 3), (404, 1), (403, 1)])
def test_persistent_or_nontransient_errors_propagate(monkeypatch, status, expected_attempts):
    attempts = []

    def fail(url, timeout):
        attempts.append(url)
        raise urllib.error.HTTPError(url, status, 'authored response', {}, None)

    monkeypatch.setattr(bootstrap.urllib.request, 'urlopen', fail)
    monkeypatch.setattr(bootstrap.time, 'sleep', lambda n: None)
    with pytest.raises(urllib.error.HTTPError) as raised:
        bootstrap.download('https://example.invalid/authored')
    assert raised.value.code == status and len(attempts) == expected_attempts


def test_successful_download_with_wrong_hash_never_installs_or_retries(tmp_path, monkeypatch):
    (tmp_path / '.tools').mkdir()
    monkeypatch.setattr(bootstrap, 'ROOT', tmp_path)
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        return io.BytesIO(b'authored corrupt binary')

    monkeypatch.setattr(bootstrap.urllib.request, 'urlopen', fetch)
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        bootstrap.install('kind', 'https://example.invalid/authored', '0' * 64)
    assert len(calls) == 1 and list((tmp_path / '.tools').iterdir()) == []


def test_missing_platform_checksum_fails_before_any_network_request(tmp_path, monkeypatch):
    (tmp_path / 'infra').mkdir()
    (tmp_path / 'infra/toolchain.json').write_text(json.dumps({'kind_version': 'authored', 'kubectl_version': 'authored'}))
    monkeypatch.setattr(bootstrap, 'ROOT', tmp_path)
    monkeypatch.setattr(bootstrap.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(bootstrap.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(bootstrap.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('unexpected download'))
    with pytest.raises(RuntimeError, match='no pinned sha256'):
        bootstrap.main()
