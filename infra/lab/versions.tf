terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "confidential-poc"
      Stack     = "lab"
      ManagedBy = "terraform"
    }
  }
}

# lab reads what it needs from base (instance profile, bucket) through base's local state file
data "terraform_remote_state" "base" {
  backend = "local"
  config = {
    path = "${path.module}/../base/terraform.tfstate"
  }
}
