# Fargate services, both running the same image:
#   web    - gunicorn behind the ALB. Only created once HTTPS is on.
#   worker - `flask reports-worker` (optional, see var.enable_reports_worker).

resource "aws_ecs_cluster" "main" {
  name = var.name
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/${var.name}/web"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_cloudwatch_log_group" "worker" {
  count             = var.enable_reports_worker ? 1 : 0
  name              = "/${var.name}/worker"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

locals {
  image = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  environment = merge(
    {
      FLASK_ENV        = "production"
      PYTHONUNBUFFERED = "1"
      CLOZE_PUBLIC_URL = "https://${var.domain_name}"
      AWS_SES_REGION   = var.region
    },
    var.guard_sender_email == "" ? {} : { CLOZE_GUARD_SENDER = var.guard_sender_email },
    var.extra_environment,
  )

  # Shape shared by both containers; ECS wants lists of {name, value}.
  container_base = {
    image       = local.image
    essential   = true
    environment = [for k in sort(keys(local.environment)) : { name = k, value = local.environment[k] }]
    secrets     = [for k in sort(keys(local.container_secrets)) : { name = k, valueFrom = local.container_secrets[k] }]
    # Required for ECS Exec.
    linuxParameters = { initProcessEnabled = true }
  }

  runtime_platform = {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
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
    operating_system_family = local.runtime_platform.operating_system_family
    cpu_architecture        = local.runtime_platform.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container_base, {
    name         = "web"
    command      = var.web_command
    portMappings = [{ containerPort = var.container_port, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.web.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "web"
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

  # spaCy and the LLM clients load at startup; give the app time before the
  # ALB health check can fail it.
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

  # A deploy whose new tasks never become healthy is rolled back automatically.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https]
}

# --- Reports worker --------------------------------------------------------------

resource "aws_ecs_task_definition" "worker" {
  count                    = var.enable_reports_worker ? 1 : 0
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = local.runtime_platform.operating_system_family
    cpu_architecture        = local.runtime_platform.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container_base, {
    name    = "worker"
    command = var.worker_command
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker[0].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "worker"
      }
    }
  })])
}

resource "aws_ecs_service" "worker" {
  count           = var.enable_reports_worker ? 1 : 0
  name            = "reports-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  enable_execute_command = true
  propagate_tags         = "SERVICE"

  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}
