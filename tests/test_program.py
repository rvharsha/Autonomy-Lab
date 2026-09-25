"""Authored language/boundary counterexamples; not live experiment evidence."""

import copy
import itertools
import json

import pytest
from test_refresh_runbook import RefreshTools
from test_runbook import ScriptedTools

from autonomy_lab.campaign import Contract
from autonomy_lab.kubernetes import ROOT
from autonomy_lab.procedure import CHOICES, freeze, parse, run, validate_pin, verify_bindings
from autonomy_lab.refresh import declaration

BASELINE = (ROOT / "procedures/bounded-refresh.json").read_bytes()


def program(**changes):
    return json.dumps({**json.loads(BASELINE), **changes}).encode()


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"null",
        b"[]",
        b"{}",
        b"1",
        b"NaN",
        b"\xff",
        b"{} " * 2048,
        b'{"schema_version":1,"schema_version":1}',
        b"[" * 1001 + b"]" * 1001,
        program(schema_version=True),
        program(schema_version=1.0),
        program(schema_version=2),
        program(backend_unavailable=True),
        program(repairable_routing="shell"),
        program(conditional_rejection="retry_forever"),
        program(policy={"budget": 100}),
        program(command="rm -rf /"),
        program(url="https://example.com"),
        program(repairable_routing=None),
        program(conditional_rejection=["refresh"]),
        BASELINE.decode(),
        {},
    ],
)
def test_invalid_program_never_calls_tools(raw):
    tools = ScriptedTools()
    with pytest.raises(ValueError):
        run(tools, raw, pin={})
    assert tools.calls == []


@pytest.mark.parametrize("values", list(itertools.product(*CHOICES.values())))
def test_all_eight_configurations_are_finite_and_obey_choices(values):
    raw = program(**dict(zip(CHOICES, values)))
    tools = RefreshTools()
    outcome = run(tools, raw, pin=freeze(raw))
    repairs = len(tools.proposals)
    expected = 0 if values[1] == "escalate" else 1 if values[2] == "escalate" else 2
    assert repairs == expected
    assert outcome["outcome"] == ("resolved" if expected == 2 else "escalated")
    assert len(tools.calls) <= 11
    assert type(parse(raw)).__dataclass_params__.frozen


@pytest.mark.parametrize("decision", CHOICES["backend_unavailable"])
def test_backend_unavailable_choice_requires_independent_verification(decision):
    raw = program(backend_unavailable=decision)
    for verdict in ["verified_success", "verified_failure", "indeterminate"]:
        tools = ScriptedTools()
        tools.responses["probe_backend"] = {"kind": "error"}
        tools.responses["verify_recovery"] = {"verdict": verdict}
        result = run(tools, raw, pin=freeze(raw))
        assert tools.proposal is None
        assert result["outcome"] == (
            "healthy" if decision == "verify" and verdict == "verified_success" else "escalated"
        )


@pytest.mark.parametrize(
    "defect", ["bytes", "runtime", "version", "schema_type", "extra", "missing"]
)
def test_exact_bytes_and_runtime_are_required_before_observation(defect):
    raw = BASELINE
    pin = freeze(raw)
    tools = ScriptedTools()
    if defect == "bytes":
        raw += b" "
    elif defect == "runtime":
        pin["definition"]["runtime_files"]["src/autonomy_lab/runbook.py"] = "different"
    elif defect == "version":
        pin["version"] = "different"
    elif defect == "schema_type":
        pin["definition"]["schema_version"] = True
    elif defect == "extra":
        pin["permission"] = "admitted"
    else:
        pin.pop("definition")
    with pytest.raises(ValueError, match="frozen definition"):
        run(tools, raw, pin=pin)
    assert tools.calls == []


def test_source_drift_is_detected_without_trusting_pin_hash(monkeypatch):
    from autonomy_lab import experiments

    pin = freeze(BASELINE)
    original = experiments.release_manifest

    def changed(config):
        result = original(config)
        result["files"]["src/autonomy_lab/procedure.py"] = "different"
        return result

    monkeypatch.setattr(experiments, "release_manifest", changed)
    with pytest.raises(ValueError, match="runtime differ"):
        validate_pin(BASELINE, pin)


