# Secrets live in SSM under /<name>/ and reach containers as environment
# variables. SECRET_KEY and the database URLs are generated here, so they're also
# in Terraform state. Each of var.llm_providers gets an API key placeholder that is
# set by hand (see the README), so the keys never touch state or git. Providers
# not listed get no key at all, which the app reads as "not configured".

locals {
  ssm_prefix = "/${var.name}"

  api_key_names = {
    openai    = "OPENAI_API_KEY"
    anthropic = "ANTHROPIC_API_KEY"
    google    = "GOOGLE_API_KEY"
  }
  external_secret_names = [for p in var.llm_providers : local.api_key_names[p]]
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
  description = "The app's database connection, as the restricted cloze_app user (TLS, server certificate verified)."
  type        = "SecureString"
  key_id      = aws_kms_key.data.arn
  value = format(
    "postgresql://%s:%s@%s/%s?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem",
    "cloze_app",
    random_password.db_app.result,
    aws_db_instance.main.endpoint,
    aws_db_instance.main.db_name,
  )
}

resource "aws_ssm_parameter" "database_owner_url" {
  name        = "${local.ssm_prefix}/DATABASE_OWNER_URL"
  description = "The database owner's connection, for setup and migrations only."
  type        = "SecureString"
  key_id      = aws_kms_key.data.arn
  value = format(
    "postgresql://%s:%s@%s/%s?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem",
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

  # The admin task connects as the owner, and init-production reads the app
  # user's URL to create that user.
  admin_container_secrets = merge(local.container_secrets, {
    DATABASE_URL           = aws_ssm_parameter.database_owner_url.arn
    CLOZE_APP_DATABASE_URL = aws_ssm_parameter.database_url.arn
  })
}
