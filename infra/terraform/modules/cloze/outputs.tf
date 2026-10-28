output "certificate_validation_records" {
  description = "Add these at the DNS host (on Cloudflare: DNS only, not proxied) so ACM can issue the certificate."
  value = [
    for o in aws_acm_certificate.app.domain_validation_options : {
      type  = o.resource_record_type
      name  = o.resource_record_name
      value = o.resource_record_value
    }
  ]
}

output "certificate_status" {
  description = "PENDING_VALIDATION until the DNS records are in place, then ISSUED."
  value       = aws_acm_certificate.app.status
}

output "load_balancer_dns_name" {
  description = "Point the app hostname at this (CNAME)."
  value       = aws_lb.main.dns_name
}

output "ecr_repository_url" {
  description = "Where the build project pushes images, tagged with the git commit SHA."
  value       = aws_ecr_repository.app.repository_url
}

output "build_project_name" {
  description = "Build an image with `aws codebuild start-build --project-name <this>` (see the README)."
  value       = aws_codebuild_project.image.name
}

output "nat_public_ips" {
  description = "Outbound IPs of the app (for allowlists at LLM providers, if needed)."
  value       = aws_eip.nat[*].public_ip
}

output "secrets_to_set_by_hand" {
  description = "SSM parameters created with a placeholder; set the real values with `aws ssm put-parameter --overwrite`."
  value       = [for p in aws_ssm_parameter.external : p.name]
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "db_endpoint" {
  description = "Only reachable from inside the VPC (e.g. via ECS Exec)."
  value       = aws_db_instance.main.endpoint
}

output "web_log_group" {
  value = aws_cloudwatch_log_group.web.name
}

# For one-off tasks with `aws ecs run-task` (see the README).
output "web_task_definition" {
  value = aws_ecs_task_definition.web.family
}

output "admin_task_definition" {
  value = aws_ecs_task_definition.admin.family
}

output "app_subnet_ids" {
  value = aws_subnet.app[*].id
}

output "app_security_group_id" {
  value = aws_security_group.app.id
}
