"""Controller-side Kubernetes access, always using an explicit disposable context.

This module is never exposed as a general command tool to an agent.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import ssl
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml

from autonomy_lab.bounded_http import request

ROOT = Path(__file__).resolve().parents[2]


def command(args: list[str], *, input: str | None = None, timeout: float = 180) -> str:
    result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed: {result.stderr.strip()}")
    return result.stdout


class Kubernetes:
    def __init__(self, kubeconfig: Path, cluster_name: str, namespace: str = "autonomy-lab"):
        if not re.fullmatch(r"autolab-[a-f0-9]{8}", cluster_name):
            raise ValueError("Only an explicitly named Autonomy Lab cluster is permitted")
        self.kubeconfig = kubeconfig.resolve()
        self.cluster_name = cluster_name
        self.namespace = namespace

    def args(self, *args: str) -> list[str]:
        return [
            str(ROOT / ".tools/kubectl"),
            "--kubeconfig",
            str(self.kubeconfig),
            "--context",
            f"kind-{self.cluster_name}",
            "--namespace",
            self.namespace,
            "--request-timeout=20s",
            *args,
        ]

    def call(self, *args: str, input: str | None = None, timeout: float = 180) -> str:
        return command(self.args(*args), input=input, timeout=timeout)

    def get_service(self, namespace: str, name: str) -> dict:
        if namespace != self.namespace:
            raise ValueError("namespace outside this trial")
        return json.loads(self.call("get", "service", name, "-o", "json"))

    def patch_service(self, namespace: str, name: str, patch: list[dict]) -> dict:
        from autonomy_lab.broker import PatchRejected

        if namespace != self.namespace:
            raise PatchRejected("namespace_out_of_scope")
        # Read structured HTTP status rather than infer outcomes from kubectl's prose.
        config = yaml.safe_load(self.kubeconfig.read_text())
        context = next(
            item["context"]
            for item in config["contexts"]
            if item["name"] == f"kind-{self.cluster_name}"
        )
        cluster = next(
            item["cluster"] for item in config["clusters"] if item["name"] == context["cluster"]
        )
        user = next(item["user"] for item in config["users"] if item["name"] == context["user"])
        tls = ssl.create_default_context(
            cadata=base64.b64decode(cluster["certificate-authority-data"]).decode()
        )
        headers = {"Content-Type": "application/json-patch+json"}
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "actor": context["user"],
            "namespace": namespace,
            "service": name,
            "patch": patch,
        }

        def audit(**extra):
            with (self.kubeconfig.parent / "api-mutations.jsonl").open("a") as stream:
                stream.write(json.dumps({**record, **extra}) + "\n")
                stream.flush()

        with tempfile.TemporaryDirectory() as directory:
            if "token" in user:
                headers["Authorization"] = f"Bearer {user['token']}"
            else:
                certificate = Path(directory) / "client.crt"
                key = Path(directory) / "client.key"
                certificate.write_bytes(base64.b64decode(user["client-certificate-data"]))
                key.write_bytes(base64.b64decode(user["client-key-data"]))
                key.chmod(0o600)
                tls.load_cert_chain(certificate, key)
            audit(event="dispatch")
            with httpx.Client(verify=tls, headers=headers, timeout=30, trust_env=False) as client:
                response = request(client, "PATCH",
                    f"{cluster['server']}/api/v1/namespaces/{quote(namespace, safe='')}/services/{quote(name, safe='')}",
                    json=patch,
                    timeout=30, max_bytes=1024 * 1024,
                )
            audit(event="response", status_code=response.status_code)
        if response.status_code in {400, 401, 403, 404, 409, 422}:
            raise PatchRejected(f"api_rejected_{response.status_code}")
        if not response.is_success:
            raise RuntimeError("Kubernetes patch did not return an acknowledged result")
        return response.json()

    def set_target_port(self, port: int) -> dict:
        service = self.get_service(self.namespace, "inventory")
        metadata = service["metadata"]
        old = service["spec"]["ports"][0]["targetPort"]
        return self.patch_service(
            self.namespace,
            "inventory",
            [
                {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
                {
                    "op": "test",
                    "path": "/metadata/resourceVersion",
                    "value": metadata["resourceVersion"],
                },
                {"op": "test", "path": "/spec/ports/0/name", "value": "http"},
                {"op": "test", "path": "/spec/ports/0/targetPort", "value": old},
                {"op": "replace", "path": "/spec/ports/0/targetPort", "value": port},
            ],
        )

    @contextlib.contextmanager
    def forward(self, resource: str, remote_port: int):
        # kubectl chooses an unused loopback port. A file prevents pipe backpressure.
        with tempfile.TemporaryFile(mode="w+t") as log:
            process = subprocess.Popen(
                self.args("port-forward", "--address=127.0.0.1", resource, f"0:{remote_port}"),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    log.seek(0)
                    output = log.read()
                    match = re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", output)
                    if match:
                        yield int(match.group(1))
                        return
                    if process.poll() is not None:
                        raise RuntimeError(f"port-forward exited: {output}")
                    time.sleep(0.1)
                raise TimeoutError("port-forward failed to become ready")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
