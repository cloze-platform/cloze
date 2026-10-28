# Root configuration for one Cloze instance. To start a new instance, copy this
# folder to instances/<your-instance>/ and fill in terraform.tfvars and
# backend.hcl from the .example files. Real values for both stay out of git.

terraform {
  required_version = ">= 1.10"

  # Partial configuration: bucket, key, region and profile come from backend.hcl.
  #   terraform init -backend-config=backend.hcl
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  # Terraform refuses to do anything if these credentials belong to any other
  # account. This is the guard against applying to the wrong place.
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project   = "cloze"
      Instance  = var.instance
      ManagedBy = "terraform"
    }
  }
}

module "cloze" {
  source = "../../modules/cloze"

  name        = "cloze-${var.instance}"
  region      = var.region
  domain_name = var.domain_name

  enable_https          = var.enable_https
  image_tag             = var.image_tag
  enable_reports_worker = var.enable_reports_worker
  guard_sender_email    = var.guard_sender_email
}

output "cloze" {
  value = module.cloze
}
