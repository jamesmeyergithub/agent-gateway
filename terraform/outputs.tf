output "tier1_agent_identity_principal" {
  description = "Google Cloud Agent Identity principal URI for Tier 1 Support Agent"
  value       = "principal://agentidentity.googleapis.com/projects/${var.project_id}/locations/global/agentIdentities/tier1-support-agent"
}

output "billing_agent_identity_principal" {
  description = "Google Cloud Agent Identity principal URI for Billing Specialist Agent"
  value       = "principal://agentidentity.googleapis.com/projects/${var.project_id}/locations/global/agentIdentities/billing-specialist"
}

output "mcp_backend_service_uri" {
  description = "Internal Cloud Run URI for backend MCP tools"
  value       = google_cloud_run_v2_service.mcp_backend.uri
}
