"""Deterministic runbook decision tests with scripted public tools, not E2E evidence."""

import copy

import pytest

from autonomy_lab.runbook import run


class ScriptedTools:
    """Test-only public-interface adapter; contains no cluster or model behavior."""

    def __init__(self, *, target_port=9999, backend_port=9091, app_ok=False):
        self.terminal = None
        self.call_count = 0
        self.calls = []
        self.proposal = None
        self.responses = {
            "observe_service": {
                "run_id": "test-run",
                "namespace": "test-namespace",
                "service": {
                    "metadata": {
                        "name": "inventory",
                        "namespace": "test-namespace",
                        "uid": "test-uid",
                        "resourceVersion": "42",
                    },
                    "spec": {
                        "selector": {"app": "inventory"},
                        "ports": [
                            {
                                "name": "http",
                                "port": 80,
                                "protocol": "TCP",
                                "targetPort": target_port,
                            },
                        ],
                    },
                },
            },
            "probe_backend": {
                "kind": "response",
                "status_code": 200,
                "backend_port": backend_port,
                "sku": "bolt",
                "quantity": 1,
                "body": {
                    "sku": "bolt",
                    "unit_price_minor": 733,
                    "stock": 10,
                    "available": True,
                    "currency": "USD",
                },
            },
            "probe_application": {
                "kind": "response",
                "status_code": 200 if app_ok else 503,
                "body": {
                    "sku": "bolt",
                    "quantity": 1,
                    "unit_price_minor": 733,
                    "total_minor": 733,
                    "available": True,
                    "currency": "USD",
                },
            },
            "propose_repair": {"status": "acknowledged"},
            "get_operation": {"status": "acknowledged"},
            "verify_recovery": {
                "verdict": "verified_success",
                "reasons": [],
                "counts": {"total": 2},
            },
        }

    def call(self, name, args):
        self.call_count += 1
        self.calls.append((name, copy.deepcopy(args)))
        if name == "finish":
            self.terminal = {"kind": "claim", **args}
            payload = self.terminal
        else:
            if name == "propose_repair":
                self.proposal = copy.deepcopy(args)
            payload = self.responses[name]
        return {
            "observation_id": f"test-observation-{len(self.calls)}",
            "run_id": "test-run",
            "timestamp": "test-only",
            "source": name,
            "payload": copy.deepcopy(payload),
        }


def test_routing_repair_uses_observed_port_identity_and_evidence():
    tools = ScriptedTools(backend_port=9091)
    result = run(tools)
    assert result["outcome"] == "resolved"
    assert tools.proposal["target_port"] == 9091  # Must not hardcode the production fixture port.
    assert tools.proposal["expected_target_port"] == 9999
    assert tools.proposal["resource_version"] == "42"
    assert tools.proposal["evidence_ids"] == [f"test-observation-{index}" for index in range(1, 4)]
    assert [name for name, _ in tools.calls] == [
        "observe_service",
        "probe_backend",
        "probe_application",
        "propose_repair",
        "verify_recovery",
        "finish",
    ]


def test_healthy_verified_application_never_mutates():
    tools = ScriptedTools(target_port=9091, app_ok=True)
    assert run(tools)["outcome"] == "healthy"
    assert tools.proposal is None
    assert [name for name, _ in tools.calls][-2:] == ["verify_recovery", "finish"]


@pytest.mark.parametrize(
    "backend",
    [
        {"kind": "error", "error": "transport_failure"},
        {"kind": "response", "status_code": 503, "body": {"detail": "database unavailable"}},
        {"kind": "response", "status_code": 200, "body": {"sku": "bolt"}},
    ],
)
def test_backend_failure_escalates_without_repair(backend):
    tools = ScriptedTools()
    tools.responses["probe_backend"] = backend
    assert run(tools)["outcome"] == "escalated"
    assert tools.proposal is None


def test_wrong_http_200_total_with_healthy_route_escalates():
    tools = ScriptedTools(target_port=9091, app_ok=True)
    tools.responses["probe_application"]["body"]["total_minor"] += 1
    assert run(tools)["outcome"] == "escalated"
    assert tools.proposal is None


def test_out_of_scope_selector_never_mutates():
    tools = ScriptedTools()
    tools.responses["observe_service"]["service"]["spec"]["selector"] = {"app": "other"}
    assert run(tools)["outcome"] == "escalated"
    assert tools.proposal is None


