"""Authored protocol cases, not live model outcomes."""

import copy
import json

import pytest

from autonomy_lab.context import request_context


def transcript():
    state = {"contents": [{"role": "user", "parts": [{"text": "incident"}]}],
             "model_responses": [], "tool_records": []}
    for i in range(5):
        model = {"role": "model", "parts": [{"functionCall": {"name": "get_operation", "args": {"operation_id": "pending"}},
                                            "thoughtSignature": f"authored-signature-{i}"}]}
        response = {"source": "get_operation", "observation_id": f"observation-{i}",
                    "payload": {"status": "uncertain", "operation_id": "pending"}}
        state["contents"].extend([model, {"role": "user", "parts": [{"functionResponse": {"name": "get_operation", "response": response}}]}])
        state["model_responses"].append({"candidates": [{"content": model}]})
        state["tool_records"].append({"name": "get_operation", "args": {"operation_id": "pending"}, "result": response})
    return state


def test_compaction_preserves_whole_signed_exchanges_and_all_public_evidence():
    state = transcript()
    original = copy.deepcopy(state)
    context, indices = request_context(state, "recent-exchanges")
    assert indices == [3, 4]
    assert context[1:] == state["contents"][-4:]
    for i in range(3):
        assert f'observation-{i}' in context[0]["parts"][-1]["text"]
    assert 'observation-3' not in context[0]["parts"][-1]["text"]
    for i in range(5):
        assert f'observation-{i}' in json.dumps(context)
    assert 'pending' in context[0]["parts"][-1]["text"]
    assert context[0]["parts"][0] == state["contents"][0]["parts"][0]
    assert state == original
    assert request_context(state, "full") == (state["contents"], list(range(5)))


def test_incomplete_exchange_cannot_be_compacted():
    state = transcript()
    state["contents"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        request_context(state, "recent-exchanges")


def test_modified_signature_is_rejected_before_compaction():
    state = copy.deepcopy(transcript())
    state["contents"][1] = copy.deepcopy(state["contents"][1])
    state["contents"][1]["parts"][0]["thoughtSignature"] = "changed"
    with pytest.raises(ValueError, match="differs"):
        request_context(state, "recent-exchanges")


def test_ledger_is_derived_from_verified_transcript_despite_record_drift():
    state = transcript()
    expected = request_context(state, "recent-exchanges")
    state["tool_records"] = [{"result": "tampered"}]
    assert request_context(state, "recent-exchanges") == expected
