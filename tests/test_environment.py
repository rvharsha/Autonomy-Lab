"""Manifest and local boundary checks; not live RBAC or database enforcement evidence."""

import json
import re
import stat
from urllib.parse import urlparse

import pytest
import yaml

from autonomy_lab import environment
from autonomy_lab.broker import PatchRejected
from autonomy_lab.kubernetes import Kubernetes


@pytest.fixture
def resources():
    return environment.manifests(
        "unit.invalid/app@sha256:" + "1" * 64,
        "unit.invalid/postgres@sha256:" + "2" * 64,
    )


def test_rbac_grants_only_scoped_service_reads_and_broker_patch(resources):
    roles = {item["metadata"]["name"]: item for item in resources if item["kind"] == "Role"}
    assert set(roles) == {"broker", "verifier"}
    assert not any(item["kind"] in {"ClusterRole", "ClusterRoleBinding"} for item in resources)
    for name, verbs in {"broker": {"get", "patch"}, "verifier": {"get"}}.items():
        assert roles[name]["metadata"]["namespace"] == "autonomy-lab"
        assert len(roles[name]["rules"]) == 1
        rule = roles[name]["rules"][0]
        assert rule["apiGroups"] == [""]
        assert rule["resources"] == ["services"]
        assert rule["resourceNames"] == ["inventory"]
        assert set(rule["verbs"]) == verbs
    bindings = [item for item in resources if item["kind"] == "RoleBinding"]
    assert len(bindings) == 2
    for binding in bindings:
        name = binding["metadata"]["name"]
        assert binding["metadata"]["namespace"] == "autonomy-lab"
        assert binding["subjects"] == [{"kind": "ServiceAccount", "name": name, "namespace": "autonomy-lab"}]
        assert binding["roleRef"] == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": name}


def test_application_pods_never_receive_automatic_or_projected_service_account_tokens(resources):
    pods = [item["spec"]["template"]["spec"] for item in resources if item["kind"] == "Deployment"]
    assert len(pods) == 3
    for pod in pods:
        assert pod["automountServiceAccountToken"] is False
        assert pod.get("serviceAccountName") not in {"broker", "verifier"}
        for volume in pod.get("volumes", []):
            assert all("serviceAccountToken" not in source for source in volume.get("projected", {}).get("sources", []))
    for account in (item for item in resources if item["kind"] == "ServiceAccount"):
        assert account["automountServiceAccountToken"] is False


def test_manifest_preserves_supplied_image_digests(resources):
    for deployment in (item for item in resources if item["kind"] == "Deployment"):
        expected = "unit.invalid/postgres@sha256:" + "2" * 64 if deployment["metadata"]["name"] == "postgres" else "unit.invalid/app@sha256:" + "1" * 64
        assert deployment["spec"]["template"]["spec"]["containers"][0]["image"] == expected


def test_application_db_identity_has_only_declared_read_privileges(resources):
    secret = next(item for item in resources if item["kind"] == "Secret" and item["metadata"]["name"] == "database")
    inventory = next(item for item in resources if item["kind"] == "Deployment" and item["metadata"]["name"] == "inventory")
    env = inventory["spec"]["template"]["spec"]["containers"][0]["env"]
    assert env == [{"name": "DATABASE_URL", "valueFrom": {"secretKeyRef": {"name": "database", "key": "inventory-url"}}}]
    parsed = urlparse(secret["stringData"]["inventory-url"])
    assert parsed.username == "inventory_reader"
    assert parsed.hostname == "postgres"
    assert parsed.path == "/lab"
    quote = next(item for item in resources if item["kind"] == "Deployment" and item["metadata"]["name"] == "quote")
    assert all(item["name"] != "DATABASE_URL" for item in quote["spec"]["template"]["spec"]["containers"][0]["env"])

    sql = next(item for item in resources if item["kind"] == "ConfigMap")["data"]["init.sql"]
    statements = [statement.strip() for statement in re.sub(r"--[^\n]*", "", sql).split(";") if statement.strip()]
    for role in ("inventory_reader", "verifier_reader"):
        creation = next(statement for statement in statements if re.match(rf"CREATE ROLE {role}\b", statement, re.IGNORECASE))
        assert not re.search(r"\b(SUPERUSER|CREATEDB|CREATEROLE|REPLICATION|BYPASSRLS|ADMIN)\b|\bIN\s+(ROLE|GROUP)\b", creation, re.IGNORECASE)
        grants = [statement for statement in statements if re.match(r"GRANT\b", statement, re.IGNORECASE) and role in statement]
        assert grants
        assert all(re.match(r"GRANT (SELECT|CONNECT|USAGE) ON\b", statement, re.IGNORECASE) for statement in grants)
        assert any(re.match(r"GRANT SELECT ON TABLE products TO\b", statement, re.IGNORECASE) for statement in grants)


