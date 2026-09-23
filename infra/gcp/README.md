# GCP lab host

Deployment target: project `autonomy-lab-509518`, region `us-central1`, zone
`us-central1-a`. This runs the existing kind/Docker experiment harness on one
Compute Engine host. It is a CLI research environment; it does not introduce a
public web service, GKE adapter, or a claim that the local ARM64 AX variant works
on GCP.

The first deployment is in preparation. No cloud execution result is implied by
Terraform validation or source review.

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
   30-second recovery windows, independent mutation audit, and owned-cluster
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

## Operate and clean up

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
