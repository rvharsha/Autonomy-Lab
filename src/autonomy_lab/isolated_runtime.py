"""Trusted host for a network-denied, immutable agent container and narrow RPC."""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from autonomy_lab.broker import OperationConflict
from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, command
from autonomy_lab.rpc import PipeReader, PipeWriter, RemoteError, error_record


def clean_environment():
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}


class AuthorityProcess:
    def __init__(self, config, log_path):
        self.log = Path(log_path).open("wb")
        self.process = subprocess.Popen([sys.executable, "-m", "autonomy_lab.authority_worker"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                        env=clean_environment())
        self.closed = False
        self.sequence = 0
        self.reader, self.writer = PipeReader(self.process.stdout), PipeWriter(self.process.stdin)
        try:
            self.writer.write(config, time.monotonic() + 30)
        except BaseException:
            self.close()
            raise

    def call(self, method, argument=None):
        if self.closed:
            raise RuntimeError("Authority channel is closed")
        self.sequence += 1
        deadline = time.monotonic() + 180
        try:
            self.writer.write({"id": self.sequence, "method": method, "argument": argument}, deadline)
            response = self.reader.read(deadline)
            if response.get("id") != self.sequence:
                raise ValueError("Authority response identity mismatch")
        except BaseException:
            self.close()
            raise
        if "error" in response:
            kind = response["error"]["error_type"]
            if kind == "KeyError":
                raise KeyError(argument)
            if kind == "OperationConflict":
                raise OperationConflict("operation_id_conflict")
            raise RemoteError(response["error"])
        return response["result"]

    def propose(self, value):
        return self.call("propose", value)

    def lookup(self, value):
        return self.call("lookup", value)

    def reconcile(self, value):
        return self.call("reconcile", value)

    def events(self, value):
        return self.call("events", value)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def build_agent_image():
    toolchain = json.loads((ROOT / "infra/toolchain.json").read_text())
    files = ["infra/agent.Dockerfile", "requirements.lock", "src/autonomy_lab/__init__.py",
             "src/autonomy_lab/agent.py", "src/autonomy_lab/context.py", "src/autonomy_lab/rpc.py", "src/autonomy_lab/isolated_agent.py"]
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    # Keep the exact build referenced even when another check builds identical
    # source with different context metadata/provenance concurrently.
    tag = "autonomy-lab-agent:" + digest.hexdigest()[:20] + "-" + uuid.uuid4().hex[:8]
    command(["docker", "build", "--build-arg", f"PYTHON_IMAGE={toolchain['python_image']}",
             "-f", str(ROOT / "infra/agent.Dockerfile"), "-t", tag, str(ROOT)], timeout=420)
    image_id = command(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).strip()
    if not image_id.startswith("sha256:"):
        raise ValueError("Missing immutable agent image ID")
    return image_id


def container_args(image_id, workspace, name):
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise ValueError("Agent image must be immutable")
    workspace = Path(workspace)
    if workspace.is_symlink():
        raise ValueError("Agent workspace cannot be a symlink")
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.getuid() == 0:
        os.chown(workspace, 10001, os.getgid() or 10001)
    return ["docker", "run", "--rm", "--init", "--name", name,
            "--label", "autonomy-lab.role=agent", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64",
            "--memory=256m", "--cpus=1", "--user", f"{os.getuid() or 10001}:{os.getgid() or 10001}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--mount",
            f"type=bind,source={workspace.resolve()},target=/workspace", "-i", image_id]


class ModelRelay:
    """A host-owned ledger enforces spend even if writable agent state is corrupted."""
    def __init__(self, client, path, options):
        self.client, self.path, self.options = client, Path(path), options
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            "calls": 0, "tokens": 0, "pending": False, "responses": [], "counts": 0}
        self.preflight = None

    def call(self, method, arguments):
        if self.state["pending"]:
            raise ValueError("Uncertain provider request cannot be retried")
        if method == "count_tokens":
            if self.state["counts"] >= self.options["max_turns"] * 2:
                raise ValueError("Model count budget exhausted")
            self.state["counts"] += 1
            save(self.path, self.state)
            count = self.client.count_tokens(**arguments)
            self.preflight = (arguments, count)
            return count
        if method != "generate" or self.preflight is None:
            raise ValueError("Provider generation requires a counted input")
        inputs = {k: v for k, v in arguments.items() if k != "max_output_tokens"}
        counted_inputs, count = self.preflight
        self.preflight = None
        output = arguments.get("max_output_tokens")
        if inputs != counted_inputs or type(output) is not int or not 1 <= output <= self.options["max_output_tokens"]:
            raise ValueError("Provider request changed after counting")
        # Reserve all previous thought tokens conservatively, as in the agent.
        thoughts = 0
        prior_contents = [r.get("candidates", [{}])[0].get("content") for r in self.state["responses"]]
        submitted = [c for c in inputs["contents"] if c.get("role") == "model"]
        for content in inputs["contents"]:
            if content.get("role") != "model" and any(
                "thoughtSignature" in part or "thought_signature" in part for part in content.get("parts", [])
            ):
                raise ValueError("Signature attached to unrecognized history")
        if any(c not in prior_contents for c in submitted):
            raise ValueError("Unrecognized model history at provider relay")
        for response in self.state["responses"]:
            if response.get("candidates", [{}])[0].get("content") not in submitted:
                continue
            usage = response["usageMetadata"]
            value = usage.get("thoughtsTokenCount")
            if value is None:
                value = usage["totalTokenCount"] - usage["promptTokenCount"] - usage["candidatesTokenCount"]
            if type(value) is not int or value < 0:
                raise ValueError("Invalid prior thought usage")
            thoughts += value * submitted.count(response["candidates"][0]["content"])
        if self.state["calls"] >= self.options["max_turns"] or self.state["tokens"] + count + thoughts + output > self.options["max_total_tokens"]:
            raise ValueError("Host model budget exhausted")
        self.state["calls"] += 1
        self.state["pending"] = True
        save(self.path, self.state)
        try:
            response = self.client.generate(**arguments)
        except Exception as error:
            response = getattr(error, "response", None)
            if isinstance(response, dict):
                self.record(response, count + thoughts + output)
            raise
        self.record(response, count + thoughts + output)
        return response

    def record(self, response, reservation):
        usage = response.get("usageMetadata", {}).get("totalTokenCount")
        if type(usage) is not int or usage < 0:
            raise ValueError("Unknown provider usage")
        self.state["responses"].append(response)
        self.state["tokens"] += usage
        self.state["pending"] = False
        save(self.path, self.state)
        if usage > reservation:
            self.state["pending"] = True  # fail closed on provider accounting overrun
            save(self.path, self.state)
            raise ValueError("Provider usage exceeded reservation")


