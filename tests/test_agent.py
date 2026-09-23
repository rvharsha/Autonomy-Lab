"""Deterministic loop/transport doubles, not live-model or AX lifecycle evidence."""

import copy
import json

import pytest

from autonomy_lab import agent
from autonomy_lab.agent import run_agent


def response(*calls, tokens=10, thought_tokens=2, finish_reason="STOP"):
    return {
        "candidates": [{
            "finishReason": finish_reason,
            "content": {"role": "model", "parts": [
                {"functionCall": call, "thoughtSignature": f"unit-signature-{index}"}
                for index, call in enumerate(calls)
            ]},
        }],
        "usageMetadata": {"totalTokenCount": tokens, "thoughtsTokenCount": thought_tokens},
        "modelVersion": "unit-model-version", "responseId": "unit-response-id",
    }


def call(name, args=None, call_id="unit-call"):
    return {"name": name, "args": {} if args is None else args, "id": call_id}


def finish():
    return call("finish", {"outcome": "escalated", "reason": "unit-test terminal claim"})


class StubClient:
    model = "unit-model"

    def __init__(self, *responses, on_request=None, count_results=None, on_count=None):
        self.responses = list(responses)
        self.requests = []
        self.on_request = on_request
        self.count_requests = []
        self.count_results = list(count_results) if count_results is not None else None
        self.on_count = on_count

    def count_tokens(self, contents, system_instruction, declarations):
        self.count_requests.append(copy.deepcopy({"contents": contents, "system_instruction": system_instruction,
                                                  "declarations": declarations}))
        if self.on_count:
            self.on_count()
        result = self.count_results.pop(0) if self.count_results is not None else 1
        if isinstance(result, BaseException):
            raise result
        return result

    def generate(self, contents, system_instruction, declarations, max_output_tokens):
        self.requests.append(copy.deepcopy({"contents": contents, "system_instruction": system_instruction,
                                            "declarations": declarations, "max_output_tokens": max_output_tokens}))
        if self.on_request:
            self.on_request()
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)