@pytest.mark.parametrize("terminal", [False, True])
def test_no_adopting_existing_workspace_or_terminal_claim(terminal):
    tools = ScriptedTools()
    tools.call_count = 1
    if terminal:
        tools.terminal = {"outcome": "resolved"}
    with pytest.raises(ValueError, match="fresh workspace"):
        run(tools, BASELINE, pin=freeze(BASELINE))
    assert tools.calls == []


@pytest.mark.parametrize(
    "extra", [{"bounded_refresh": True}, {"admitted_procedure": "runbook_fallback"}]
)
def test_experimental_program_cannot_reuse_known_variant_admission(extra):
    contract = declaration("stable", interpreted=True)["contract"]
    with pytest.raises(ValueError, match="cannot combine"):
        Contract.model_validate({**contract, **extra})


def bindings(tmp_path):
    pin = freeze(BASELINE)
    spec = {"contract": {"procedure_program": BASELINE.decode()}, "program_pin": pin}
    from test_conflict import stamp

    from autonomy_lab.harness import save

    save(tmp_path / "program-definition.json", pin)
    path = tmp_path / "workers/operator-authored/episode-authored"
    path.mkdir(parents=True)
    save(path / "program.json", {"at": 1000.1, "pin": pin})
    ops = []
    journal = []
    events = []
    for i in [1, 2]:
        op = "authored-" + str(i)
        at = 1005 + 10 * i
        ops.append({"operation_id": op, "request": json.dumps({"evidence_ids": ["e1"]})})
        save(
            path / f"operation-{op}.json",
            {"at": at, "operation_id": op, "episode": path.name, "program_version": pin["version"]},
        )
        journal.append({"operation_id": op, "event": "dispatching", "timestamp": stamp(at - 0.1)})
        events.append(
            {
                "stage": "ResponseComplete",
                "userAgent": "autonomy-lab-operation/" + op,
                "user": {"username": "system:serviceaccount:autonomy-lab:broker"},
                "requestReceivedTimestamp": stamp(at + 0.1),
            }
        )
    card = {
        "workers": [
            {
                "id": "operator-authored",
                "episodes": [{"id": path.name, "attempt": {"started_at": 1000}}],
            }
        ],
        "operations": ops,
    }
    evidence = {
        "operator-authored": [
            {"id": path.name, "records": [{"observation_id": "e1", "timestamp": stamp(1001)}]}
        ]
    }
    return path, {
        "directory": tmp_path,
        "spec": spec,
        "card": card,
        "evidence": evidence,
        "journal": journal,
        "audit": {"events": events},
    }


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "missing",
        "late",
        "too_early",
        "version",
        "episode",
        "definition",
        "pin_time",
        "bool_time",
        "nan_time",
        "foreign_evidence",
        "extra",
        "duplicate_api",
        "no_dispatch",
        "missing_pin",
        "second_missing",
    ],
)
def test_independent_binding_gate_rejects_missing_late_or_misattributed_bindings(tmp_path, defect):
    from autonomy_lab.harness import save

    path, data = bindings(tmp_path)
    file = path / "operation-authored-1.json"
    binding = json.loads(file.read_text())
    if defect in ["late", "too_early", "bool_time", "nan_time"]:
        binding["at"] = {
            "late": 1016,
            "too_early": 1014,
            "bool_time": True,
            "nan_time": float("nan"),
        }[defect]
        save(file, binding)
    elif defect in ["version", "episode"]:
        binding["program_version" if defect == "version" else "episode"] = "different"
        save(file, binding)
    elif defect == "definition":
        pin = copy.deepcopy(data["spec"]["program_pin"])
        pin["definition"]["schema_version"] = True
        save(tmp_path / "program-definition.json", pin)
    elif defect == "pin_time":
        save(path / "program.json", {"at": 1002, "pin": data["spec"]["program_pin"]})
    elif defect == "foreign_evidence":
        data["card"]["operations"][0]["request"] = json.dumps({"evidence_ids": ["another-episode"]})
    elif defect == "extra":
        save(path / "operation-extra.json", binding)
    elif defect == "duplicate_api":
        data["audit"]["events"].append(copy.deepcopy(data["audit"]["events"][0]))
    elif defect == "no_dispatch":
        data["journal"].pop(0)
    elif defect in ["missing", "second_missing", "missing_pin"]:
        (
            file
            if defect == "missing"
            else path / "operation-authored-2.json"
            if defect == "second_missing"
            else path / "program.json"
        ).unlink()
    if defect == "none":
        assert verify_bindings(**data)
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            verify_bindings(**data)


