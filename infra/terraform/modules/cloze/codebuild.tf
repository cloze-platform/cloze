# Builds the image from a commit on GitHub and pushes it to ECR, tagged with the
# full commit SHA. GIT_REF can be a branch, tag or SHA:
#
#   aws codebuild start-build --project-name <name>-image \
#     --environment-variables-override name=GIT_REF,value=<ref>

resource "aws_cloudwatch_log_group" "build" {
  name              = "/${var.name}/build"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_codebuild_project" "image" {
  name          = "${var.name}-image"
  description   = "Builds the Cloze image from ${var.source_repository} and pushes it to ECR"
  service_role  = aws_iam_role.build.arn
  build_timeout = 30

  source {
    type      = "NO_SOURCE"
    buildspec = <<-EOT
      version: 0.2
      env:
        shell: bash
        variables:
          GIT_REF: main
      phases:
        build:
          commands:
            - |
              set -euo pipefail
              git clone --quiet --filter=blob:none "$SOURCE_REPOSITORY" src
              cd src
              git checkout --quiet --detach "$GIT_REF" 2> /dev/null || git checkout --quiet --detach "origin/$GIT_REF"
              COMMIT="$(git rev-parse HEAD)"
              IMAGE="$IMAGE_REPOSITORY:$COMMIT"
              echo "Building $GIT_REF at $COMMIT"
              # Tags are immutable; skip commits already built.
              if aws ecr describe-images --repository-name "$ECR_REPOSITORY_NAME" --image-ids imageTag="$COMMIT" > /dev/null 2>&1; then
                echo "$IMAGE already exists; nothing to build."
                exit 0
              fi
              aws ecr get-login-password | docker login --username AWS --password-stdin "$${IMAGE_REPOSITORY%%/*}"
              docker build --tag "$IMAGE" .
              docker push "$IMAGE"
              echo "Pushed $IMAGE"
    EOT
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type            = var.cpu_architecture == "ARM64" ? "ARM_CONTAINER" : "LINUX_CONTAINER"
    image           = var.cpu_architecture == "ARM64" ? "aws/codebuild/amazonlinux-aarch64-standard:3.0" : "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    compute_type    = "BUILD_GENERAL1_SMALL"
    privileged_mode = true # required to run Docker

    environment_variable {
      name  = "SOURCE_REPOSITORY"
      value = var.source_repository
    }
    environment_variable {
      name  = "IMAGE_REPOSITORY"
      value = aws_ecr_repository.app.repository_url
    }
    environment_variable {
      name  = "ECR_REPOSITORY_NAME"
      value = aws_ecr_repository.app.name
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build.name
    }
  }
}

# --- Build role ----------------------------------------------------------------

data "aws_iam_policy_document" "build_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "build" {
  name               = "${var.name}-image-build"
  assume_role_policy = data.aws_iam_policy_document.build_assume.json
}

data "aws_iam_policy_document" "build" {
  statement {
    sid       = "WriteBuildLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.build.arn}:*"]
  }

  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "PushToThisInstanceRepository"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.app.arn]
  }
}

resource "aws_iam_role_policy" "build" {
  name   = "build-and-push"
  role   = aws_iam_role.build.id
  policy = data.aws_iam_policy_document.build.json
}
