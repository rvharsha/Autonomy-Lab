# GCP lab host

Deployment target: project `autonomy-lab-509518`, region `us-central1`, zone
`us-central1-a`. This runs the existing kind/Docker experiment harness on one
Compute Engine host. It is a CLI research environment; it does not introduce a
public web service, GKE adapter, or a claim that the local ARM64 AX variant works
on GCP.

The host is deployed and validated on source `a5e1912`.
The [selected deployment evidence](../../docs/validation/gcp-deployment.json)
retains the initial four infrastructure errors and the separately declared
corrected run (4/4 supported completions). These known-family
smoke cases do not establish production reliability.

## Resources and access

- One `e2-standard-4` VM: 4 vCPU, 16 GiB RAM, an 80 GiB balanced persistent boot
  disk, pinned Ubuntu image, and checksum-verified uv 0.9.3. Signed Ubuntu package
  updates supply Docker and Python; installed versions are recorded on the host.
- One dedicated VPC and subnet. Ingress permits TCP 22 only from Google's IAP
  forwarding range. There are no public application ports. An ephemeral external
  address supplies outbound package/image/model access; it is not a public SSH
  grant. OS Login controls administrative access.
- No attached service account or workload Google API credentials. The host and
  its administrators remain trusted; membership of the Docker group is
  effectively host-root authority. Model agents retain the existing separate,
  nonroot, network-disabled container boundary.
- GCE stops the VM after 12 hours from each start, with automatic restart
  disabled. This controller-independent limit survives local session loss.
  **Stopping does not delete the disk or stop disk charges.** The disk is also
  retained on explicit VM deletion to preserve evidence. Both VM and disk have
  Terraform `prevent_destroy` guards; the disk is a separate tracked resource.
  Back it up before deliberately removing the guards and deleting it. This is
  not a strict total spending cap.