@pytest.mark.parametrize(
    "defect", ["none", "source_drift", "episode_drift", "binding_save_failure", "replay"]
)
def test_campaign_binds_each_operation_before_api_and_refuses_drift(tmp_path, monkeypatch, defect):
    import time
    from types import SimpleNamespace

    from autonomy_lab import campaign as c
    from autonomy_lab import experiments
    from autonomy_lab.harness import save

    directory = tmp_path / "campaign"
    workspace = directory / "operator-authored"
    workspace.mkdir(parents=True)
    contract = Contract.model_validate(declaration("stable", interpreted=True)["contract"])
    save(directory / "program-definition.json", freeze(BASELINE))
    save(directory / "owner.json", {"run_id": "authored-campaign"})
    save(directory / "identities-before.json", {"Service/inventory": "authored-uid"})
    save(directory / "window.json", {"start": time.time() - 1, "end": time.time() + 100})
    rows, calls = [], []
    state = {}

    class Api:
        def __init__(self, *args):
            pass

        def patch_service(self, namespace, name, patch):
            episode = next(workspace.glob("episode-*"))
            record = c.read(episode / ("operation-" + rows[0]["operation_id"] + ".json"))
            assert record["program_version"] == state["pin"]["version"]
            assert record["episode"] == episode.name
            calls.append(rows[0]["operation_id"])
            return {}

    def broker(path, policy, adapter):
        state["adapter"] = adapter
        return SimpleNamespace(owner="authored-owner", policy=policy)

    def execute(tools, raw, *, pin):
        state["pin"] = pin
        episode = tools.path.parent
        assert c.read(episode / "program.json")["pin"] == pin
        assert not tools.path.exists()
        if defect == "source_drift":
            original = experiments.release_manifest

            def changed(config):
                value = original(config)
                value["files"]["src/autonomy_lab/procedure.py"] = "changed"
                return value

            monkeypatch.setattr(experiments, "release_manifest", changed)
        elif defect == "episode_drift":
            save(episode / "program.json", {"at": time.time(), "pin": {}})
        elif defect == "binding_save_failure":
            original_save = c.save

            def fail(path, value):
                if path.name.startswith("operation-"):
                    raise OSError("authored durable write failure")
                original_save(path, value)

            monkeypatch.setattr(c, "save", fail)
        for i in [1, 1 if defect == "replay" else 2]:
            rows[:] = [
                {
                    "operation_id": f"authored-{i}",
                    "status": "dispatching",
                    "owner": "authored-owner",
                }
            ]
            state["adapter"].patch_service("autonomy-lab", "inventory", [])
        return {"outcome": "escalated"}

    monkeypatch.setattr(c, "active", lambda _: None)
    monkeypatch.setattr(c, "operation_rows", lambda _: rows)
    monkeypatch.setattr(c, "ActionBroker", broker)
    monkeypatch.setattr(c, "Kubernetes", Api)
    monkeypatch.setattr(c, "run_program", execute)
    args = (
        directory,
        workspace,
        contract,
        SimpleNamespace(namespace="autonomy-lab", cluster_name="authored"),
        {"quote_url": "http://localhost:1", "inventory_control_url": "http://localhost:2"},
    )
    if defect == "none":
        c.operator(*args)
        assert calls == ["authored-1", "authored-2"]
    else:
        with pytest.raises((ValueError, OSError)):
            c.operator(*args)
        assert calls == (["authored-1"] if defect == "replay" else [])


def test_valid_but_unhelpful_program_is_parseable_without_becoming_eligible():
    raw = program(repairable_routing="escalate")
    assert parse(raw).repairable_routing == "escalate"
    tools = RefreshTools()
    assert run(tools, raw, pin=freeze(raw))["outcome"] == "escalated"
    assert tools.proposals == []
    # This tests the language's adverse choice, not empirical admission of a candidate.


