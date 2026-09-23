terraform {
  required_version = ">= 1.5.0, < 2.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.2.0"
    }
  }
  backend "local" {
    path = "../../.state/gcp/terraform.tfstate"
  }
}

variable "project_id" {
  type    = string
  default = "autonomy-lab-509518"
}

variable "region" {
  type    = string
  default = "us-central1"
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = "${var.region}-a"
}

resource "google_project_service" "api" {
  for_each           = toset(["compute.googleapis.com", "iap.googleapis.com", "oslogin.googleapis.com"])
  service            = each.key
  disable_on_destroy = false
}

resource "google_compute_network" "lab" {
  name                    = "autonomy-lab"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Dedicated Autonomy Lab network; no public application ingress."
  depends_on              = [google_project_service.api]
}

resource "google_compute_subnetwork" "lab" {
  name          = "autonomy-lab"
  ip_cidr_range = "10.42.0.0/24"
  network       = google_compute_network.lab.id
  region        = var.region
}

resource "google_compute_firewall" "iap_ssh" {
  name          = "autonomy-lab-iap-ssh"
  network       = google_compute_network.lab.name
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["autonomy-lab"]
  direction     = "INGRESS"
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  log_config {
    metadata = "EXCLUDE_ALL_METADATA"
  }
}

resource "google_compute_disk" "lab_boot" {
  name  = "autonomy-lab-boot"
  image = "ubuntu-os-cloud/ubuntu-2404-noble-amd64-v20260918"
  size  = 80
  type  = "pd-balanced"
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [google_project_service.api]
}

resource "google_compute_instance" "lab" {
  name         = "autonomy-lab"
  machine_type = "e2-standard-4"
  tags         = ["autonomy-lab"]
  labels       = { application = "autonomy-lab", purpose = "research" }

  boot_disk {
    # Keep the evidence disk tracked and reusable across deliberate VM replacement.
    source      = google_compute_disk.lab_boot.id
    auto_delete = false
  }
  lifecycle {
    prevent_destroy = true
  }
  network_interface {
    subnetwork = google_compute_subnetwork.lab.id
    # Outbound image/package/API access. Inbound SSH is restricted to IAP above.
    access_config {
      network_tier = "STANDARD"
    }
  }
  # Omitting service_account gives this host no Google API workload identity.
  metadata = {
    enable-oslogin           = "TRUE"
    block-project-ssh-keys   = "TRUE"
    serial-port-enable       = "FALSE"
    disable-legacy-endpoints = "TRUE"
  }
  metadata_startup_script = file("${path.module}/bootstrap.sh")
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  scheduling {
    automatic_restart           = false
    instance_termination_action = "STOP"
    max_run_duration {
      seconds = 43200
    }
  }
  depends_on = [google_project_service.api, google_compute_firewall.iap_ssh]
}

output "ssh_command" {
  value = "gcloud compute ssh autonomy-lab --project=${var.project_id} --zone=${var.region}-a --tunnel-through-iap"
}

output "instance_id" {
  value = google_compute_instance.lab.instance_id
}
