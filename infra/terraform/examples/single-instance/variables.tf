variable "instance" {
  description = "Short instance name, used in resource names (cloze-<instance>-...) and tags."
  type        = string
}

variable "aws_account_id" {
  description = "The 12-digit account this instance lives in. Terraform refuses to run against any other."
  type        = string
}

variable "aws_profile" {
  description = "Local AWS CLI profile with admin access to that account."
  type        = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "domain_name" {
  description = "Public hostname, e.g. cloze.example.org."
  type        = string
}

variable "enable_https" {
  description = "See enable_https in modules/cloze/variables.tf."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Image to run: the full git commit SHA the build project pushed."
  type        = string
  default     = "bootstrap"
}

variable "reports_enabled" {
  description = "Report generation (NLP analysis and AI summaries). False turns it off for the whole instance."
  type        = bool
  default     = true
}

variable "guard_sender_email" {
  description = "Cloze-Guard From address; leave empty until SES is verified and out of the sandbox."
  type        = string
  default     = ""
}
