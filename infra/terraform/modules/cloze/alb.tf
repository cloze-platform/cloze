# HTTPS entry point. TLS terminates at the ALB with an ACM certificate.
#
# Two-step rollout (see var.enable_https):
#   1. enable_https = false: the certificate is requested and its DNS validation
#      records are output. Port 80 answers 503 "not ready"; nothing is served.
#   2. Add those records at the DNS host. Once the certificate is "Issued", set
#      enable_https = true: adds the HTTPS listener and the web service, and port
#      80 starts redirecting to HTTPS.

resource "aws_acm_certificate" "app" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Waits for the certificate to be issued. Only declared once DNS is in place;
# otherwise the apply would hang for the validation timeout.
resource "aws_acm_certificate_validation" "app" {
  count           = var.enable_https ? 1 : 0
  certificate_arn = aws_acm_certificate.app.arn
}

resource "aws_lb" "main" {
  name               = var.name
  load_balancer_type = "application"
  internal           = false
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]

  drop_invalid_header_fields = true
  idle_timeout               = 120 # LLM responses can take a while
}

resource "aws_lb_target_group" "web" {
  name        = "${var.name}-web"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  protocol    = "HTTP"
  port        = var.container_port

  deregistration_delay = 30

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = var.enable_https ? "redirect" : "fixed-response"

    dynamic "redirect" {
      for_each = var.enable_https ? [1] : []
      content {
        protocol    = "HTTPS"
        port        = "443"
        status_code = "HTTP_301"
      }
    }

    dynamic "fixed_response" {
      for_each = var.enable_https ? [] : [1]
      content {
        content_type = "text/plain"
        message_body = "Not ready yet."
        status_code  = "503"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.app[0].certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
