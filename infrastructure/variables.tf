variable "aws_region" {
  description = "AWS region to deploy resources in."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment: dev, staging, or prod."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "aws_account_id" {
  description = "AWS account ID. Used to ensure globally unique bucket names."
  type        = string
}

variable "versioning_expiry_days" {
  description = "Days before non-current S3 object versions are permanently deleted."
  type        = number
  default     = 90
}

variable "ia_transition_days" {
  description = "Days before objects not accessed are moved to S3 Infrequent Access (lower cost)."
  type        = number
  default     = 90
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
