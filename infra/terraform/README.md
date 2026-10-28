# Cloze on AWS: Terraform

This folder builds one complete Cloze instance inside a dedicated AWS account: network, database, container services, load balancer and HTTPS certificate.

- `modules/cloze/` is the reusable part.
- `instances/<name>/` is a thin per-instance wrapper. Its real values live in gitignored `terraform.tfvars` and `backend.hcl` files.

**Before using this, the account itself should be set up:** a dedicated account, a locked-down root user, an admin login inside the account, CloudTrail, account-level S3 Block Public Access, and default EBS encryption. If participant data will be stored, a BAA must also be accepted for the account. Terraform deliberately doesn't manage any of those.

## What it builds

```
                internet
                   │  80 → redirect, 443 (TLS 1.2+/1.3, ACM certificate)
           ┌───────▼────────┐
  public   │  Load balancer │        NAT gateway ──► internet (LLM APIs, SES, ECR)
           └───────┬────────┘              ▲
  app              │ :8000                 │
           ┌───────▼────────┐   ┌──────────┴────────┐
           │  web (Fargate) │   │ reports worker    │  (optional)
           │  gunicorn      │   │ (Fargate)         │
           └───────┬────────┘   └──────────┬────────┘
  db               │ 5432, TLS required    │
           ┌───────▼───────────────────────▼───────┐
           │  RDS PostgreSQL (private, encrypted)  │
           └───────────────────────────────────────┘
```

| Piece | Choice | Why |
|---|---|---|
| Network | VPC across 2 AZs; public, app and db subnets | Only the load balancer is reachable from the internet. The database has no internet route at all. |
| Outbound | One NAT gateway (per-AZ is optional) | The app must call the LLM APIs. One NAT is ~$33/mo, and an AZ outage would only cut outbound calls. |
| Database | RDS PostgreSQL 17, `db.t4g.small`, single-AZ, 14-day point-in-time recovery, deletion protection | Fits a research-scale workload. Use `db_multi_az` for automatic failover (about 2× the cost). |
| Encryption | One customer-managed KMS key per instance | Covers the database, secrets, logs and images. TLS from browser to ALB, and from app to database (`rds.force_ssl`). **The ALB→app hop is plain HTTP inside the private app subnets.** See the open items below. |
| Compute | ECS Fargate on ARM64 (Graviton) | No servers to patch. ~20% cheaper than x86, and images build natively on Apple-silicon Macs. |
| Secrets | SSM Parameter Store, under `/cloze-<instance>/` | Injected as environment variables at task start. API keys are set by hand, so they never enter Terraform state or git. |
| Deploys | Immutable image tags (git SHA); automatic rollback | The running code is always identifiable, and a broken deploy reverts itself. |
| Admin access | ECS Exec (`aws ecs execute-command`) | A shell inside a running task, for migrations. No SSH and no bastion host, and every session is logged in CloudTrail. |
| Safety rail | `allowed_account_ids` in the provider | Terraform refuses to touch any account other than the instance's own. |

**Rough cost** (us-east-1, idle-to-light use): about **$115–125/month**.

| Item | Monthly |
|---|---|
| NAT gateway | $33 |
| Load balancer | $22 |
| Database | $27 |
| One web task | $23 |
| Public IPv4 addresses | $11 |
| KMS, logs and storage | a few dollars |

The reports worker adds about $23.

## Prerequisites

- Terraform ≥ 1.10, the AWS CLI v2, and Docker.
- An AWS CLI profile with admin rights in the instance's account. Give it a distinctive name, and never `default`.
- A hostname you can add DNS records for.

## First-time setup

All commands run from `infra/terraform/`, unless noted otherwise.

**1. Create the state bucket.** This is once per account:

```bash
scripts/bootstrap-state-bucket.sh <profile> <account-id>
```

**2. Create the instance folder.** For a new instance, copy `instances/bidmc` to `instances/<name>`. Then copy the two `.example` files to `terraform.tfvars` and `backend.hcl`, and fill them in.

**3. Initialise:**

```bash
cd instances/<name>
terraform init -backend-config=backend.hcl
```

**4. First apply, with `enable_https = false`:**

```bash
terraform plan -out=tfplan
terraform apply tfplan
```

This creates the network, database, secrets, image registry, load balancer and certificate request. It takes ~10–15 min, mostly the database. No app runs yet, and port 80 answers "Not ready yet."

**5. Add DNS records** at your DNS host. If it's Cloudflare, set each to **DNS only** (grey cloud) for now.

- The certificate validation CNAME, from `terraform output`, under `cloze.certificate_validation_records`.
- A CNAME from your hostname to `cloze.load_balancer_dns_name`.

**6. Set the API keys** that Terraform created as placeholders (listed in `cloze.secrets_to_set_by_hand`). Set only the providers the instance uses:

```bash
aws ssm put-parameter --profile <profile> --overwrite --type SecureString \
  --name /cloze-<instance>/OPENAI_API_KEY --value 'sk-...'
```

**7. Build and push the app image:**

```bash
REPO=$(terraform output -json cloze | jq -r .ecr_repository_url)
TAG=$(git rev-parse --short HEAD)
aws ecr get-login-password --profile <profile> | docker login --username AWS --password-stdin "${REPO%%/*}"
docker build --platform linux/arm64 -t "$REPO:$TAG" ../../../..
docker push "$REPO:$TAG"
```

**8. Second apply.** When `cloze.certificate_status` says `ISSUED`, set `enable_https = true` and `image_tag = "<TAG>"` in `terraform.tfvars`, then plan and apply again. This adds the HTTPS listener and starts the web service.

**9. Set up the database** with ECS Exec into the running web task:

```bash
aws ecs execute-command --profile <profile> --cluster cloze-<instance> \
  --task <task-id> --container web --interactive --command "/bin/bash"
```

Inside the task:
- **Fresh instance:** `python -c "from manage import initialize_database; initialize_database()"`
- **Loading existing data:** `pg_restore` from a dump, then `python migrate_schema.py --apply`

## Deploying a new version

Build and push with the new commit's SHA (step 7), set `image_tag`, then plan and apply. ECS starts new tasks, waits for them to pass health checks, then drains the old ones. If they never become healthy, it rolls back automatically.

## Requirements this places on the app

- **An image built from the repo's `Dockerfile`.** It must include `gunicorn`, and it must not start the dev server or seed data on boot. The task definition supplies the command.
- **A `GET /healthz` that returns 200 without logging in.** The load balancer uses it to decide whether a task is alive.
- **Only one web task**, until the in-process report scheduler moves out of the web app. Otherwise every task runs it (`web_desired_count` defaults to 1).

## Open items

- **ALB→app encryption.** This hop is HTTP inside the VPC, reachable only from the load balancer's security group. If your compliance office reads the BAA's in-transit requirement as covering traffic inside the VPC, switch the target group to HTTPS. Gunicorn would then serve TLS with a certificate generated at container start; the ALB doesn't validate target certificates. Ask before going live.
- **Database user.** The app connects as the RDS master user. A separate least-privilege app user would be better, created once with ECS Exec.

## Not managed here (on purpose)

- **DNS records:** each institution has its own DNS host.
- **SES domain verification and production access:** these need human steps and AWS review.
- **CloudTrail, GuardDuty and budgets:** these are account-wide, so they're set up once per account outside Terraform.