@pytest.mark.parametrize("status", ["uncertain", "dispatching", "prepared"])
def test_uncertain_or_prepared_operation_is_looked_up_without_retry(status):
    tools = ScriptedTools()
    tools.responses["propose_repair"] = {"status": status}
    tools.responses["get_operation"] = {
        "status": "uncertain",
        "reconciliation": {
            "observation": "desired_state_observed",
            "attribution": "not_established",
        },
    }
    result = run(tools)
    assert result["outcome"] == "resolved"
    assert "attribution is not established" in result["reason"]
    names = [name for name, _ in tools.calls]
    assert names.count("propose_repair") == 1
    assert names.count("get_operation") == 1
    assert names.index("get_operation") < names.index("verify_recovery")


def test_lost_tool_response_looks_up_original_operation():
    tools = ScriptedTools()
    tools.responses["propose_repair"] = {"kind": "error", "error": "tool_unavailable"}
    assert run(tools)["outcome"] == "resolved"
    lookup = next(args for name, args in tools.calls if name == "get_operation")
    assert lookup["operation_id"] == tools.proposal["operation_id"]
    assert [name for name, _ in tools.calls].count("propose_repair") == 1


@pytest.mark.parametrize(
    "operation",
    [
        {"status": "rejected", "reason": "resource_version_changed"},
        {"status": "prepared"},
        {"status": "uncertain", "reconciliation": {"observation": "desired_state_not_observed"}},
        {"kind": "error", "error": "operation_not_found"},
    ],
)
def test_unresolved_outcome_escalates_without_blind_retry(operation):
    tools = ScriptedTools()
    tools.responses["propose_repair"] = {"status": "uncertain"}
    tools.responses["get_operation"] = operation
    assert run(tools)["outcome"] == "escalated"
    names = [name for name, _ in tools.calls]
    assert names.count("propose_repair") == 1
    assert "verify_recovery" not in names


@pytest.mark.parametrize("verdict", ["verified_failure", "indeterminate"])
@pytest.mark.parametrize("initially_healthy", [False, True])
def test_verifier_must_establish_success(verdict, initially_healthy):
    tools = ScriptedTools(target_port=9091 if initially_healthy else 9999, app_ok=initially_healthy)
    tools.responses["verify_recovery"]["verdict"] = verdict
    assert run(tools)["outcome"] == "escalated"


def test_terminal_restart_does_not_execute_more_tools():
    tools = ScriptedTools()
    first = run(tools)
    call_count = len(tools.calls)
    assert run(tools) == first
    assert len(tools.calls) == call_count


def test_previously_used_nonterminal_workspace_is_rejected():
    tools = ScriptedTools()
    tools.call("observe_service", {})
    with pytest.raises(ValueError, match="requires a fresh workspace"):
        run(tools)
    assert tools.call_count == 1
    assert tools.terminal is None


def test_interrupted_repair_cannot_restart_as_verified_initial_health():
    tools = ScriptedTools()
    original = tools.call

    def interrupt(name, args):
        if name == "verify_recovery":
            raise RuntimeError("test-only interruption after repair")
        return original(name, args)

    tools.call = interrupt
    with pytest.raises(RuntimeError):
        run(tools)
    assert tools.proposal is not None
    tools.responses["observe_service"]["service"]["spec"]["ports"][0]["targetPort"] = 9091
    tools.responses["probe_application"]["status_code"] = 200
    tools.call = original
    prior_calls = copy.deepcopy(tools.calls)
    with pytest.raises(ValueError, match="mid-run resumption is unsupported"):
        run(tools)
    assert tools.calls == prior_calls
    assert tools.terminal is None


@pytest.mark.parametrize(
    "observation_id,eligible",
    [
        (None, False),
        ("", True),
        (" ", True),
        (42, True),
        ("not-evidence", False),
    ],
)
def test_non_evidence_tool_errors_never_enter_claim_references(observation_id, eligible):
    tools = ScriptedTools()
    original = tools.call

    def limited(name, args):
        response = original(name, args)
        if name == "probe_backend":
            response.update(observation_id=observation_id, evidence_eligible=eligible)
            response["payload"] = {"kind": "error", "error": "tool_budget_exhausted"}
        return response

    tools.call = limited
    result = run(tools)
    assert result["outcome"] == "escalated"
    assert result["evidence_ids"] == ["test-observation-1", "test-observation-3"]
