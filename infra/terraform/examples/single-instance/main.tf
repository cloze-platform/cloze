# Example root config for one instance. Copy the .example files to
# terraform.tfvars and backend.hcl (both gitignored) and fill them in.
#
# A long-lived instance belongs in its own private repo, with the module pinned
# to a release:
#   source = "git::https://github.com/cloze-platform/cloze.git//infra/terraform/modules/cloze?ref=v0.5.0"

terraform {
  required_version = ">= 1.10"

  # Settings come from backend.hcl: terraform init -backend-config=backend.hcl
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

  # Refuse to run against any other account.
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

  enable_https       = var.enable_https
  image_tag          = var.image_tag
  reports_enabled    = var.reports_enabled
  guard_sender_email = var.guard_sender_email
}

output "cloze" {
  value = module.cloze
}
