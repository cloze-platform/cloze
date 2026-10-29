# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

variable "name" {
  description = "Prefix for every resource name, e.g. \"cloze-acme\". Lowercase letters, digits and hyphens."
  type        = string

  validation {
    # The longest derived name is the target group "<name>-web", and AWS caps those at 32.
    condition     = can(regex("^[a-z][a-z0-9-]{2,27}$", var.name))
    error_message = "name must be 3-28 chars of lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  description = "AWS region everything is created in."
  type        = string
}

variable "domain_name" {
  description = "Public hostname for the app, e.g. \"cloze.example.org\". Also the SES sending domain."
  type        = string
}

# ---------------------------------------------------------------------------
# Rollout switches
# ---------------------------------------------------------------------------

variable "enable_https" {
  description = "False on the first apply, which requests the certificate and outputs its DNS validation records. Set true once it's issued: this adds the HTTPS listener and starts the web service."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Commit SHA of the image to run, as pushed to ECR by the build project."
  type        = string
  default     = "bootstrap"
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block for the VPC. Pick one that won't clash if you ever peer with another network."
  type        = string
  default     = "10.40.0.0/16"
}

variable "nat_gateway_per_az" {
  description = "One NAT gateway per AZ (survives an AZ outage, ~2x NAT cost) instead of a single shared one."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

variable "db_engine_version" {
  description = "PostgreSQL major version. Minor versions are upgraded automatically in the maintenance window."
  type        = string
  default     = "17"

  validation {
    # The app's restricted database user relies on PostgreSQL 15+ schema defaults.
    condition     = can(tonumber(var.db_engine_version)) && tonumber(var.db_engine_version) >= 15
    error_message = "db_engine_version must be a major version, 15 or later."
  }
}

variable "db_instance_class" {
  description = "RDS instance size."
  type        = string
  default     = "db.t4g.small"
}

variable "db_allocated_storage_gb" {
  description = "Initial storage. Grows automatically up to db_max_allocated_storage_gb."
  type        = number
  default     = 20
}

variable "db_max_allocated_storage_gb" {
  description = "Ceiling for storage autoscaling."
  type        = number
  default     = 100
}

variable "db_multi_az" {
  description = "Keep a standby replica in a second AZ with automatic failover (~2x database cost)."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  description = "Days of automated backups / point-in-time recovery (max 35)."
  type        = number
  default     = 14
}

variable "db_deletion_protection" {
  description = "Block deletion of the database. Must be set false (and applied) before the database can be destroyed."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------

variable "cpu_architecture" {
  description = "ARM64 (Graviton, ~20% cheaper) or X86_64."
  type        = string
  default     = "ARM64"

  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "cpu_architecture must be ARM64 or X86_64."
  }
}

variable "container_port" {
  description = "Port gunicorn listens on inside the container."
  type        = number
  default     = 8000
}

variable "health_check_path" {
  description = "Path the load balancer polls; must return 200 without logging in."
  type        = string
  default     = "/healthz"
}

variable "web_cpu" {
  description = "Fargate CPU units for one web task (1024 = 1 vCPU)."
  type        = number
  default     = 1024
}

variable "web_memory" {
  description = "Fargate memory (MiB) for one web task."
  type        = number
  default     = 2048
}

variable "web_desired_count" {
  description = "Number of web tasks. Keep at 1 until the in-process report scheduler is moved out of the web app."
  type        = number
  default     = 1
}

variable "web_command" {
  description = "Override the image's command (gunicorn; see the Dockerfile)."
  type        = list(string)
  default     = null
}

# ---------------------------------------------------------------------------
# Image build
# ---------------------------------------------------------------------------

variable "source_repository" {
  description = "Public git repository the build project clones."
  type        = string
  default     = "https://github.com/cloze-platform/cloze.git"
}

# ---------------------------------------------------------------------------
# App settings
# ---------------------------------------------------------------------------

variable "llm_providers" {
  description = "LLM providers the instance uses: any of openai, anthropic, google. Only their API keys are created and passed to the app."
  type        = set(string)

  validation {
    condition     = length(var.llm_providers) > 0 && length(setsubtract(var.llm_providers, ["openai", "anthropic", "google"])) == 0
    error_message = "llm_providers must list at least one of openai, anthropic, google."
  }
}

variable "reports_enabled" {
  description = "Report generation (NLP analysis and AI summaries). False turns it off instance-wide, overriding admin and provider settings."
  type        = bool
  default     = true
}

variable "theme" {
  description = "Instance colours (#RRGGBB) overriding any of the Cloze palette: primary, hover, accent, tint, on_dark, on_dark_hover, dark_page, dark_sidebar, dark_card, dark_raised, dark_border. See llm_chat/theme.py."
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for k, v in var.theme : contains(["primary", "hover", "accent", "tint", "on_dark", "on_dark_hover", "dark_page", "dark_sidebar", "dark_card", "dark_raised", "dark_border"], k) && can(regex("^#[0-9A-Fa-f]{6}$", v))])
    error_message = "theme keys must be Cloze palette names (see the description) and values #RRGGBB colours."
  }
}

variable "guard_sender_email" {
  description = "From address for Cloze-Guard alerts (must be on the verified SES domain). Empty disables alert emails."
  type        = string
  default     = ""
}

variable "extra_environment" {
  description = "Additional non-secret environment variables for the app containers."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps container logs. Logs can contain participant identifiers."
  type        = number
  default     = 365
}