@pytest.mark.parametrize("cluster", [
    "docker-desktop", "kind-production", "gke-project-region-production", "production",
    "autolab-production", "autolab-deadbeef-other", "autolab-0000000g", "autolab-DEADBEEF",
    "autolab-0000000", "autolab-deadbeef\n", "--context=production",
])
def test_kubernetes_constructor_rejects_arbitrary_cluster_names(tmp_path, cluster):
    with pytest.raises(ValueError, match="Autonomy Lab cluster"):
        Kubernetes(tmp_path / "kubeconfig", cluster)


def test_kubernetes_commands_explicitly_select_lab_kubeconfig_context_and_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "unrelated-production-config"))
    config = tmp_path / "lab-kubeconfig"
    arguments = Kubernetes(config, "autolab-deadbeef").args("get", "service", "inventory")
    assert arguments[arguments.index("--kubeconfig") + 1] == str(config.resolve())
    assert arguments[arguments.index("--context") + 1] == "kind-autolab-deadbeef"
    assert arguments[arguments.index("--namespace") + 1] == "autonomy-lab"
    assert str(tmp_path / "unrelated-production-config") not in arguments


def test_service_access_rejects_out_of_scope_namespace_before_io(tmp_path):
    kube = Kubernetes(tmp_path / "nonexistent-kubeconfig", "autolab-deadbeef")
    with pytest.raises(ValueError, match="namespace outside"):
        kube.get_service("default", "inventory")
    with pytest.raises(PatchRejected, match="namespace_out_of_scope"):
        kube.patch_service("default", "inventory", [])


class IdentityController:
    cluster_name = "autolab-deadbeef"

    def __init__(self):
        self.calls = []

    def call(self, *args):
        self.calls.append(args)
        if args[:2] == ("config", "view"):
            return yaml.safe_dump({
                "clusters": [{"name": "unit-cluster", "cluster": {"server": "https://127.0.0.1:6443"}}],
                "contexts": [{"name": "kind-autolab-deadbeef", "context": {"cluster": "unit-cluster", "user": "admin"}}],
                "users": [{"name": "admin", "user": {"client-key-data": "unit-admin-private-key"}}],
            })
        if args[:2] == ("create", "token"):
            return "unit-service-account-token\n"
        pytest.fail("unexpected controller request")


@pytest.mark.parametrize("identity", ["broker", "verifier"])
def test_service_identity_replaces_admin_credentials_and_secures_existing_file(tmp_path, identity):
    path = tmp_path / f"{identity}-kubeconfig"
    path.write_text("unit-previous-content")
    path.chmod(0o644)
    controller = IdentityController()
    result = environment.service_identity(controller, tmp_path, identity)
    assert result.kubeconfig == path.resolve()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    config = yaml.safe_load(path.read_text())
    assert config["users"] == [{"name": identity, "user": {"token": "unit-service-account-token"}}]
    assert all(item["context"]["user"] == identity for item in config["contexts"])
    assert "unit-admin-private-key" not in path.read_text()
    assert ("create", "token", identity, "--duration=1h") in controller.calls


def test_unknown_service_identity_is_rejected_before_credential_io(tmp_path):
    controller = IdentityController()
    with pytest.raises(ValueError, match="Unknown lab identity"):
        environment.service_identity(controller, tmp_path, "cluster-admin")
    assert controller.calls == []
    assert list(tmp_path.iterdir()) == []


def test_invalid_run_id_is_rejected_before_provisioning_commands(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid run ID must fail before invoking cluster commands")

    monkeypatch.setattr(environment, "command", unexpected)
    with pytest.raises(ValueError, match="Autonomy Lab cluster"):
        environment.provision(tmp_path, "production")
    assert not (tmp_path / "environment.json").exists()


def test_teardown_refuses_non_lab_cluster_before_delete(tmp_path, monkeypatch):
    (tmp_path / "environment.json").write_text(json.dumps({"cluster": "production"}))

    def unexpected(*args, **kwargs):
        pytest.fail("must not issue deletion for a non-lab cluster")

    monkeypatch.setattr(environment, "command", unexpected)
    with pytest.raises(ValueError, match="Autonomy Lab cluster"):
        environment.teardown(tmp_path)
