# Secrets live in SSM under /<name>/ and reach containers as environment
# variables. SECRET_KEY and DATABASE_URL are generated here, so they're also in
# Terraform state. API keys get a placeholder and are set by hand (see the
# README), so they never touch state or git.

locals {
  ssm_prefix = "/${var.name}"

  external_secret_names = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
  ]
}

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "secret_key" {
  name        = "${local.ssm_prefix}/SECRET_KEY"
  description = "Flask session signing key. Changing it logs everyone out."
  type        = "SecureString"
  key_id      = aws_kms_key.data.arn
  value       = random_password.secret_key.result
}

resource "aws_ssm_parameter" "database_url" {
  name        = "${local.ssm_prefix}/DATABASE_URL"
  description = "SQLAlchemy URL for the app database (TLS required)."
  type        = "SecureString"
  key_id      = aws_kms_key.data.arn
  value = format(
    "postgresql://%s:%s@%s/%s?sslmode=require",
    aws_db_instance.main.username,
    random_password.db.result,
    aws_db_instance.main.endpoint,
    aws_db_instance.main.db_name,
  )
}

resource "aws_ssm_parameter" "external" {
  for_each = toset(local.external_secret_names)

  name        = "${local.ssm_prefix}/${each.value}"
  description = "Set by hand; Terraform only creates the placeholder."
  type        = "SecureString"
  key_id      = aws_kms_key.data.arn
  value       = "unset"

  lifecycle {
    ignore_changes = [value]
  }
}

locals {
  # Name -> parameter ARN, for the container definitions.
  container_secrets = merge(
    {
      SECRET_KEY   = aws_ssm_parameter.secret_key.arn
      DATABASE_URL = aws_ssm_parameter.database_url.arn
    },
    { for k, p in aws_ssm_parameter.external : k => p.arn },
  )
}