class StubToolbox:
    def __init__(self, on_call=None):
        self.calls = []
        self.operations = {}
        self.terminal = None
        self.on_call = on_call

    def declarations(self):
        empty = {"type": "OBJECT", "properties": {}, "additionalProperties": False}
        return [
            {"name": name, "parameters": empty} for name in
            ("observe_service", "probe_backend", "probe_application", "observe_events", "verify_recovery")
        ] + [
            {"name": "propose_repair", "parameters": {"type": "OBJECT", "properties": {
                "operation_id": {"type": "STRING"}, "target_port": {"type": "INTEGER"}},
                "required": ["operation_id", "target_port"], "additionalProperties": False}},
            {"name": "get_operation", "parameters": {"type": "OBJECT", "properties": {
                "operation_id": {"type": "STRING"}}, "required": ["operation_id"]}},
            {"name": "finish", "parameters": {"type": "OBJECT", "properties": {
                "outcome": {"type": "STRING", "enum": ["escalated", "recovered", "healthy"]},
                "reason": {"type": "STRING"}}, "required": ["outcome", "reason"]}},
        ]

    def call(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if self.on_call:
            self.on_call(name, args)
        payload = {"kind": "unit_observation"}
        if name == "get_operation":
            payload = self.operations.get(args["operation_id"], {
                "kind": "error", "error": "operation_not_found", "operation_id": args["operation_id"],
            })
        if name == "propose_repair":
            payload = self.operations.setdefault(args["operation_id"], {
                "operation_id": args["operation_id"], "status": "applied", "request": copy.deepcopy(args),
            })
        if name == "finish":
            self.terminal = {"kind": "claim", **args}
            payload = self.terminal
        return {"observation_id": f"unit-observation-{len(self.calls)}", "run_id": "unit-run",
                "timestamp": "unit-test-time", "source": name, "payload": copy.deepcopy(payload)}


def test_checkpoints_precede_model_and_tool_dispatch_and_preserve_protocol(tmp_path):
    path = tmp_path / "agent.json"

    def model_checkpoint():
        saved = json.loads(path.read_text())
        assert saved["pending_model"] is not None
        assert saved["usage"]["model_calls"] > 0
        assert saved["token_preflights"][-1]["phase"] == "counted"

    def tool_checkpoint(name, args):
        saved = json.loads(path.read_text())
        assert any(item["phase"] == "dispatched" and item["call"]["name"] == name
                   for item in saved["pending_turn"]["calls"])
        assert saved["pending_model"] is None

    first = response(call("observe_service", call_id="first"), call("probe_backend", call_id="second"))
    client = StubClient(first, response(finish()), on_request=model_checkpoint)
    toolbox = StubToolbox(on_call=tool_checkpoint)
    result = run_agent(client, toolbox, path)
    assert result["status"] == "completed"
    assert result["usage"] == {"model_calls": 2, "tool_calls": 3, "total_tokens": 20, "unknown": False}
    assert result["model_responses"][0] == first
    assert result["contents"][1] == first["candidates"][0]["content"]
    function_responses = client.requests[1]["contents"][2]["parts"]
    assert [part["functionResponse"]["id"] for part in function_responses] == ["first", "second"]
    assert [part["functionResponse"]["response"]["source"] for part in function_responses] == ["observe_service", "probe_backend"]
    assert json.loads(path.read_text()) == result


def test_interruption_resumes_remaining_calls_without_repeating_completed_tools(tmp_path):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    first = response(call("observe_service", call_id="a"), call("probe_backend", call_id="b"))
    interrupted = run_agent(StubClient(first), toolbox, path, interrupt_after_tool="observe_service")
    assert interrupted["status"] == "interrupted"
    assert len(toolbox.calls) == 1
    resumed_client = StubClient(response(finish()))
    result = run_agent(resumed_client, toolbox, path)
    assert result["status"] == "completed"
    assert [name for name, _ in toolbox.calls] == ["observe_service", "probe_backend", "finish"]
    assert result["usage"]["model_calls"] == 2
    assert resumed_client.requests[0]["contents"][1] == first["candidates"][0]["content"]


def test_pending_model_call_never_retries_and_does_not_log_exception_secret(tmp_path):
    path = tmp_path / "agent.json"
    result = run_agent(StubClient(TimeoutError("unit-private-key")), StubToolbox(), path)
    assert result["status"] == "indeterminate"
    assert result["error_type"] == "TimeoutError"
    assert result["pending_model"] is not None
    assert result["usage"]["unknown"] is True
    assert "unit-private-key" not in path.read_text()
    resumed = StubClient(response(finish()))
    second = run_agent(resumed, StubToolbox(), path, max_turns=100)
    assert second["status"] == "indeterminate"
    assert resumed.requests == []
    assert second["usage"]["model_calls"] == 1
    assert second["limits"]["max_turns"] == 12


def test_uncertain_repair_uses_existing_broker_result_without_redispatch(tmp_path):
    path = tmp_path / "agent.json"
    proposal = {"operation_id": "unit-operation", "target_port": 8080}
    toolbox = StubToolbox()

    def lost_ack(name, args):
        if name == "propose_repair":
            toolbox.operations[args["operation_id"]] = {"operation_id": args["operation_id"],
                "status": "applied", "request": copy.deepcopy(args)}
            raise TimeoutError("unit-private-key")

    toolbox.on_call = lost_ack
    failed = run_agent(StubClient(response(call("propose_repair", proposal))), toolbox, path)
    assert failed["status"] == "error"
    assert failed["error_type"] == "TimeoutError"
    assert "unit-private-key" not in path.read_text()
    toolbox.on_call = None
    resumed = StubClient(response(finish()))
    result = run_agent(resumed, toolbox, path)
    assert result["status"] == "completed"
    assert [name for name, _ in toolbox.calls] == ["propose_repair", "get_operation", "finish"]
    recovered = resumed.requests[0]["contents"][-1]["parts"][0]["functionResponse"]
    assert recovered["name"] == "propose_repair"
    assert recovered["response"]["source"] == "get_operation"
    assert recovered["response"]["payload"]["status"] == "applied"


def test_missing_broker_operation_reuses_saved_identical_request(tmp_path):
    path = tmp_path / "agent.json"
    proposal = {"operation_id": "unit-operation", "target_port": 8080}
    toolbox = StubToolbox(on_call=lambda name, args: (_ for _ in ()).throw(TimeoutError()) if name == "propose_repair" else None)
    result = run_agent(StubClient(response(call("propose_repair", proposal))), toolbox, path)
    assert result["status"] == "error"
    toolbox.on_call = None
    result = run_agent(StubClient(response(finish())), toolbox, path)
    assert result["status"] == "completed"
    assert [args for name, args in toolbox.calls if name == "propose_repair"] == [proposal, proposal]
    assert [name for name, _ in toolbox.calls] == ["propose_repair", "get_operation", "propose_repair", "finish"]


def test_recovery_lookup_conflict_blocks_proposal(tmp_path):
    path = tmp_path / "agent.json"
    proposal = {"operation_id": "unit-operation", "target_port": 8080}
    toolbox = StubToolbox(on_call=lambda name, args: (_ for _ in ()).throw(TimeoutError()))
    run_agent(StubClient(response(call("propose_repair", proposal))), toolbox, path)
    toolbox.on_call = None
    toolbox.operations["unit-operation"] = {"operation_id": "unit-operation", "status": "applied",
                                           "request": {**proposal, "target_port": 9090}}
    client = StubClient(response(finish()))
    result = run_agent(client, toolbox, path)
    assert result["status"] == "blocked"
    assert result["reason"] == "operation_id_content_conflict"
    assert client.requests == []
    assert len([name for name, _ in toolbox.calls if name == "propose_repair"]) == 1


def test_each_uncertain_repair_recovery_performs_fresh_lookup(tmp_path):
    path = tmp_path / "agent.json"
    proposal = {"operation_id": "unit-operation", "target_port": 8080}
    toolbox = StubToolbox()

    def fail(name, args):
        if name == "propose_repair":
            raise TimeoutError()

    toolbox.on_call = fail
    run_agent(StubClient(response(call("propose_repair", proposal))), toolbox, path)
    run_agent(StubClient(), toolbox, path)
    toolbox.on_call = None
    result = run_agent(StubClient(response(finish())), toolbox, path)
    assert result["status"] == "completed"
    assert [name for name, _ in toolbox.calls].count("get_operation") == 2


def test_cumulative_token_budget_stops_before_tools_and_caps_output_request(tmp_path):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    first = run_agent(StubClient(response(call("observe_service"), tokens=8, thought_tokens=0)), toolbox, path,
                      max_total_tokens=10, interrupt_after_tool=1)
    assert first["status"] == "interrupted"
    second = StubClient(response(call("propose_repair", {"operation_id": "unit-operation", "target_port": 8080}), tokens=3))
    result = run_agent(second, toolbox, path, max_total_tokens=1000)
    assert second.requests[0]["max_output_tokens"] == 1
    assert result["limits"]["max_total_tokens"] == 10
    assert result["usage"]["total_tokens"] == 11
    assert result["status"] == "budget_exhausted"
    assert [name for name, _ in toolbox.calls] == ["observe_service"]


def test_cumulative_model_call_budget_survives_resume(tmp_path):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    run_agent(StubClient(response(call("observe_service"))), toolbox, path, max_turns=1, interrupt_after_tool=1)
    client = StubClient(response(finish()))
    result = run_agent(client, toolbox, path, max_turns=100)
    assert result["reason"] == "model_call_budget_exhausted"
    assert client.requests == []


@pytest.mark.parametrize("bad_call", [
    {"name": "propose_repair", "args": "bad"},
    call("propose_repair", {"target_port": 8080}),
    call("propose_repair", {"operation_id": "unit-op", "target_port": "8080"}),
    call("unapproved_shell", {"command": "echo hello"}),
    call("observe_service", {"unknown": True}),
])
def test_malformed_calls_never_dispatch_any_tool_in_turn(tmp_path, bad_call):
    toolbox = StubToolbox()
    result = run_agent(StubClient(response(call("observe_service"), bad_call)), toolbox, tmp_path / "agent.json")
    assert result["status"] == "blocked"
    assert toolbox.calls == []


def test_unknown_usage_and_incomplete_generation_do_not_execute_tools(tmp_path):
    for index, data in enumerate([response(finish(), finish_reason="MAX_TOKENS"), {**response(finish()), "usageMetadata": {}}]):
        toolbox = StubToolbox()
        result = run_agent(StubClient(data), toolbox, tmp_path / f"agent-{index}.json")
        assert result["status"] == "blocked"
        assert toolbox.calls == []
        assert result["model_responses"] == [data]


def test_provider_exception_response_retains_usage(tmp_path):
    error = RuntimeError("unit-private-key")
    error.response = response(finish(), tokens=25, finish_reason="MAX_TOKENS")
    result = run_agent(StubClient(error), StubToolbox(), tmp_path / "agent.json")
    assert result["status"] == "blocked"
    assert result["usage"]["total_tokens"] == 25
    assert result["model_responses"] == [error.response]


def test_provider_status_code_is_retained_without_exception_text(tmp_path):
    error = RuntimeError("unit-private-key")
    error.status_code = 401
    path = tmp_path / "agent.json"
    result = run_agent(StubClient(error), StubToolbox(), path)
    assert result["error_type"] == "RuntimeError"
    assert result["provider_status_code"] == 401
    assert "unit-private-key" not in path.read_text()


def test_structured_memory_changes_resume_instruction_and_retains_history(tmp_path):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    incident = {"hypotheses": ["Need fresh backend evidence."], "evidence_ids": ["unit-observation-1"],
                "unresolved_operations": [], "next_step": "Probe the backend before deciding."}
    first_response = response(call("observe_service"))
    client = StubClient(first_response, response(call("record_incident", incident)))
    interrupted = run_agent(client, toolbox, path, variant="structured", interrupt_after_tool="record_incident")
    assert interrupted["status"] == "interrupted"
    assert interrupted["incident"] == incident
    resumed = StubClient(response(finish()))
    result = run_agent(resumed, toolbox, path, variant="structured")
    assert result["status"] == "completed"
    assert incident["next_step"] in resumed.requests[0]["system_instruction"]
    assert resumed.requests[0]["contents"][1] == first_response["candidates"][0]["content"]
    assert "record_incident" in [item["name"] for item in resumed.requests[0]["declarations"]]
    assert [name for name, _ in toolbox.calls] == ["observe_service", "finish"]
    assert result["usage"]["tool_calls"] == 3


def test_basic_variant_cannot_record_incident(tmp_path):
    toolbox = StubToolbox()
    result = run_agent(StubClient(response(call("record_incident", {}))), toolbox, tmp_path / "agent.json")
    assert result["status"] == "blocked"
    assert toolbox.calls == []


@pytest.mark.parametrize("invalid_fields", [
    {"evidence_ids": ["never-observed"]},
    {"hypotheses": ["x" * 501]},
    {"unresolved_operations": [""]},
    {"unexpected": "untrusted validation detail"},
])
def test_rejected_incident_is_a_durable_tool_result_not_repeated_on_resume(tmp_path, invalid_fields):
    path = tmp_path / "agent.json"
    incident = {"hypotheses": [], "evidence_ids": [], "unresolved_operations": [], "next_step": "Gather evidence."}
    toolbox = StubToolbox()
    first = run_agent(StubClient(response(call("record_incident", {**incident, **invalid_fields}))), toolbox, path,
                      variant="structured", interrupt_after_tool="record_incident")
    assert first["status"] == "interrupted"
    assert first["incident"]["next_step"] == "Gather initial observations."
    rejected = {"kind": "incident_rejected", "reason": "invalid_incident_state"}
    assert first["tool_records"][0]["result"] == rejected
    assert first["pending_turn"]["calls"][0]["phase"] == "completed"
    client = StubClient(response(call("record_incident", incident)), response(finish()))
    result = run_agent(client, toolbox, path, variant="structured")
    assert result["status"] == "completed"
    assert result["incident"] == incident
    assert result["usage"]["tool_calls"] == 3
    assert [r["result"]["kind"] for r in result["tool_records"][:2]] == ["incident_rejected", "incident_recorded"]
    assert client.requests[0]["contents"][-1]["parts"][0]["functionResponse"]["response"] == rejected


def test_corrupt_checkpoint_is_preserved_and_never_starts_fresh_budget(tmp_path):
    path = tmp_path / "agent.json"
    path.write_text("{truncated-existing-checkpoint")
    client = StubClient(response(finish()))
    result = run_agent(client, StubToolbox(), path)
    assert result["status"] == "blocked"
    assert client.requests == []
    assert path.read_text() == "{truncated-existing-checkpoint"
    assert json.loads((tmp_path / "agent.json.error.json").read_text())["reason"] == "unreadable_existing_checkpoint"


@pytest.mark.parametrize("variant", ["basic", "structured"])
@pytest.mark.parametrize("interrupt_hook", [None, "observe_servce"])
def test_completed_agent_is_not_rewritten_or_rerun(tmp_path, variant, interrupt_hook):
    path = tmp_path / "agent.json"
    result = run_agent(StubClient(response(finish())), StubToolbox(), path, variant=variant)
    assert result["status"] == "completed"
    before, modified_at = path.read_bytes(), path.stat().st_mtime_ns
    second, toolbox = StubClient(response(finish())), StubToolbox()
    replay = run_agent(second, toolbox, path, variant=variant, interrupt_after_tool=interrupt_hook)
    assert replay == result
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_at
    assert second.count_requests == second.requests == toolbox.calls == []


@pytest.mark.parametrize("variant, model", [("structured", "unit-model"), ("basic", "changed-model")])
@pytest.mark.parametrize("completed", [False, True])
def test_configuration_mismatch_blocks_without_rewriting_checkpoint(tmp_path, variant, model, completed):
    path = tmp_path / "agent.json"
    first_call = finish() if completed else call("observe_service")
    run_agent(StubClient(response(first_call)), StubToolbox(), path,
              interrupt_after_tool=None if completed else "observe_service")
    before, modified_at = path.read_bytes(), path.stat().st_mtime_ns
    client, toolbox = StubClient(response(finish())), StubToolbox()
    client.model = model
    result = run_agent(client, toolbox, path, variant=variant, interrupt_after_tool="observe_servce")
    assert result["status"] == "blocked"
    assert result["reason"] == "checkpoint_configuration_changed"
    assert client.count_requests == client.requests == toolbox.calls == []
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_at
    assert json.loads(path.with_suffix(".json.error.json").read_text()) == result


@pytest.mark.parametrize("missing, replacements", [
    ("variant", {}), ("status", {}), ("pending_turn", {"status": "error"}),
    ("pending_model", {}), ("limits", {}), ("resume_count", {}),
    ("usage", {}), ("contents", {}), ("model_requests", {}),
    (None, {"limits": None}),
    (None, {"limits": {"max_turns": "unit-private-key"}}),
    (None, {"resume_count": None}),
    (None, {"usage": None}),
])
def test_malformed_resume_checkpoint_is_preserved_before_execution(tmp_path, missing, replacements):
    path = tmp_path / "agent.json"
    run_agent(StubClient(response(call("observe_service"))), StubToolbox(), path, interrupt_after_tool=1)
    saved = json.loads(path.read_text())
    if missing is not None:
        del saved[missing]
    saved.update(replacements)
    path.write_text(json.dumps(saved))
    before, modified_at = path.read_bytes(), path.stat().st_mtime_ns
    client, toolbox = StubClient(response(finish())), StubToolbox()
    result = run_agent(client, toolbox, path)
    assert result["status"] == "blocked"
    assert result["reason"] == "invalid_existing_checkpoint"
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_at
    assert client.count_requests == client.requests == toolbox.calls == []
    sidecar = path.with_suffix(".json.error.json")
    assert json.loads(sidecar.read_text()) == result
    assert "unit-private-key" not in sidecar.read_text()


@pytest.mark.parametrize("failure", ["unreadable", "invalid", "configuration"])
def test_failure_to_write_checkpoint_error_sidecar_preserves_primary(tmp_path, monkeypatch, failure):
    path = tmp_path / "agent.json"
    run_agent(StubClient(response(finish())), StubToolbox(), path)
    if failure == "unreadable":
        path.write_text("{truncated")
    elif failure == "invalid":
        path.write_text('{"schema_version": 1, "variant": "basic", "model": "unit-model", "status": "error"}')
    before, modified_at = path.read_bytes(), path.stat().st_mtime_ns
    original_save = agent._save
    attempted_paths = []

    def fail_sidecar(target, state):
        attempted_paths.append(target)
        if target == path.with_suffix(".json.error.json"):
            raise OSError("unit-private-key")
        return original_save(target, state)

    monkeypatch.setattr(agent, "_save", fail_sidecar)
    client, toolbox = StubClient(response(finish())), StubToolbox()
    result = run_agent(client, toolbox, path, variant="structured" if failure == "configuration" else "basic")
    assert result["status"] == "blocked"
    assert result["persistence_error"] is True
    assert "unit-private-key" not in json.dumps(result)
    assert attempted_paths == [path.with_suffix(".json.error.json")]
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_at
    assert client.count_requests == client.requests == toolbox.calls == []


def test_process_abort_leaves_pending_model_request_and_resume_does_not_retry(tmp_path):
    class SimulatedProcessAbort(BaseException):
        pass

    path = tmp_path / "agent.json"
    with pytest.raises(SimulatedProcessAbort):
        run_agent(StubClient(SimulatedProcessAbort()), StubToolbox(), path)
    assert json.loads(path.read_text())["pending_model"] is not None
    client = StubClient(response(finish()))
    resumed = run_agent(client, StubToolbox(), path)
    assert resumed["status"] == "indeterminate"
    assert client.requests == []


@pytest.mark.parametrize("after_commit", [False, True])
def test_model_response_and_tool_intent_share_one_checkpoint(tmp_path, monkeypatch, after_commit):
    class SimulatedProcessAbort(BaseException):
        pass

    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    proposal = {"operation_id": "unit-stable-operation", "target_port": 8080}
    model_response = response(call("propose_repair", proposal))
    original_save = agent._save

    def abort_first_response_checkpoint(path, state):
        if state["model_responses"]:
            assert state["pending_turn"]["calls"][0]["call"]["args"] == proposal
            assert state["pending_turn"]["calls"][0]["phase"] == "queued"
            assert state["contents"][-1] == model_response["candidates"][0]["content"]
            if after_commit:
                original_save(path, state)
            raise SimulatedProcessAbort()
        original_save(path, state)

    monkeypatch.setattr(agent, "_save", abort_first_response_checkpoint)
    with pytest.raises(SimulatedProcessAbort):
        run_agent(StubClient(model_response), toolbox, path)
    checkpoint = json.loads(path.read_text())
    assert toolbox.calls == []
    monkeypatch.setattr(agent, "_save", original_save)
    client = StubClient(response(finish()))
    result = run_agent(client, toolbox, path)
    if after_commit:
        assert checkpoint["model_responses"] == [model_response]
        assert checkpoint["usage"]["total_tokens"] == 10
        assert result["status"] == "completed"
        assert toolbox.calls == [("propose_repair", proposal), ("finish", finish()["args"])]
        assert len(client.requests) == 1
    else:
        assert checkpoint["pending_model"] is not None
        assert checkpoint["model_responses"] == []
        assert result["reason"] == "pending_model_request_no_automatic_retry"
        assert client.requests == client.count_requests == toolbox.calls == []


@pytest.mark.parametrize("history_saved", [False, True])
def test_legacy_unqueued_response_blocks_new_generation(tmp_path, history_saved):
    path = tmp_path / "agent.json"
    run_agent(StubClient(response(call("observe_service"))), StubToolbox(), path, interrupt_after_tool=1)
    checkpoint = json.loads(path.read_text())
    checkpoint.update(status="running", pending_turn=None)
    if not history_saved:
        checkpoint["contents"].pop()
    path.write_text(json.dumps(checkpoint))
    client = StubClient(response(finish()))
    result = run_agent(client, StubToolbox(), path)
    assert result["reason"] == "unqueued_model_turn"
    assert client.requests == client.count_requests == []


def test_failed_predispatch_checkpoint_prevents_tool_execution(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    original_save = agent._save

    def unavailable(path, state):
        if state["pending_turn"] and any(item["phase"] == "dispatched" for item in state["pending_turn"]["calls"]):
            raise OSError("unit-private-filesystem-detail")
        original_save(path, state)

    monkeypatch.setattr(agent, "_save", unavailable)
    toolbox = StubToolbox()
    result = run_agent(StubClient(response(call("observe_service"))), toolbox, path)
    assert result["status"] == "error"
    assert result["persistence_error"] is True
    assert toolbox.calls == []
    assert "unit-private-filesystem-detail" not in path.read_text()
    assert json.loads(path.read_text())["pending_turn"]["calls"][0]["phase"] == "queued"


def test_lowered_resume_budget_prevents_queued_tool_dispatch(tmp_path):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    run_agent(StubClient(response(call("observe_service", call_id="first"), call("probe_backend", call_id="second"), tokens=20)),
              toolbox, path, interrupt_after_tool="observe_service")
    result = run_agent(StubClient(), toolbox, path, max_total_tokens=10)
    assert result["status"] == "budget_exhausted"
    assert [name for name, _ in toolbox.calls] == ["observe_service"]


@pytest.mark.parametrize("input_tokens", [32000, 39430])
def test_counted_input_exhaustion_prevents_billable_generation(tmp_path, input_tokens):
    path = tmp_path / "agent.json"
    client = StubClient(response(finish()), count_results=[input_tokens])
    toolbox = StubToolbox()
    result = run_agent(client, toolbox, path, max_total_tokens=32000)
    assert result["status"] == "budget_exhausted"
    assert result["reason"] == "input_and_output_token_budget_exhausted"
    assert result["usage"]["model_calls"] == 0
    assert result["usage"]["total_tokens"] == 0
    assert result["pending_model"] is None
    assert client.requests == []
    assert toolbox.calls == []
    assert result["token_preflights"][0]["counted_input_tokens"] == input_tokens
    assert result["token_preflights"][0]["reserved_output_tokens"] == 0
    assert json.loads(path.read_text()) == result


def test_input_reservation_uses_remaining_cumulative_budget_and_identical_input(tmp_path):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    first = StubClient(response(call("observe_service"), tokens=70), count_results=[50])
    run_agent(first, toolbox, path, max_total_tokens=100, interrupt_after_tool="observe_service")
    second = StubClient(response(finish(), tokens=30), count_results=[23])
    result = run_agent(second, toolbox, path, max_total_tokens=100)
    assert result["status"] == "completed"
    assert second.requests[0]["max_output_tokens"] == 5
    assert second.count_requests[0] == {key: value for key, value in second.requests[0].items() if key != "max_output_tokens"}
    assert result["usage"]["total_tokens"] == 100
    preflight = result["token_preflights"][-1]
    assert preflight["counted_input_tokens"] == 23
    assert preflight["remaining_total_tokens"] == 30
    assert preflight["preserved_thought_tokens"] == 2
    assert preflight["reserved_input_tokens"] == 25
    assert preflight["reserved_output_tokens"] == 5
    assert preflight["elapsed_seconds"] >= 0
    assert result["model_requests"][-1]["reserved_tokens"] == 30


@pytest.mark.parametrize("variant", ["basic", "structured"])
def test_prior_thinking_reservation_matches_observed_usage_pattern_across_resume(tmp_path, variant):
    # Deterministic regression inputs follow the observed live count/usage gap;
    # these doubles test budgeting and are not another live-model result.
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    first_response = response(call("observe_service"), tokens=2200, thought_tokens=111)
    first_response["usageMetadata"].update(promptTokenCount=2000, candidatesTokenCount=89)
    second_response = response(call("probe_backend"), tokens=4500, thought_tokens=778)
    second_response["usageMetadata"].update(promptTokenCount=3612, candidatesTokenCount=110)
    first = StubClient(first_response, second_response, count_results=[2000, 3501])
    interrupted = run_agent(first, toolbox, path, variant=variant, max_total_tokens=12000,
                            interrupt_after_tool="probe_backend")
    assert interrupted["token_preflights"][1]["reserved_input_tokens"] == 3612
    final_response = response(finish(), tokens=5300, thought_tokens=20)
    final_response["usageMetadata"].update(promptTokenCount=5270, candidatesTokenCount=10)
    second = StubClient(final_response, count_results=[4381])
    result = run_agent(second, toolbox, path, variant=variant, max_total_tokens=12000)
    preflight = result["token_preflights"][-1]
    assert result["status"] == "completed"
    assert result["usage"]["total_tokens"] == 12000
    assert preflight["counted_input_tokens"] == 4381
    assert preflight["preserved_thought_tokens"] == 889
    assert preflight["reserved_input_tokens"] == 5270
    assert preflight["prior_response_count"] == 2
    assert preflight["reserved_output_tokens"] == 30
    assert preflight["input_reservation_source"] == "countTokens.totalTokens_plus_prior_thought_usage"
    assert second.requests[0]["max_output_tokens"] == 30
    assert result["model_requests"][-1]["reserved_tokens"] == 5300
    preserved = [c for c in second.requests[0]["contents"] if c["role"] == "model"]
    assert preserved == [r["candidates"][0]["content"] for r in (first_response, second_response)]
    assert result["model_responses"] == [first_response, second_response, final_response]


@pytest.mark.parametrize("remaining", [29, 30, 31])
def test_preserved_thoughts_can_exhaust_or_leave_one_output_token(tmp_path, remaining):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    limit = 100 + remaining
    run_agent(StubClient(response(call("observe_service"), tokens=100, thought_tokens=20), count_results=[60]),
              toolbox, path, max_total_tokens=limit, interrupt_after_tool=1)
    client = StubClient(response(finish(), tokens=31, thought_tokens=0), count_results=[10])
    result = run_agent(client, toolbox, path, max_total_tokens=limit)
    assert result["token_preflights"][-1]["reserved_input_tokens"] == 30
    if remaining == 31:
        assert result["status"] == "completed"
        assert client.requests[0]["max_output_tokens"] == 1
        assert result["usage"]["total_tokens"] == limit
    else:
        assert result["reason"] == "input_and_output_token_budget_exhausted"
        assert result["usage"]["model_calls"] == 1
        assert result["usage"]["total_tokens"] == 100
        assert client.requests == []
        assert [name for name, _ in toolbox.calls] == ["observe_service"]


@pytest.mark.parametrize("metadata", [
    None, {}, {"totalTokenCount": 70},
    *({"totalTokenCount": 70, "thoughtsTokenCount": value} for value in (None, -1, True, "2", 1.5, 71)),
    {"totalTokenCount": "70", "thoughtsTokenCount": 2},
    {"totalTokenCount": 69, "thoughtsTokenCount": 2},
    {"totalTokenCount": 70, "promptTokenCount": 71, "candidatesTokenCount": 0},
    {"totalTokenCount": 70, "promptTokenCount": 50},
    {"totalTokenCount": 70, "promptTokenCount": True, "candidatesTokenCount": 1},
    {"totalTokenCount": 70, "promptTokenCount": 50, "candidatesTokenCount": "20"},
    {"totalTokenCount": 70, "promptTokenCount": -1, "candidatesTokenCount": 20},
    {"totalTokenCount": 70, "promptTokenCount": 50, "candidatesTokenCount": 20, "thoughtsTokenCount": None},
    *({"totalTokenCount": 70, "promptTokenCount": 50, "candidatesTokenCount": 20, "toolUsePromptTokenCount": value}
      for value in (None, -1, True, False, "0", 0.0, 1, 1.5)),
])
def test_unknown_or_invalid_prior_usage_prevents_counting_and_generation(tmp_path, metadata):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    run_agent(StubClient(response(call("observe_service"), tokens=70)), toolbox, path, interrupt_after_tool=1)
    checkpoint = json.loads(path.read_text())
    checkpoint["model_responses"][0]["usageMetadata"] = metadata
    path.write_text(json.dumps(checkpoint))
    client = StubClient(response(finish()))
    result = run_agent(client, toolbox, path)
    assert result["reason"] == "token_preflight_failed"
    assert result["token_preflights"][-1]["failure_stage"] == "prior_usage"
    assert result["usage"]["total_tokens"] == 70
    assert client.requests == client.count_requests == []
    assert [name for name, _ in toolbox.calls] == ["observe_service"]


@pytest.mark.parametrize("thoughts", [0, 20])
@pytest.mark.parametrize("tool_usage", [{}, {"toolUsePromptTokenCount": 0}])
def test_missing_thought_count_is_derived_only_from_complete_usage(tmp_path, thoughts, tool_usage):
    path = tmp_path / "agent.json"
    toolbox = StubToolbox()
    first_response = response(call("observe_service"), tokens=70)
    first_response["usageMetadata"] = {"totalTokenCount": 70, "promptTokenCount": 60 - thoughts, "candidatesTokenCount": 10}
    first_response["usageMetadata"].update(tool_usage)
    run_agent(StubClient(first_response), toolbox, path, max_total_tokens=200, interrupt_after_tool=1)
    client = StubClient(response(finish(), tokens=50), count_results=[23])
    result = run_agent(client, toolbox, path, max_total_tokens=200)
    assert result["status"] == "completed"
    preflight = result["token_preflights"][-1]
    assert preflight["preserved_thought_tokens"] == thoughts
    assert preflight["reserved_input_tokens"] == 23 + thoughts
    assert client.requests[0]["max_output_tokens"] == 107 - thoughts
    assert preflight["prior_thought_usage"] == [{
        "response_index": 0, "tokens": thoughts,
        "source": "usageMetadata.totalTokenCount_minus_promptTokenCount_minus_candidatesTokenCount",
    }]
    assert result["model_responses"][0] == first_response


@pytest.mark.parametrize("variant, tool_name", [
    ("basic", "observe_servce"), ("structured", "observe_servce"),
    ("basic", "record_incident"), ("structured", ""),
])
def test_invalid_interrupt_name_blocks_before_any_provider_or_tool_call(tmp_path, variant, tool_name):
    client, toolbox = StubClient(response(finish())), StubToolbox()
    result = run_agent(client, toolbox, tmp_path / "agent.json", variant=variant, interrupt_after_tool=tool_name)
    assert result["reason"] == "invalid_interrupt_tool"
    assert client.count_requests == client.requests == toolbox.calls == []


def test_interrupt_name_must_be_in_actual_toolbox_declarations(tmp_path):
    client, toolbox = StubClient(response(finish())), StubToolbox()
    declared = toolbox.declarations()
    toolbox.declarations = lambda: [item for item in declared if item["name"] != "finish"]
    result = run_agent(client, toolbox, tmp_path / "agent.json", interrupt_after_tool="finish")
    assert result["reason"] == "invalid_interrupt_tool"
    assert client.count_requests == client.requests == toolbox.calls == []


def test_count_failure_is_durable_and_never_falls_back_to_estimate(tmp_path):
    path = tmp_path / "agent.json"

    def assert_pending_count():
        checkpoint = json.loads(path.read_text())
        assert checkpoint["token_preflights"][-1]["phase"] == "pending"
        assert checkpoint["pending_model"] is None

    error = TimeoutError("unit-private-key")
    client = StubClient(response(finish()), count_results=[error], on_count=assert_pending_count)
    result = run_agent(client, StubToolbox(), path)
    assert result["status"] == "blocked"
    assert result["reason"] == "token_preflight_failed"
    assert result["token_preflights"][-1]["phase"] == "failed"
    assert result["error_type"] == "TimeoutError"
    assert result["usage"]["model_calls"] == 0
    assert result["usage"]["unknown"] is False
    assert client.requests == []
    assert "unit-private-key" not in path.read_text()
    second = StubClient(response(finish()))
    run_agent(second, StubToolbox(), path)
    assert second.count_requests == []
    assert second.requests == []


@pytest.mark.parametrize("count", [None, -1, True, 1.5, "12"])
def test_invalid_count_never_permits_generation(tmp_path, count):
    client = StubClient(response(finish()), count_results=[count])
    result = run_agent(client, StubToolbox(), tmp_path / "agent.json")
    assert result["reason"] == "token_preflight_failed"
    assert client.requests == []


def test_client_without_live_counter_cannot_generate(tmp_path):
    client = StubClient(response(finish()))
    client.count_tokens = None
    result = run_agent(client, StubToolbox(), tmp_path / "agent.json")
    assert result["reason"] == "token_preflight_failed"
    assert client.requests == []


def test_aborted_token_count_does_not_trigger_generation_on_resume(tmp_path):
    class SimulatedProcessAbort(BaseException):
        pass

    path = tmp_path / "agent.json"
    with pytest.raises(SimulatedProcessAbort):
        run_agent(StubClient(count_results=[SimulatedProcessAbort()]), StubToolbox(), path)
    client = StubClient(response(finish()))
    result = run_agent(client, StubToolbox(), path)
    assert result["reason"] == "pending_token_preflight_no_automatic_retry"
    assert result["usage"]["model_calls"] == 0
    assert client.requests == []
    assert client.count_requests == []