@pytest.mark.parametrize("defect", ["none", "tail", "claim", "operation", "missing_tail_state"])
def test_interruption_before_program_pin_preserves_empty_attempt_only(tmp_path, defect):
    from autonomy_lab.harness import save

    path, data = bindings(tmp_path)
    for file in path.glob("operation-*.json"):
        file.unlink()
    (path / "program.json").unlink()
    data["card"]["operations"] = []
    data["evidence"]["operator-authored"][0]["records"] = []
    data["evidence"]["operator-authored"][0]["uncommitted_bytes"] = 0
    if defect == "missing_tail_state":
        data["evidence"]["operator-authored"][0].pop("uncommitted_bytes")
    elif defect == "tail":
        data["evidence"]["operator-authored"][0]["uncommitted_bytes"] = 1
    elif defect == "claim":
        data["card"]["workers"][0]["episodes"][0]["outcome"] = {"outcome": "healthy"}
    elif defect == "operation":
        save(path / "operation-authored.json", {})
    if defect == "none":
        assert verify_bindings(**data)
    else:
        with pytest.raises(ValueError):
            verify_bindings(**data)


@pytest.mark.parametrize("target", ["pin", "binding", "request"])
@pytest.mark.parametrize(
    "value", [None, [], {}, {"at": 1}, {"operation_id": []}, {"evidence_ids": [{}]}]
)
def test_malformed_binding_records_fail_as_evidence_refusals(tmp_path, target, value):
    from autonomy_lab.harness import save

    path, data = bindings(tmp_path)
    if target == "request":
        data["card"]["operations"][0]["request"] = json.dumps(value)
    else:
        save(path / ("program.json" if target == "pin" else "operation-authored-1.json"), value)
    with pytest.raises(ValueError):
        verify_bindings(**data)


@pytest.mark.parametrize(
    "error_type",
    [ValueError, FileNotFoundError, KeyError, TypeError, RecursionError, AttributeError],
)
def test_binding_failure_preserves_full_base_assessment(tmp_path, monkeypatch, error_type):
    from test_refresh import authored

    from autonomy_lab import refresh
    from autonomy_lab.harness import save

    data = authored()
    for episodes in data["evidence"].values():
        for episode in episodes:
            episode.update(uncommitted_bytes=0, uncommitted_sha256=None)
    spec = declaration("stable", interpreted=True)
    save(tmp_path / "declaration.json", spec)
    save(tmp_path / "record.json", data["record"])
    save(tmp_path / "server-audit.json", data["captured"])
    for attempt in data["record"]["attempts"]:
        path = (
            tmp_path
            / "campaign/workers"
            / data["record"]["repair_worker"]
            / "preflight"
            / attempt["barrier"]["operation_id"]
        )
        path.mkdir(parents=True)
        save(path / "preflight-barrier.json", attempt["barrier"])
        save(path / "preflight-release.json", attempt["release"])
    monkeypatch.setattr(
        refresh.conflict,
        "load_evidence",
        lambda *_: (data["card"], data["raw_samples"], data["evidence"]),
    )
    monkeypatch.setattr(refresh.ambiguity, "journal_events", lambda _: data["journal"])

    def corrupt(*_):
        raise error_type("authored-content-must-not-escape")

    monkeypatch.setattr(refresh, "verify_bindings", corrupt)
    result = refresh.evaluate(tmp_path)
    assert result["status"] == "failed"
    assert result["checks"]["two_spent_dispatches"] is True
    assert result["checks"]["frozen_program_before_every_dispatch"] is False
    assert result["program_binding_error"]["type"] == error_type.__name__
    assert "authored-content-must-not-escape" not in json.dumps(result)
    assert "uncommitted_evidence" in result
    assert result == refresh.evaluate(tmp_path)
    monkeypatch.setattr(refresh, "verify_bindings", lambda *_: True)
    monkeypatch.setattr(refresh, "assess_case", lambda *_: {"status": "failed", "checks": {}})
    assert refresh.evaluate(tmp_path)["status"] == "failed"


def test_deeply_nested_binding_never_passes(tmp_path):
    path, data = bindings(tmp_path)
    (path / "operation-authored-1.json").write_text("[" * 2000 + "]" * 2000)
    # Python's recursion limit may differ under the full test runner. Either
    # JSON decoding or the shape guard must refuse this record.
    with pytest.raises((ValueError, RecursionError)):
        verify_bindings(**data)
