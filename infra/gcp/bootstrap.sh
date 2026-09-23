#!/bin/bash
# Host tooling only. No credentials, repository tokens, model calls or autorun.
set -euo pipefail
umask 027
exec 9>/run/autonomy-lab-bootstrap.lock
flock -n 9 || exit 0
if test -f /var/lib/autonomy-lab/bootstrap-ready; then
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
timeout 600 apt-get -o DPkg::Lock::Timeout=120 update
timeout 900 apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends \
  ca-certificates curl docker.io git make python3 python3-venv
systemctl enable --now docker

temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 --max-time 180 \
  https://github.com/astral-sh/uv/releases/download/0.9.3/uv-x86_64-unknown-linux-gnu.tar.gz \
  --output "$temporary/uv.tar.gz"
(
  cd "$temporary"
  printf '%s  uv.tar.gz\n' 4d6f84490da4b21bb6075ffc1c6b22e0cf37bc98d7cca8aff9fbb759093cdc23 | sha256sum --check
)
tar -xzf "$temporary/uv.tar.gz" -C "$temporary"
install -o root -g root -m 0755 "$temporary/uv-x86_64-unknown-linux-gnu/uv" /usr/local/bin/uv

if ! id autolab >/dev/null 2>&1; then
  useradd --create-home --home-dir /srv/autonomy-lab --shell /bin/bash autolab
fi
usermod -aG docker autolab
chmod 0750 /srv/autonomy-lab
install -d -o root -g root -m 0755 /var/lib/autonomy-lab
dpkg-query -W docker.io python3 python3-venv > /var/lib/autonomy-lab/host-packages.txt
uv --version > /var/lib/autonomy-lab/uv-version.txt
date --iso-8601=seconds > /var/lib/autonomy-lab/bootstrap-ready
