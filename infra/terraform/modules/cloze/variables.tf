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
  description = <<-EOT
    Leave false on the first apply. That apply creates the ACM certificate and outputs
    the DNS records needed to validate it. Once those records are in DNS and the
    certificate shows "Issued", set true: this adds the HTTPS listener and the web service.
    The app is never served over plain HTTP.
  EOT
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Tag of the image in this instance's ECR repository to run (we use the git commit SHA)."
  type        = string
  default     = "bootstrap"
}

variable "enable_reports_worker" {
  description = "Run the reports worker service (`flask reports-worker`). Only exists on branches with the v2 report system."
  type        = bool
  default     = false
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
  description = "ARM64 (Graviton, ~20% cheaper, native for Apple-silicon builds) or X86_64. Must match the pushed image."
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
  description = "Command the web container runs."
  type        = list(string)
  default = [
    "gunicorn", "--bind", "0.0.0.0:8000",
    "--workers", "2", "--threads", "4", "--timeout", "120",
    "--access-logfile", "-", "manage:app",
  ]
}

variable "worker_cpu" {
  description = "Fargate CPU units for the reports worker."
  type        = number
  default     = 1024
}

variable "worker_memory" {
  description = "Fargate memory (MiB) for the reports worker."
  type        = number
  default     = 2048
}

variable "worker_command" {
  description = "Command the reports worker container runs."
  type        = list(string)
  default     = ["flask", "--app", "manage:app", "reports-worker"]
}

# ---------------------------------------------------------------------------
# App settings
# ---------------------------------------------------------------------------

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
