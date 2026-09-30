variable "project_id" {
  description = "The Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "The Google Cloud region for deployment"
  type        = string
  default     = "us-west1"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "dev"
}
