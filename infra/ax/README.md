# Pinned local AX runtime

This macOS ARM64 launcher builds AX at
`d8ed0fe38bceb7842d3c47817d53d16ccdfcb601` and Substrate at
`672533541dbfcd29084e4de2475267088bda3651`. It uses checksum-verified Go/ko
archives and pinned images. Docker, the lab's Python environment, and its
pinned `kind`/`kubectl` tools must already be installed through the normal
repository setup.

From the repository root:

```sh
.venv/bin/python infra/ax/bootstrap.py
.venv/bin/python infra/ax/bootstrap.py --execute
.venv/bin/python infra/ax/bootstrap.py --execute --env-file ~/Dev/.env
```

Preparation builds tools without creating a cluster. `--execute` creates a
bounded local cluster, checks Substrate state restoration, and exercises three
AX data-resume cycles plus recovery from loss of worker capacity. Supplying an
environment file additionally runs a real Gemini agent with an external broker
and verifier. Model credentials remain on the host. Every execution retains
private evidence under `.state/ax-spike/logs/` and deletes its owned cluster and
registry. A detached janitor handles controller death. Existing lab resources
cause a preflight refusal rather than deletion.

The explicit local patches are:

- `cold-boot.patch`: reconstruct a fresh command from the image and restored
  durable files for DATA snapshots; retain upstream FULL snapshot behavior.
- `recovery.patch`: omit mutable lifecycle status from the runtime template
  identity and retry only explicit pre-assignment capacity rejections for a
  bounded interval. Resume does not create a new template each time.
- `privilege-drop.patch`: grant CHOWN/SETUID/SETGID only to the lab's
  `autonomy-agents` atespace so the trusted bootstrap can hand off its workspace
  and enter UID/GID 10001. The decision process drops all effective/permitted
  capabilities and installs a no-new-privileges, network-denying seccomp filter.
- `substrate-local.patch`: local ARM64 kind deployment adaptations.
- `durable-cleanup.patch` (deployment approval pending): give only the local
  trusted `atelet` service DAC_OVERRIDE to remove nonroot-owned durable files
  after snapshot capture. Its guest keeps zero capabilities. This broadens
  access to files available in atelet's existing mounts in the disposable
  kind node; it does not add a mount or grant this capability to the agent.

`source-manifest.json` records every expected source modification and rejects
unexpected changes. Build tests check stable templates and the capability
scope. Patches were reproduced from clean checkouts of the pinned commits;
that is separate from running the entire installer on a newly provisioned host.
Use a fresh deployment: AX reuses existing templates without migrating their
resume policy.

The three-cycle and worker-capacity recovery gate passed. Live agent integration
has a separate gate; see the current [runtime work record](../../docs/RUNTIME_ISOLATION_WORK.md).
The [AX runtime history](../../docs/AX_RUNTIME_STATUS.md) retains the original
upstream and earlier patched failures. This is a lab variant, not a claim that
unmodified AX passed. Source review is not runtime or merge approval.
