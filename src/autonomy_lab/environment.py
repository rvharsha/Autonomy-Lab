"""A fresh, explicitly scoped application environment for each run."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import yaml

from autonomy_lab.audit import configure
from autonomy_lab.kubernetes import ROOT, Kubernetes, command


def image_tag() -> str:
    digest = hashlib.sha256()
    paths = [ROOT / "Dockerfile", ROOT / "requirements.lock", *sorted((ROOT / "src").rglob("*.py"))]
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return f"autonomy-lab:{digest.hexdigest()[:16]}"


def manifests(image: str, postgres_image: str) -> list[dict]:
    namespace = "autonomy-lab"
    objects: list[dict] = [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}
    ]

    def add(kind, name, **fields):
        obj = {
            "apiVersion": "apps/v1" if kind == "Deployment" else "v1",
            "kind": kind,
            "metadata": {"name": name, "namespace": namespace},
            **fields,
        }
        objects.append(obj)

    add(
        "ConfigMap",
        "database-init",
        data={"init.sql": (ROOT / "fixtures/database.sql").read_text()},
    )
    add(
        "Secret",
        "database",
        type="Opaque",
        stringData={
            "admin-password": "lab-test-only",
            "inventory-url": "postgresql://inventory_reader:inventory-test-only@postgres:5432/lab",
        },
    )
    add(
        "PersistentVolumeClaim",
        "postgres-data",
        spec={
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "128Mi"}},
        },
    )
    add("ServiceAccount", "verifier", automountServiceAccountToken=False)
    objects.extend(
        [
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {"name": "verifier", "namespace": namespace},
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["services"],
                        "resourceNames": ["inventory"],
                        "verbs": ["get"],
                    }
                ],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": "verifier", "namespace": namespace},
                "subjects": [
                    {"kind": "ServiceAccount", "name": "verifier", "namespace": namespace}
                ],
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": "verifier",
                },
            },
        ]
    )
    add("ServiceAccount", "broker", automountServiceAccountToken=False)
    broker_role = copy.deepcopy(next(obj for obj in objects if obj["kind"] == "Role"))
    broker_role["metadata"]["name"] = "broker"
    broker_role["rules"][0]["verbs"] = ["get", "patch"]
    broker_binding = copy.deepcopy(next(obj for obj in objects if obj["kind"] == "RoleBinding"))
    broker_binding["metadata"]["name"] = "broker"
    broker_binding["subjects"][0]["name"] = "broker"
    broker_binding["roleRef"]["name"] = "broker"
    objects.extend([broker_role, broker_binding])
    add("ServiceAccount", "observer", automountServiceAccountToken=False)
    observer_role = copy.deepcopy(next(obj for obj in objects if obj["kind"] == "Role"))
    observer_role["metadata"]["name"] = "observer"
    observer_role["rules"].append({"apiGroups": [""], "resources": ["events"], "verbs": ["list"]})
    observer_binding = copy.deepcopy(broker_binding)
    observer_binding["metadata"]["name"] = "observer"
    observer_binding["subjects"][0]["name"] = "observer"
    observer_binding["roleRef"]["name"] = "observer"
    objects.extend([observer_role, observer_binding])

    for name, port in [("postgres", 5432), ("inventory", 80), ("quote", 80)]:
        target = 5432 if name == "postgres" else 8080
        add(
            "Service",
            name,
            spec={
                "selector": {"app": name},
                "ports": [
                    {
                        "name": "postgres" if name == "postgres" else "http",
                        "port": port,
                        "targetPort": target,
                        "protocol": "TCP",
                    },
                ],
            },
        )

    for name in ["postgres", "inventory", "quote"]:
        container: dict = {
            "name": name,
            "image": postgres_image if name == "postgres" else image,
            "imagePullPolicy": "IfNotPresent",
            "resources": {
                "requests": {"cpu": "50m", "memory": "64Mi"},
                "limits": {"cpu": "1", "memory": "256Mi"},
            },
        }
        spec: dict = {"automountServiceAccountToken": False, "containers": [container]}
        if name == "postgres":
            container.update(
                {
                    "env": [
                        {"name": "POSTGRES_DB", "value": "lab"},
                        {
                            "name": "POSTGRES_PASSWORD",
                            "valueFrom": {
                                "secretKeyRef": {"name": "database", "key": "admin-password"}
                            },
                        },
                        {"name": "PGDATA", "value": "/var/lib/postgresql/data/pgdata"},
                    ],
                    "volumeMounts": [
                        {"name": "data", "mountPath": "/var/lib/postgresql/data"},
                        {
                            "name": "init",
                            "mountPath": "/docker-entrypoint-initdb.d",
                            "readOnly": True,
                        },
                    ],
                    "readinessProbe": {
                        "exec": {"command": ["pg_isready", "-U", "postgres", "-d", "lab"]},
                        "periodSeconds": 2,
                    },
                }
            )
            spec["volumes"] = [
                {"name": "data", "persistentVolumeClaim": {"claimName": "postgres-data"}},
                {"name": "init", "configMap": {"name": "database-init"}},
            ]
        else:
            container["command"] = [
                "python",
                "-m",
                "uvicorn",
                f"autonomy_lab.{name}:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
            ]
            container["ports"] = [{"name": "http", "containerPort": 8080}]
            container["securityContext"] = {
                "runAsNonRoot": True,
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            }
            container["readinessProbe"] = {
                "httpGet": {"path": "/readyz", "port": "http"},
                "periodSeconds": 2,
            }
            container["livenessProbe"] = {
                "httpGet": {"path": "/healthz", "port": "http"},
                "periodSeconds": 5,
            }
            container["env"] = (
                [
                    {
                        "name": "DATABASE_URL",
                        "valueFrom": {"secretKeyRef": {"name": "database", "key": "inventory-url"}},
                    }
                ]
                if name == "inventory"
                else [{"name": "INVENTORY_URL", "value": "http://inventory"}]
            )
        add(
            "Deployment",
            name,
            spec={
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"app": name}},
                "template": {"metadata": {"labels": {"app": name}}, "spec": spec},
            },
        )
    return objects


def provision(run_dir: Path, run_id: str, *, cleanup_on_exit=True, lease_seconds=7200) -> Kubernetes:
    toolchain = json.loads((ROOT / "infra/toolchain.json").read_text())
    kind = str(ROOT / ".tools/kind")
    cluster = f"autolab-{run_id}"
    kubeconfig = run_dir / "kubeconfig"
    kube = Kubernetes(kubeconfig, cluster)
    image = image_tag()
    # Never claim or delete an existing environment with this name.
    if cluster in command([kind, "get", "clusters"]).splitlines():
        raise RuntimeError(f"Refusing to reuse existing cluster {cluster}")
    (run_dir / "environment.json").write_text(
        json.dumps(
            {
                "cluster": cluster,
                "run_id": run_id,
                "app_image": image,
                "toolchain": toolchain,
                "status": "provisioning",
                "runtime": "local-kind; AX not validated",
            },
            indent=2,
        )
        + "\n"
    )
    from autonomy_lab.janitor import start
    if cleanup_on_exit:
        start(run_dir, lifetime_seconds=lease_seconds)
    kubeconfig.touch(mode=0o600)
    command(
        [
            kind,
            "create",
            "cluster",
            "--name",
            cluster,
            "--kubeconfig",
            str(kubeconfig),
            "--config",
            str(configure(run_dir, ROOT / "infra/kind.yaml")),
            "--image",
            toolchain["node_image"],
            "--wait",
            "120s",
        ],
        timeout=420,
    )
    os.chmod(kubeconfig, 0o600)
    command(
        [
            "docker",
            "build",
            "--build-arg",
            f"PYTHON_IMAGE={toolchain['python_image']}",
            "-t",
            image,
            str(ROOT),
        ],
        timeout=420,
    )
    command([kind, "load", "docker-image", "--name", cluster, image], timeout=240)
    kube.call(
        "apply", "-f", "-", input=yaml.safe_dump_all(manifests(image, toolchain["postgres_image"]))
    )
    for name in ["postgres", "inventory", "quote"]:
        try:
            kube.call("rollout", "status", f"deployment/{name}", "--timeout=120s")
        except Exception:
            for label, arguments in [
                ("pods", ("get", "pods", "-o", "json")),
                ("events", ("get", "events", "-o", "json")),
                ("failed-deployment", ("logs", f"deployment/{name}", "--all-containers", "--tail=150")),
            ]:
                try:
                    (run_dir / f"provision-{label}.log").write_text(kube.call(*arguments, timeout=30))
                except Exception:
                    pass
            raise
    return kube


def service_identity(kube: Kubernetes, run_dir: Path, identity: str) -> Kubernetes:
    if identity not in {"broker", "verifier", "observer"}:
        raise ValueError("Unknown lab identity")
    config = yaml.safe_load(kube.call("config", "view", "--raw", "--minify"))
    token = kube.call("create", "token", identity, "--duration=1h").strip()
    config["users"] = [{"name": identity, "user": {"token": token}}]
    for context in config["contexts"]:
        context["context"]["user"] = identity
    path = run_dir / f"{identity}-kubeconfig"
    # Credentials stay in ignored local artifacts and are never report attachments.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        yaml.safe_dump(config, stream)
    return Kubernetes(path, kube.cluster_name)


def verifier_identity(kube: Kubernetes, run_dir: Path) -> Kubernetes:
    return service_identity(kube, run_dir, "verifier")


def reset_application(kube: Kubernetes, image: str, postgres_image: str):
    kube.call("delete", "namespace", kube.namespace, "--wait=true", "--timeout=120s")
    kube.call("apply", "-f", "-", input=yaml.safe_dump_all(manifests(image, postgres_image)))
    for name in ["postgres", "inventory", "quote"]:
        kube.call("rollout", "status", f"deployment/{name}", "--timeout=120s")


def teardown(run_dir: Path):
    from autonomy_lab.harness import save
    metadata = json.loads((run_dir / "environment.json").read_text())
    kube = Kubernetes(run_dir / "kubeconfig", metadata["cluster"])
    command(
        [
            str(ROOT / ".tools/kind"),
            "delete",
            "cluster",
            "--name",
            kube.cluster_name,
            "--kubeconfig",
            str(kube.kubeconfig),
        ],
        timeout=120,
    )
    metadata["status"] = "deleted"
    save(run_dir / "environment.json", metadata)