Google currently lists the us-central1 E2 VM at approximately $0.134/hour
(about $1.61 for 12 running hours), excluding disk, IP, network, and model costs.
Verify current prices for future runs. Sources: [VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose),
[IAP access](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding),
[VM time limits](https://docs.cloud.google.com/compute/docs/instances/limit-vm-runtime).

## Provision

Billing must be linked to the user's selected active account first. Terraform
does not choose a billing account or manage billing IAM. The operator needs
permission to enable APIs and create the declared resources; authenticated IAP
access and OS Login administrator access are also required. Every command must
select this project explicitly; do not change the global gcloud project.

From the repository root, with operator Application Default Credentials or an
ephemeral `GOOGLE_OAUTH_ACCESS_TOKEN` supplied through the process environment:

```sh
umask 077
mkdir -p .state/gcp
export TF_DATA_DIR="$PWD/.state/gcp/terraform-data"
terraform -chdir=infra/gcp init -input=false
terraform -chdir=infra/gcp validate
terraform -chdir=infra/gcp plan -out=../../.state/gcp/deploy.tfplan
terraform -chdir=infra/gcp apply ../../.state/gcp/deploy.tfplan
```

Inspect the concrete plan before applying. Existing names must not be adopted or
overwritten without checking ownership. Terraform state and plans stay in
`.state/gcp`, outside Git. Keep that state private and backed up. No secret belongs
in startup metadata, Terraform variables, plans, source, or published evidence.

Connect using:

```sh
gcloud compute ssh autonomy-lab --project=autonomy-lab-509518 \
  --zone=us-central1-a --tunnel-through-iap
```

Bootstrap creates the trusted controller account `autolab` with home
`/srv/autonomy-lab`. Wait for `/var/lib/autonomy-lab/bootstrap-ready`; absence means
setup is incomplete. Inspect `journalctl -u google-startup-scripts.service` for
failure. It installs tooling only and never starts experiments or model calls on
boot. Restarting the VM must not silently rerun paid trials.

The installed release is under `/srv/autonomy-lab/current`, pointing to a release
directory named for its source commit. After connecting, run the lab as
the dedicated controller account:

```sh
sudo -iu autolab
cd /srv/autonomy-lab/current
make demo
```

Each invocation creates new evidence and removes its owned trial cluster. Live
experiments additionally require a transient Gemini credential as described
below. The initial cloud smoke manifest declares the first deployment gate;
future executions are separate runs and must not replace its evidence.

## Install the release and validate

Transfer a `git archive` of the exact reviewed commit over IAP. This repository
is private: do not put GitHub tokens or personal Git credentials on the host.
Check the archive SHA-256 at both ends, extract into a new directory owned by
`autolab`, and record the commit and digest. Do not overlay a previous run's
evidence. Run `make setup`, then `make test lint` as `autolab` in that checkout.

The declared first-cloud gates are sequential:

1. Check the actual VM's project, image, network rules, absent service account,
   Secure Boot settings, disk, and 12-hour stop schedule through GCP APIs. Test
   IAP access and absence of host metadata service-account tokens. Do not infer
   these from the Terraform plan alone.
2. Run `make demo`: the existing 17 real Kubernetes acceptance checks, unchanged
   30-second recovery windows and owned-cluster
   deletion. This is model-free.
3. Run `PYTHONPATH=src .venv/bin/python scripts/check_agent_isolation.py` and
   `PYTHONPATH=src .venv/bin/python scripts/check_controller_death.py`. Require
   actual denied metadata/network/filesystem/credential access and detached
   cleanup after SIGKILL. Keep original failed outcomes.
4. On frozen source, run `scenarios/gcp-smoke.yaml` once: routing and lost-ack,
   both agent variants, four trials, at most 128,000 requested total tokens.
   Keep the 32,000-token trial target, 12 turns, requested output 2,048, 900-second
   deadline and 30-second verification. No retry, replacement, provider fallback,
   or prompt/budget tuning. Report every attempted/unrun trial and unknown usage.
   These are known-family cloud smoke cases, not a new reliability comparison.
5. Copy private run evidence back over IAP, verify hashes, delete the transient
   model key, and check no owned trial cluster/container remains. Reboot the host
   and verify saved journals/evidence hashes persist without automatically
   starting another trial. Preserve its on-demand readiness and 12-hour limit.

For the live gate, transfer only the Gemini credential recognized by the existing
loader from the authorized local env file. Use a temporary mode-0600 file owned
by `autolab` under `/run` on the host, pass its path with `--env-file`, and remove
it after the gate. Do not transfer the entire local `.env`, publish that key,
place it in instance metadata, or pass it on a command line. The decision
container receives no provider credential.

The host's persistent disk survives controller death and VM stop/restart; it is
not immutable evidence against a host administrator or a cross-region backup.
Selected reports must include source/manifest hashes, real cloud configuration,
failed and passing gates, usage, audit scope, cleanup, and remaining limitations.
Raw model responses, private thinking, credentials and kubeconfigs stay private.

## Native Linux audit correction

The initial `gcp-smoke` run on `e525612` completed agent work but could not score
trials because the root API server created `events.jsonl` as root-owned mode
0600. The nonroot controller received `PermissionError` during independent
auditing. These original outcomes remain infrastructure errors; later analysis
or passing runs must not replace them. The acceptance demo checks application
and broker behavior but does not parse the server audit stream; the new probe
adds the native Linux ownership and rotation coverage.

The correction precreates the private log as the controller before cluster
startup. The pinned Kubernetes logger preserves the existing owner, including
rotation ([backend source](https://github.com/kubernetes/kubernetes/blob/v1.35.8/staging/src/k8s.io/apiserver/pkg/server/options/audit.go),
[Linux rotation ownership](https://github.com/kubernetes/kubernetes/blob/v1.35.8/vendor/gopkg.in/natefinch/lumberjack.v2/chown_linux.go)).
Agent prompts, tool authority, scoring and budgets remain unchanged.

Before another model call, run `scripts/check_audit_permissions.py` as the
nonroot Linux controller. It provisions a real cluster, lowers only that probe's
rotation threshold to 1 MiB, generates actual Service reads, and requires current
and rotated logs to remain controller-owned, private and readable. It retains
its evidence and deletes its cluster. Also require tests, lint and isolation.

Then run `scenarios/gcp-audit-remediation.yaml` once on the frozen corrected
source: the same four known cases, seed and per-trial limits as the initial
smoke manifest, at most another 128,000 requested tokens. Keep every outcome,
including failures and unrun cases, with no retries, provider fallback, prompt
tuning or budget changes. Report the initial four and remedial four separately.
This is a deployment correction check, not a new reliability comparison.

## Executed deployment checks

- Tests and lint: 693 tests on the initial release; 694 on the correction, both
  on this GCP host. Exact corrected-source CI also passed all 17 real Kubernetes
  acceptance checks; the original cloud acceptance passed the same 17 checks.
- Agent isolation: all 15 real probes passed on both releases. Actual SIGKILL of
  the original cloud controller triggered detached deletion with no remaining
  cluster nodes.
- Native Linux rotation: 349 real Service reads triggered rotation; both
  log files retained controller UID 1001 and mode 0600. All 526 retained
  events parsed, with no malformed lines, and the probe cluster was deleted.
- Initial live run: all four cases remain unscored `infrastructure_error`
  outcomes caused by audit-log permissions (74,029 reported tokens).
  Corrective live run: 4/4 supported completions, four assessed clean scoped
  audits, 18 recorded generations, 70,499 reported tokens. Neither
  run had an unrun trial; both clusters were deleted.
- Private evidence was copied over IAP and hash-verified. A real VM stop/start
  changed its boot ID while preserving all 386 hashed evidence files across
  both releases. No cluster/container or temporary model credential remained,
  and no experiment restarted automatically.
- Five completed direct Fable reviews covered infrastructure, the ownership fix
  and the real rotation probe. [Findings and checked dispositions](../../docs/validation/gcp-deployment-reviews.json)
  retain the accepted fixes and the source snapshot for each review.

Only `audit.py` differs among the 39 frozen runtime files between the two cloud
releases. Agent prompts, scorer, broker, verifier and per-trial limits are
unchanged. The original failed trials were not rescored or replaced. The
installed checkout remains the tested source commit; subsequent report-only
commits do not require overwriting it.

## Operate and clean up

The later [fallback study](../../docs/RUNBOOK_FALLBACK_RESULTS.md) exposed a
different termination boundary: a systemd service stop/restart during unattended
package maintenance interrupted both the controller and its detached janitor.
The controller-only SIGKILL check above does not validate whole-service
termination. The original evidence was archived, the owned cluster was manually
deleted, and the VM was stopped. Before another live comparison, require a real
service-stop gate proving final accounting and cleanup survive independently of
the study's control group. Keep host maintenance and restoration explicit and
bounded; do not disable security updates indefinitely to make a run pass.

The proposed correction and separate validation are declared in
[SERVICE_RECOVERY_EXPERIMENT.md](../../docs/SERVICE_RECOVERY_EXPERIMENT.md).
Use the managed entry point for new cloud studies: prepare one manifest as
`autolab`, then launch that prepared job as the host administrator. For example,
from the exact staged checkout (replace the printed job path below):

```sh
sudo -u autolab env PYTHONPATH=src .venv/bin/python scripts/service_experiment.py prepare scenarios/runbook-fallback-validation.yaml
sudo env PYTHONPATH=src .venv/bin/python scripts/service_experiment.py launch /absolute/checkout/artifacts/service-PRINTED_ID
```

The wrapper uses `Restart=no`, `KillMode=control-group`, a bounded service runtime,
and systemd `ExecStopPost` recovery. A persistent launch claim prevents a restart
from replaying the study. Cleanup starts in the supervised post-stop phase after
the original processes terminate. This does not guarantee recovery after loss of
the host or systemd itself. The local detached janitor remains a separate,
narrower controller-death mechanism.

`post-stop-accounting.json` is explicitly derived accounting; it does not overwrite
original `trial.json`, `results.json`, `accounting.json` or `cleanup.json`. An
uncommitted worker result stays unassessed. `post-stop-started.json` records
credential removal before Docker work; only `post-stop.json` with status `finished`
establishes completed recovery. A missing final receipt is not success. If cleanup
fails, retain the original receipt and investigate owned resources before another
job. The existing raw exporter still requires original controller-final accounting.

For future live-model studies, supply `prepare --env-file` with a dedicated
`/run/autonomy-lab/.../provider.env`, following the credential-transfer restrictions
above. Never give this wrapper the reusable local `.env`: recovery removes the
declared transient file. If service creation fails before any start/stop phase,
the operator must remove that transient file. The declared fallback validation is
model-free and does not require a credential.

Use the same explicit project, zone, and IAP flags when restarting or accessing
the host. Starting it grants a new 12-hour run interval. Applications exist only
while a declared lab run provisions them; the VM is an on-demand experiment host.

```sh
gcloud compute instances stop autonomy-lab --project=autonomy-lab-509518 --zone=us-central1-a
gcloud compute instances start autonomy-lab --project=autonomy-lab-509518 --zone=us-central1-a
```

To remove infrastructure, first copy and verify the evidence and Terraform state.
Terraform refuses VM/disk destruction until their `prevent_destroy` guards are
deliberately removed. Review the resulting destroy plan before execution.
The disk remains separately tracked; do not delete it to work around a recreate
error. Image upgrades require a new disk resource and deliberate migration or a
verified snapshot/recreate procedure. Enabled APIs are left enabled; no project,
billing account, or unrelated infrastructure is removed.
