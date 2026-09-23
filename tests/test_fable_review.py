"""Review-boundary tests; no model calls or actual credentials are used here."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "fable_review", Path(__file__).resolve().parents[1] / "scripts/fable_review.py"
)
review = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review)


def put(root, relative, contents):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def test_snapshot_only_includes_scoped_public_source(tmp_path):
    put(tmp_path, "src/autonomy_lab/broker.py", "value = 1\nprint(value)\n")
    put(tmp_path, "tests/test_broker.py", "def test_guard():\n    assert True\n")
    for path in (
        ".env",
        ".state/private.py",
        ".tools/secret.py",
        "artifacts/result.json",
        "tests/.private.py",
        "tests/.env",
        "src/autonomy_lab/.credentials.py",
        "private.py",
        "fixtures/private.json",
        "infra/private.yaml",
        "PLAN.md",
        "src/autonomy_lab/agent.py",
    ):
        put(tmp_path, path, "DO_NOT_TRANSMIT_PRIVATE_OR_UNSCOPED_CONTENT")
    result = review.build_snapshot(tmp_path)
    assert {item["path"] for item in result["files"]} == {
        "src/autonomy_lab/broker.py",
        "tests/test_broker.py",
    }
    assert "    2: print(value)" in result["prompt"]
    assert "DO_NOT_TRANSMIT_PRIVATE_OR_UNSCOPED_CONTENT" not in result["prompt"]
    assert "TEST INDEX ONLY tests/test_broker.py" in result["prompt"]
    assert "test_guard" in result["prompt"]
    assert "assert True" not in result["prompt"]


def test_agents_scope_has_distinct_explicit_file_set(tmp_path):
    put(tmp_path, "src/autonomy_lab/agent.py", "AGENT_SOURCE")
    put(tmp_path, "src/autonomy_lab/broker.py", "BROKER_SOURCE")
    assert "AGENT_SOURCE" in review.build_snapshot(tmp_path, "agents")["prompt"]
    assert "BROKER_SOURCE" not in review.build_snapshot(tmp_path, "agents")["prompt"]
    assert "BROKER_SOURCE" in review.build_snapshot(tmp_path, "all")["prompt"]


def test_broker_scope_is_single_module_plus_test_index(tmp_path):
    put(tmp_path, "src/autonomy_lab/broker.py", "BROKER_SOURCE")
    put(tmp_path, "tests/test_broker.py", "def test_guard(): pass\n")
    put(tmp_path, "src/autonomy_lab/harness.py", "OMITTED_RUNTIME")
    put(tmp_path, "pyproject.toml", "OMITTED_CONFIG")
    snapshot = review.build_snapshot(tmp_path, "broker")
    assert {item["path"] for item in snapshot["files"]} == {
        "src/autonomy_lab/broker.py",
        "tests/test_broker.py",
    }
    assert "BROKER_SOURCE" in snapshot["prompt"]
    assert "OMITTED" not in snapshot["prompt"]
    with pytest.raises(review.ReviewError, match="Unknown review scope"):
        review.build_snapshot(tmp_path, "../../.env")


def test_broker_profile_enforces_smaller_input_and_low_effort():
    payload = review.request_payload({"scope": "broker", "prompt": "source snapshot"})
    assert payload["output_config"] == {"effort": "low"}
    assert payload["max_tokens"] == 12_000
    assert "at most two" in payload["system"]
    bound = review.cost_gate(14_999, "broker")
    assert bound["estimated_maximum_usd"] < 0.8
    assert bound["max_output_tokens"] == payload["max_tokens"]
    with pytest.raises(review.ReviewError):
        review.cost_gate(15_000, "broker")


@pytest.mark.parametrize("scope", list(review.COMPONENT_SCOPES))
def test_named_components_enforce_explicit_source_allowlists_and_budget(tmp_path, scope):
    modules = review.FOUNDATION | review.AGENTS
    for module in modules:
        put(tmp_path, f"src/autonomy_lab/{module}.py", f"module = '{module}'\n")
    snapshot = review.build_snapshot(tmp_path, scope)
    expected, _tests = review.COMPONENT_SCOPES[scope]
    assert {item["path"] for item in snapshot["files"]} == {
        f"src/autonomy_lab/{module}.py" for module in expected
    }
    payload = review.request_payload(snapshot)
    assert payload["output_config"] == {"effort": "low"}
    assert payload["max_tokens"] == 12_000
    assert review.cost_gate(14_999, scope)["estimated_maximum_usd"] < 0.8
    with pytest.raises(review.ReviewError):
        review.cost_gate(15_000, scope)


def test_remediation_context_is_scoped_untrusted_and_hash_bound(tmp_path):
    put(tmp_path, "src/autonomy_lab/agent.py", "value = 1\n")
    original = review.build_snapshot(tmp_path, "agent")
    followup = review.build_snapshot(tmp_path, "agent", remediation=True)
    assert followup["review_kind"] == "remediation"
    assert followup["snapshot_id"] == original["snapshot_id"]
    assert followup["prompt_sha256"] != original["prompt_sha256"]
    assert "BEGIN UNTRUSTED PRIOR FINDINGS" in followup["prompt"]
    assert review.REMEDIATION_FINDINGS["agent"] in followup["prompt"]
    assert "only unresolved original findings" in review.request_payload(followup)["system"]
    with pytest.raises(review.ReviewError, match="No remediation context"):
        review.build_snapshot(tmp_path, "foundation", remediation=True)


def test_symlink_cannot_include_private_file_or_directory(tmp_path):
    private = put(tmp_path, "private/broker.py", "PRIVATE_SOURCE")
    public = put(tmp_path, "tests/test_broker.py", "def test_public(): pass\n")
    (public.parent / "test_harness.py").symlink_to(private)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/autonomy_lab").symlink_to(private.parent, target_is_directory=True)
    result = review.build_snapshot(tmp_path)
    assert [item["path"] for item in result["files"]] == ["tests/test_broker.py"]
    assert "PRIVATE_SOURCE" not in result["prompt"]


def test_hashes_bind_actual_source_and_paths_deterministically(tmp_path):
    first = put(tmp_path, "src/autonomy_lab/broker.py", "value = 1\n")
    original = review.build_snapshot(tmp_path)
    assert review.build_snapshot(tmp_path) == original
    first.write_text("value = 2\n")
    changed = review.build_snapshot(tmp_path)
    assert changed["snapshot_id"] != original["snapshot_id"]
    assert changed["files"][0]["sha256"] != original["files"][0]["sha256"]
    first.rename(first.with_name("verifier.py"))
    assert review.build_snapshot(tmp_path)["snapshot_id"] != changed["snapshot_id"]


def test_oversized_snapshot_fails_instead_of_silently_truncating(tmp_path, monkeypatch):
    put(tmp_path, "src/autonomy_lab/broker.py", "abcdefghij")
    monkeypatch.setattr(review, "MAX_SOURCE_BYTES", 5)
    with pytest.raises(review.ReviewError, match="byte limit"):
        review.build_snapshot(tmp_path)


def test_only_selected_credential_names_are_parsed_without_shell_execution(tmp_path):
    marker = tmp_path / "must-not-exist"
    credential = put(
        tmp_path,
        ".env",
        f"UNRELATED_SECRET='bad-quote\nANTHROPIC_KEY='$(touch {marker})'\n"
        "export ANTHROPIC_API_KEY='unit-preferred-key' # comment\n",
    )
    assert review.load_anthropic_key(credential) == "unit-preferred-key"
    assert not marker.exists()
    credential.write_text(f"ANTHROPIC_KEY='$(touch {marker})'\n")
    assert review.load_anthropic_key(credential) == f"$(touch {marker})"
    assert not marker.exists()


def test_bad_credential_does_not_appear_in_error(tmp_path):
    credential = put(tmp_path, ".env", 'ANTHROPIC_API_KEY="unit-private-value\n')
    with pytest.raises(review.ReviewError, match="invalid quoting") as error:
        review.load_anthropic_key(credential)
    assert "unit-private-value" not in str(error.value)


def test_request_is_one_bounded_medium_effort_message_without_tools_or_caching():
    payload = review.request_payload({"prompt": "source snapshot"})
    assert payload["model"] == review.MODEL
    assert payload["max_tokens"] == 6000
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "medium"}
    assert len(payload["messages"]) == 1
    assert "tools" not in payload
    assert "cache_control" not in payload


@pytest.mark.parametrize("count", [None, True, 0, -1, 50_001, 1.5, "100"])
def test_token_gate_rejects_invalid_or_excessive_input(count):
    with pytest.raises(review.ReviewError):
        review.cost_gate(count)


def test_cost_gate_has_margin_and_stays_below_one_dollar():
    bound = review.cost_gate(50_000)
    assert bound["input_margin_tokens"] == 2500
    assert bound["estimated_maximum_usd"] == pytest.approx(0.825)
    assert bound["estimated_maximum_usd"] <= review.MAX_BUDGET_USD
    assert review.usage_cost({"input_tokens": 50_000, "output_tokens": 6000}) == pytest.approx(0.8)


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": 100},
        {"input_tokens": True, "output_tokens": 50},
        {"input_tokens": 100, "output_tokens": 50, "cache_creation": None},
    ],
)
def test_incomplete_or_malformed_billing_counters_fail_closed(usage):
    with pytest.raises(review.ReviewError):
        review.usage_cost(usage)


def response_for(**changes):
    return {
        "type": "message",
        "role": "assistant",
        "model": review.MODEL,
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Review findings"}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
        **changes,
    }


@pytest.mark.parametrize(
    "response",
    [
        response_for(model="claude-sonnet-5"),
        response_for(stop_reason="max_tokens"),
        response_for(stop_reason="pause_turn"),
        response_for(content=[]),
        response_for(content=[{"type": "thinking", "thinking": "Unfinished reasoning"}]),
        response_for(content=[{"type": "tool_use", "name": "unexpected"}]),
    ],
)
def test_wrong_model_tool_use_and_incomplete_answers_are_never_success(response):
    with pytest.raises(review.ReviewError):
        review.validate_result(response)


def test_requested_fable_text_is_review_evidence_only():
    assert review.validate_result(response_for()) == "Review findings"


def test_known_credential_in_source_stops_before_network(tmp_path):
    put(tmp_path, "src/autonomy_lab/broker.py", "key = 'unit-selected-secret'\n")
    credential = put(tmp_path, ".env", "ANTHROPIC_API_KEY=unit-selected-secret\n")
    transport = httpx.MockTransport(lambda _request: pytest.fail("must not send"))
    with pytest.raises(review.ReviewError, match="credential appears"):
        review.run_review(tmp_path, credential_file=credential, transport=transport)


@pytest.mark.parametrize("mode", ["excessive_input", "api_error", "incomplete", "success"])
def test_preflight_prevents_overspend_and_generation_is_never_retried(tmp_path, mode):
    put(tmp_path, "src/autonomy_lab/broker.py", "value = 1\n")
    credential = put(tmp_path, ".env", "ANTHROPIC_API_KEY=unit-selected-secret\n")
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "api.anthropic.com"
        assert request.headers["x-api-key"] == "unit-selected-secret"
        assert b"unit-selected-secret" not in request.content
        if request.url.path.endswith("count_tokens"):
            assert "max_tokens" not in json.loads(request.content)
            return httpx.Response(
                200, json={"input_tokens": 50_001 if mode == "excessive_input" else 100}
            )
        assert request.url.path == "/v1/messages"
        if mode == "api_error":
            return httpx.Response(429, json={"error": "Rate limited; unit-selected-secret"})
        return httpx.Response(
            200, json=response_for(stop_reason="max_tokens" if mode == "incomplete" else "end_turn")
        )

    if mode == "success":
        review.run_review(
            tmp_path, credential_file=credential, transport=httpx.MockTransport(handle)
        )
    else:
        with pytest.raises(review.ReviewError):
            review.run_review(
                tmp_path, credential_file=credential, transport=httpx.MockTransport(handle)
            )
    assert len(requests) == (1 if mode == "excessive_input" else 2)
    records = list((tmp_path / ".state/reviews").glob("*.json"))
    assert len(records) == 1
    text = records[0].read_text()
    assert "unit-selected-secret" not in text
    record = json.loads(text)
    assert record["status"] == {"success": "completed", "incomplete": "incomplete"}.get(
        mode, "failed"
    )
    assert record["generation_attempts"] == (0 if mode == "excessive_input" else 1)
