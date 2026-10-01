# ==============================================================================
# ARCHITECTURAL REFERENCE ONLY
# ------------------------------------------------------------------------------
# This Terraform configuration serves as a conceptual architectural template.
# It is NOT used for live deployment. 
#
# To deploy the live, functional Google Cloud Agent Gateway & Agent Platform demo,
# use the turnkey deployment script:
#   ./scripts/deploy_gcp.sh --project YOUR_PROJECT_ID --region us-west1
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# 1. Enable Required Google Cloud & Agent Platform APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "aiplatform.googleapis.com",              # Vertex AI & Agent Platform Runtime
    "iam.googleapis.com",                     # Google Cloud IAM
    "cloudresourcemanager.googleapis.com",    # Resource Manager
    "logging.googleapis.com",                 # Cloud Audit Logging
    "run.googleapis.com"                      # Cloud Run (for backend MCP microservices)
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# ==============================================================================
# 2. Custom IAM Roles for Granular Agent-to-Tool & Agent-to-Service Governance
# ==============================================================================

# 2a. Support Viewer Role (Tier 1 Support Agents)
resource "google_project_iam_custom_role" "support_viewer" {
  role_id     = "agentgateway.supportViewer"
  title       = "Agent Gateway Support Viewer"
  description = "Allows calling read-only customer and order inquiry tools via Agent Gateway"
  permissions = [
    "aiplatform.endpoints.predict",
    "logging.logEntries.create"
  ]
}

# 2b. Billing Admin Role (Billing Specialist Agents)
resource "google_project_iam_custom_role" "billing_admin" {
  role_id     = "agentgateway.billingAdmin"
  title       = "Agent Gateway Billing Administrator"
  description = "Allows calling read tools and financial refund tools via Agent Gateway"
  permissions = [
    "aiplatform.endpoints.predict",
    "logging.logEntries.create"
  ]
}

# ==============================================================================
# 3. Agent Platform: Agent Identity IAM Bindings
# In Google Cloud Agent Platform, agents are first-class principals identified by
# Agent Identities (SPIFFE standard):
#   principal://agentidentity.googleapis.com/projects/<PROJECT>/locations/global/agentIdentities/<AGENT_ID>
# ==============================================================================

# Bind Tier 1 Support Agent Identity to Support Viewer Role
resource "google_project_iam_member" "tier1_agent_binding" {
  project = var.project_id
  role    = google_project_iam_custom_role.support_viewer.id
  member  = "principal://agentidentity.googleapis.com/projects/${var.project_id}/locations/global/agentIdentities/tier1-support-agent"

  depends_on = [google_project_iam_custom_role.support_viewer]
}

# Bind Billing Specialist Agent Identity to Billing Admin Role
resource "google_project_iam_member" "billing_agent_binding" {
  project = var.project_id
  role    = google_project_iam_custom_role.billing_admin.id
  member  = "principal://agentidentity.googleapis.com/projects/${var.project_id}/locations/global/agentIdentities/billing-specialist"

  depends_on = [google_project_iam_custom_role.billing_admin]
}

# ==============================================================================
# 4. Backend MCP Services (Running in Private Network behind Agent Gateway)
# ==============================================================================
resource "google_service_account" "mcp_service_sa" {
  account_id   = "mcp-backend-service"
  display_name = "Backend MCP Tools Service Account"
  description  = "Service identity for backend MCP tool microservices"
}

resource "google_cloud_run_v2_service" "mcp_backend" {
  name     = "mcp-tools-service"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY" # Isolated from public internet; reachable ONLY via Agent Gateway

  template {
    service_account = google_service_account.mcp_service_sa.email

    containers {
      image = "gcr.io/${var.project_id}/mcp-tools:latest"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "1Gi"
        }
      }
    }
  }

  depends_on = [google_project_service.required_apis]
}

# ==============================================================================
# 5. Native Google Cloud Agent Gateway & VPC Egress (Gemini Enterprise Platform)
# ==============================================================================
resource "google_compute_subnetwork" "agent_gateway_subnet" {
  name                     = "gateway-agent-gateway-subnet-west1"
  ip_cidr_range            = "10.30.0.0/28"
  region                   = var.region
  network                  = "gateway-vpc"
  private_ip_google_access = true
  depends_on               = [google_project_service.required_apis]
}

resource "google_compute_router" "agent_gateway_router" {
  name       = "gateway-nat-router-west1"
  region     = var.region
  network    = "gateway-vpc"
  depends_on = [google_compute_subnetwork.agent_gateway_subnet]
}

resource "google_compute_router_nat" "agent_gateway_nat" {
  name                               = "gateway-nat-gateway-west1"
  router                             = google_compute_router.agent_gateway_router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_network_attachment" "agent_gateway_na" {
  name                  = "agent-gateway-na-west1"
  region                = var.region
  subnetworks           = [google_compute_subnetwork.agent_gateway_subnet.id]
  connection_preference = "ACCEPT_AUTOMATIC"
}

resource "google_network_services_agent_gateway" "agent_gateway" {
  provider    = google-beta
  name        = "agent-gateway-vpc-west1"
  location    = var.region
  project     = var.project_id
  description = "Managed Agent Gateway with VPC Egress for us-west1"

  protocols = ["MCP"]

  google_managed {
    governed_access_path = "AGENT_TO_ANYWHERE"
  }

  network_config {
    egress {
      network_attachment = google_compute_network_attachment.agent_gateway_na.id
    }
  }

  registries = [
    "//agentregistry.googleapis.com/projects/${var.project_id}/locations/${var.region}"
  ]

  depends_on = [google_compute_network_attachment.agent_gateway_na]
}