def charge_rpc(path, maximum):
    path = Path(path)
    record = json.loads(path.read_text()) if path.exists() else {"count": 0, "limit": maximum}
    record["limit"] = min(record["limit"], maximum)
    if record["count"] >= record["limit"]:
        raise ValueError("Durable RPC budget exhausted")
    record["count"] += 1
    save(path, record)


def run_isolated_agent(client, toolbox, state_path, *, image_id, timeout=900, crash_boundary=None, **options):
    state_path = Path(state_path)
    workspace = state_path.parent / "agent-workspace"
    name = "autolab-agent-" + uuid.uuid4().hex[:12]
    if crash_boundary not in {None, "model_response", "tool_dispatch", "checkpoint", "terminal"}:
        raise ValueError("Unknown crash boundary")
    crash_marker = state_path.parent / "runtime-crash.json"
    armed = crash_boundary is not None and not crash_marker.exists()
    args = container_args(image_id, workspace, name)
    metadata = {"image_id": image_id, "name": name, "network": "none", "read_only_root": True,
                "workspace": str(workspace), "status": "running"}
    save(state_path.parent / "agent-runtime.json", metadata)
    relay = ModelRelay(client, state_path.parent / "model-relay.json", options)
    log = (state_path.parent / "agent-container.log").open("ab")
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
    deadline = time.monotonic() + timeout
    reader, writer = PipeReader(process.stdout), PipeWriter(process.stdin)
    try:
        writer.write( {"run_id": toolbox.run_id, "declarations": toolbox.declarations(),
                                   "terminal": toolbox.terminal, "model": client.model,
                                   "agent_options": options, "checkpoint_probe": armed and crash_boundary == "checkpoint"}, deadline)
        sequence = 0
        while time.monotonic() < deadline:
            request = reader.read(deadline)
            if request.get("method") == "result":
                metadata["status"] = "returned"
                return request["result"]
            sequence += 1
            if request.get("id") != sequence or sequence > options["max_turns"] * 12:
                raise ValueError("Invalid RPC sequence or budget")
            charge_rpc(state_path.parent / "rpc-budget.json", options["max_turns"] * 12)
            try:
                if request["method"] == "tool":
                    arguments = request["arguments"]
                    observation = toolbox.call(arguments["name"], arguments["args"])
                    result = {"observation": observation, "terminal": toolbox.terminal}
                elif request["method"] in {"count_tokens", "generate"}:
                    result = relay.call(request["method"], request["arguments"])
                elif request["method"] == "boundary":
                    result = {"observed": True}
                else:
                    raise ValueError("Unknown RPC method")
                response = {"id": sequence, "result": result}
            except Exception as error:
                response = {"id": sequence, "error": error_record(error)}
            method, arguments = request["method"], request.get("arguments", {})
            crash = armed and (
                crash_boundary == "model_response" and method == "generate"
                or crash_boundary == "tool_dispatch" and method == "tool" and arguments.get("name") == "propose_repair"
                or crash_boundary == "terminal" and method == "tool" and arguments.get("name") == "finish"
                or crash_boundary == "checkpoint" and method == "boundary" and arguments.get("event") == "tool_checkpoint" and arguments.get("tool") == "propose_repair"
            )
            if crash and "error" not in response:
                checkpoint = workspace / "agent-state.json"
                before = checkpoint.read_bytes()
                killed = subprocess.run(["docker", "kill", "--signal=KILL", name], capture_output=True, timeout=30)
                if killed.returncode:
                    raise RuntimeError("Agent crash injection failed")
                save(crash_marker, {"boundary": crash_boundary, "signal": "SIGKILL", "container": name,
                                    "checkpoint_sha256": hashlib.sha256(before).hexdigest(),
                                    "host_model_calls": relay.state["calls"], "host_model_tokens": relay.state["tokens"]})
                metadata["status"] = "killed"
                return {"status": "crashed", "reason": crash_boundary}
            writer.write(response, deadline)
        raise TimeoutError("Agent runtime deadline")
    except BaseException as error:
        metadata.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=log, timeout=30)
        process.wait(timeout=30)
        process.stdin.close()
        process.stdout.close()
        log.close()
        checkpoint = workspace / "agent-state.json"
        if checkpoint.exists():
            if checkpoint.is_symlink() or checkpoint.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Invalid agent checkpoint export")
            state_path.write_bytes(checkpoint.read_bytes())
        save(state_path.parent / "agent-runtime.json", metadata)
