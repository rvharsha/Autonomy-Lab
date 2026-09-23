"""Boundary/accounting unit cases; live enforcement has a separate Docker probe."""

import io

import pytest

from autonomy_lab.isolated_runtime import ModelRelay, clean_environment
from autonomy_lab.rpc import MAX_FRAME_BYTES, read_frame, write_frame


class CountedClient:
    def __init__(self):
        self.calls = 0

    def count_tokens(self, **kwargs):
        return 5

    def generate(self, **kwargs):
        self.calls += 1
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": "authored"}]}}],
                "usageMetadata": {"totalTokenCount": 8, "promptTokenCount": 5, "candidatesTokenCount": 2, "thoughtsTokenCount": 1}}


INPUT = {"contents": [{"role": "user", "parts": [{"text": "authored"}]}], "system_instruction": "", "declarations": []}
OPTIONS = {"max_turns": 1, "max_total_tokens": 10, "max_output_tokens": 5}


def test_host_ledger_survives_agent_reset_and_prevents_extra_generation(tmp_path):
    client = CountedClient()
    path = tmp_path / "ledger.json"
    relay = ModelRelay(client, path, OPTIONS)
    relay.call("count_tokens", INPUT)
    relay.call("generate", {**INPUT, "max_output_tokens": 5})
    restarted = ModelRelay(client, path, OPTIONS)
    restarted.call("count_tokens", INPUT)
    with pytest.raises(ValueError, match="budget"):
        restarted.call("generate", {**INPUT, "max_output_tokens": 1})
    assert client.calls == 1


def test_unknown_model_request_is_never_retried(tmp_path):
    class Broken(CountedClient):
        def generate(self, **kwargs):
            self.calls += 1
            raise TimeoutError()
    client = Broken()
    path = tmp_path / "ledger.json"
    relay = ModelRelay(client, path, OPTIONS)
    relay.call("count_tokens", INPUT)
    with pytest.raises(TimeoutError):
        relay.call("generate", {**INPUT, "max_output_tokens": 5})
    with pytest.raises(ValueError, match="Uncertain"):
        ModelRelay(client, path, OPTIONS).call("count_tokens", INPUT)
    assert client.calls == 1


def test_changed_generation_input_is_rejected(tmp_path):
    client = CountedClient()
    relay = ModelRelay(client, tmp_path / "ledger.json", OPTIONS)
    relay.call("count_tokens", INPUT)
    with pytest.raises(ValueError, match="changed"):
        relay.call("generate", {**INPUT, "system_instruction": "different", "max_output_tokens": 1})
    assert client.calls == 0


def test_authorities_do_not_inherit_provider_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-only-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-only-secret")
    monkeypatch.setenv("KUBECONFIG", "/private/controller/config")
    assert not {"GEMINI_API_KEY", "ANTHROPIC_API_KEY", "KUBECONFIG"} & clean_environment().keys()


def test_rpc_rejects_partial_oversized_and_nonobject_frames():
    for data in [b"{}", b"[]\n", b"x" * (MAX_FRAME_BYTES + 1)]:
        with pytest.raises(ValueError):
            read_frame(io.BytesIO(data))
    output = io.BytesIO()
    write_frame(output, {"id": 1, "result": "complete"})
    output.seek(0)
    assert read_frame(output) == {"id": 1, "result": "complete"}


def test_partial_pipe_frame_cannot_bypass_deadline():
    import os
    import time

    from autonomy_lab.rpc import PipeReader
    read, write = os.pipe()
    try:
        os.write(write, b'{')
        with os.fdopen(read, 'rb') as stream:
            with pytest.raises(TimeoutError):
                PipeReader(stream).read(time.monotonic() + .03)
    finally:
        os.close(write)


def test_pipe_reader_retains_two_frames_from_one_write():
    import os
    import time

    from autonomy_lab.rpc import PipeReader
    read, write = os.pipe()
    try:
        os.write(write, b'{"id":1}\n{"id":2}\n')
        with os.fdopen(read, 'rb') as stream:
            reader = PipeReader(stream)
            assert reader.read(time.monotonic() + 1) == {'id': 1}
            assert reader.read(time.monotonic() + 1) == {'id': 2}
    finally:
        os.close(write)


def test_backpressured_write_has_deadline():
    import os
    import time

    from autonomy_lab.rpc import PipeWriter
    read, write = os.pipe()
    try:
        with os.fdopen(write, 'wb') as stream:
            with pytest.raises(TimeoutError):
                PipeWriter(stream).write({'payload': 'x' * 1000000}, time.monotonic() + .03)
    finally:
        os.close(read)


def test_rpc_budget_survives_new_process_and_cannot_increase(tmp_path):
    from autonomy_lab.isolated_runtime import charge_rpc
    path = tmp_path / 'rpc.json'
    charge_rpc(path, 2)
    charge_rpc(path, 100)
    with pytest.raises(ValueError, match='budget'):
        charge_rpc(path, 100)


def test_real_authority_process_distinguishes_journal_miss_from_malformed_request(tmp_path):
    from autonomy_lab.isolated_runtime import AuthorityProcess
    from autonomy_lab.rpc import RemoteError
    config = {'role': 'broker', 'kubeconfig': str(tmp_path / 'unused'), 'cluster_name': 'autolab-12345678',
              'namespace': 'autonomy-lab', 'journal': str(tmp_path / 'journal.sqlite'),
              'policy': {'run_id': 'unit', 'namespace': 'autonomy-lab', 'service_name': 'inventory',
                         'service_uid': 'unit', 'max_dispatches': 1}, 'withhold_ack': False}
    with AuthorityProcess(config, tmp_path / 'worker.log') as authority:
        with pytest.raises(KeyError):
            authority.lookup('missing')
        with pytest.raises(RemoteError, match='KeyError'):
            authority.propose({})
        with pytest.raises(KeyError):
            authority.lookup('still-missing')
