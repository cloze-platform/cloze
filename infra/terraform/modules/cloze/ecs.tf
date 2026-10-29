# Two task definitions on the same image:
#   web   - the app, as the restricted database user. The service only exists
#           once HTTPS is on, but one-off tasks can run it before then.
#   admin - one-off tasks as the database owner: init-production by default,
#           or migrations (see the README).

resource "aws_ecs_cluster" "main" {
  name = var.name

  # Record what happens in ECS Exec sessions; CloudTrail only shows that one started.
  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name     = aws_cloudwatch_log_group.exec.name
        cloud_watch_encryption_enabled = true
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "exec" {
  name              = "/${var.name}/exec"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/${var.name}/web"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_cloudwatch_log_group" "admin" {
  name              = "/${var.name}/admin"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

locals {
  image = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  environment = merge(
    {
      FLASK_ENV             = "production"
      PYTHONUNBUFFERED      = "1"
      CLOZE_PUBLIC_URL      = "https://${var.domain_name}"
      AWS_SES_REGION        = var.region
      CLOZE_REPORTS_ENABLED = tostring(var.reports_enabled)
    },
    var.guard_sender_email == "" ? {} : { CLOZE_GUARD_SENDER = var.guard_sender_email },
    length(var.theme) == 0 ? {} : { CLOZE_THEME = jsonencode(var.theme) },
    var.extra_environment,
  )

  container_common = {
    image     = local.image
    essential = true
    # ECS wants lists of {name, value}.
    environment = [for k in sort(keys(local.environment)) : { name = k, value = local.environment[k] }]
    # Required for ECS Exec.
    linuxParameters = { initProcessEnabled = true }
  }
}

# --- Web -----------------------------------------------------------------------

resource "aws_ecs_task_definition" "web" {
  family                   = "${var.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.web_cpu
  memory                   = var.web_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container_common, {
    name         = "web"
    secrets      = [for k in sort(keys(local.container_secrets)) : { name = k, valueFrom = local.container_secrets[k] }]
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.web.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "web"
      }
    }
  }, var.web_command == null ? {} : { command = var.web_command })])
}

resource "aws_ecs_task_definition" "admin" {
  family                   = "${var.name}-admin"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.web_cpu
  memory                   = var.web_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container_common, {
    name    = "admin"
    command = ["python", "manage.py", "init-production"]
    secrets = [for k in sort(keys(local.admin_container_secrets)) : { name = k, valueFrom = local.admin_container_secrets[k] }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.admin.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "admin"
      }
    }
  })])
}

resource "aws_ecs_service" "web" {
  count           = var.enable_https ? 1 : 0
  name            = "web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = var.web_desired_count
  launch_type     = "FARGATE"

  enable_execute_command = true
  propagate_tags         = "SERVICE"

  # Startup is slow (NLP imports, LLM clients).
  health_check_grace_period_seconds = 120

  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = var.container_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https]
}
