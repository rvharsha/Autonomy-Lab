"""Install project-local, checksum-verified Kubernetes tools; never alter global config."""

import hashlib
import json
import platform
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIND_HASHES = {
    "darwin-arm64": "0c8c7dbe5e23594a198b786c4bc13dacc101fa6196b0cb0b23a1ca44e61f4b4f",
    "darwin-amd64": "5a99f26f57246dc9319dd294803313197a0f34d33c525b3ea8b655db5916ece0",
    "linux-arm64": "20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2",
    "linux-amd64": "aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d",
}


def download(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def install(name, url, expected):
    target = ROOT / ".tools" / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        print(f"{name}: checksum verified")
        return
    content = download(url)
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError(f"{name}: checksum mismatch")
    temporary = target.with_suffix(".download")
    temporary.write_bytes(content)
    temporary.chmod(0o755)
    temporary.replace(target)
    print(f"{name}: installed and checksum verified")


def main():
    config = json.loads((ROOT / "infra/toolchain.json").read_text())
    operating_system = platform.system().lower()
    architecture = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    host = f"{operating_system}-{architecture}"
    if host not in KIND_HASHES:
        raise RuntimeError(f"Unsupported platform: {host}")
    (ROOT / ".tools").mkdir(exist_ok=True)
    install(
        "kind",
        f"https://github.com/kubernetes-sigs/kind/releases/download/{config['kind_version']}/kind-{host}",
        KIND_HASHES[host],
    )
    kubectl_url = f"https://dl.k8s.io/release/{config['kubectl_version']}/bin/{operating_system}/{architecture}/kubectl"
    expected = config.get(f"kubectl_{operating_system}_{architecture}_sha256")
    if expected is None:
        expected = download(kubectl_url + ".sha256").decode().strip()
    install("kubectl", kubectl_url, expected)


if __name__ == "__main__":
    main()
