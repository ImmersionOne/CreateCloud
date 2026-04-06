terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment and configure once you have an S3 backend bucket + DynamoDB lock table.
  # backend "s3" {
  #   bucket         = "crat8cloud-tfstate-<account-id>"
  #   key            = "crat8cloud/<environment>/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "crat8cloud-tfstate-lock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Project     = "crat8cloud"
        Environment = var.environment
        ManagedBy   = "terraform"
      },
      var.tags,
    )
  }
}
