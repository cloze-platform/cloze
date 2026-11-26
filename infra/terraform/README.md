# Cloze on AWS: Terraform

This folder builds one complete Cloze instance inside a dedicated AWS account: network, database, container service, image build, load balancer and HTTPS certificate.

- `modules/cloze/` is the reusable part.
- `examples/single-instance/` is a thin wrapper around it. Its real values live in gitignored `terraform.tfvars` and `backend.hcl` files. For a long-lived instance, copy it into a private deploy repository and pin the module to a release tag.

**Before using this, the account itself should be set up:** a dedicated account, a locked-down root user, an admin login inside the account, CloudTrail, account-level S3 Block Public Access, and default EBS encryption. If participant data will be stored, a BAA must also be accepted for the account. Terraform deliberately doesn't manage any of those.

## What it builds

```
                internet
                   │  80 → redirect, 443 (TLS 1.2+/1.3, ACM certificate)
           ┌───────▼────────┐
  public   │  Load balancer │        NAT gateway ──► internet (LLM APIs, SES, ECR)
           └───────┬────────┘              ▲
  app              │ :8000                 │
           ┌───────▼────────┐              │
           │  web (Fargate) ├──────────────┘
           │  gunicorn      │
           └───────┬────────┘
  db               │ 5432, TLS required
           ┌───────▼───────────────────────────────┐
           │  RDS PostgreSQL (private, encrypted)  │
           └───────────────────────────────────────┘

  CodeBuild (outside the VPC): clones a commit from GitHub → builds → pushes to ECR
```

| Piece | Choice | Why |
|---|---|---|
| Network | VPC across 2 AZs; public, app and db subnets | Only the load balancer is reachable from the internet. The database has no internet route at all. |
| Outbound | One NAT gateway (per-AZ is optional) | The app must call the LLM APIs. One NAT is ~$33/mo, and an AZ outage would only cut outbound calls. |
| Database | RDS PostgreSQL 17, `db.t4g.small`, single-AZ, 14-day point-in-time recovery, deletion protection | Fits a research-scale workload. Use `db_multi_az` for automatic failover (about 2× the cost). |
| Encryption | One customer-managed KMS key per instance | Covers the database, secrets, logs, container images and researcher media. TLS on every hop: browser to ALB (ACM certificate), ALB to app (a self-signed certificate the container generates at start), and app to database (`rds.force_ssl`, with the app verifying the server against the RDS certificate authorities). |
| Database users | The app connects as `cloze_app`, which can read and write rows but not change the schema | The owner (RDS master user) is only used by the admin task definition, for setup and migrations. |
| Compute | ECS Fargate on ARM64 (Graviton) | No servers to patch, and ~20% cheaper than x86. |
| Researcher media | A private S3 bucket, `<name>-media-<account>`, versioned (90 days of old versions) | Researchers' images (and later video). Nobody reads the bucket directly: the app checks who may see a file, then redirects to a presigned URL that lasts minutes. The app can't delete or list files, and the S3 gateway endpoint keeps its uploads off the NAT. |
| Secrets | SSM Parameter Store, under `/cloze-<instance>/` | Injected as environment variables at task start. API keys are set by hand, so they never enter Terraform state or git. |
| Image builds | CodeBuild in the instance's account, from a commit on GitHub | No Docker needed locally, and an image can only contain committed code: nothing from anyone's working tree. |
| Deploys | Immutable image tags (git SHA); automatic rollback | The running code is always identifiable, and a broken deploy reverts itself. |
| Admin access | One-off tasks and ECS Exec (`aws ecs execute-command`) | No SSH and no bastion host. CloudTrail records each session starting, and ECS Exec sessions themselves are recorded in the `/<name>/exec` log group. |
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

Image builds cost a few cents each.

## Prerequisites

- Terraform ≥ 1.10, the AWS CLI v2 with the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html), and `jq`. Docker isn't needed.
- An AWS CLI profile with admin rights in the instance's account. Give it a distinctive name, and never `default`.
- A hostname you can add DNS records for.

## First-time setup

All commands run from `infra/terraform/`, unless noted otherwise. `<profile>` is the AWS CLI profile and `<name>` is the module's `name` (`cloze-<instance>` in the example).

**1. Create the state bucket.** This is once per account:

```bash
scripts/bootstrap-state-bucket.sh <profile> <account-id>
```

**2. Fill in the instance's values.** In `examples/single-instance/` (or your deploy repository's copy of it), copy the two `.example` files to `terraform.tfvars` and `backend.hcl`, and fill them in.

**3. Initialise:**

```bash
cd examples/single-instance
terraform init -backend-config=backend.hcl
```

**4. First apply, with `enable_https = false`:**

```bash
terraform plan -out=tfplan
terraform apply tfplan
```

This creates the network, database, secrets, image registry and build project, the app's task definition, the load balancer and the certificate request. It takes ~10–15 min, mostly the database. No app runs yet, and port 80 answers "Not ready yet."

**5. Add the certificate validation record** at your DNS host: the CNAME under `cloze.certificate_validation_records` in `terraform output`. If it's Cloudflare, set it to **DNS only** (grey cloud).

**6. Set the API keys** for the providers in `llm_providers`. Terraform created them as placeholders, listed in `cloze.secrets_to_set_by_hand`. Paste the key at the prompt; it's piped in, so it stays out of your shell history and the process list:

```bash
printf 'API key: '; read -rs KEY; echo
printf %s "$KEY" | aws ssm put-parameter --profile <profile> --overwrite --type SecureString \
  --name /<name>/OPENAI_API_KEY --value file:///dev/stdin; unset KEY
```

Or edit the parameter in the console (Systems Manager → Parameter Store), keeping the type and the `alias/<name>-data` key.

**7. Build the image** from a commit on GitHub (`GIT_REF` can be a branch, tag or commit SHA):

```bash
aws codebuild start-build --profile <profile> --project-name <name>-image \
  --environment-variables-override name=GIT_REF,value=main
aws logs tail /<name>/build --profile <profile> --follow
```

The log ends with `Pushed <repository>:<commit-sha>`. Set `image_tag = "<commit-sha>"` in `terraform.tfvars`, then plan and apply. This points the task definition at the image; nothing runs yet.

**8. Set up the database and test the app before DNS.** These run the app's task definition as one-off tasks in the private subnets. First, collect the network settings:

```bash
OUT=$(terraform output -json cloze)
NET="awsvpcConfiguration={subnets=[$(echo "$OUT" | jq -r '.app_subnet_ids | join(",")')],securityGroups=[$(echo "$OUT" | jq -r .app_security_group_id)],assignPublicIp=DISABLED}"
```

Run the admin task, which connects as the database owner and runs `manage.py init-production`. That creates the tables, models and system prompts (no demo accounts or data), then the `cloze_app` user the app connects as:

```bash
aws ecs run-task --profile <profile> --cluster <name> --task-definition <name>-admin \
  --launch-type FARGATE --network-configuration "$NET"
aws logs tail /<name>/admin --profile <profile> --follow   # ends "Database user 'cloze_app' is up to date."
```

Then start the app itself, with ECS Exec on, and forward its port to your machine:

```bash
TASK=$(aws ecs run-task --profile <profile> --cluster <name> --task-definition <name>-web \
  --launch-type FARGATE --network-configuration "$NET" --enable-execute-command \
  --query 'tasks[0].taskArn' --output text | awk -F/ '{print $NF}')
aws ecs wait tasks-running --profile <profile> --cluster <name> --tasks "$TASK"
RUNTIME=$(aws ecs describe-tasks --profile <profile> --cluster <name> --tasks "$TASK" \
  --query 'tasks[0].containers[0].runtimeId' --output text)
aws ssm start-session --profile <profile> --target "ecs:<name>_${TASK}_${RUNTIME}" \
  --document-name AWS-StartPortForwardingSession --parameters portNumber=8000,localPortNumber=8000
```

Open https://localhost:8000/login and accept the browser's warning about the self-signed certificate. In a second terminal, create the first admin. The password is typed at a hidden prompt:

```bash
aws ecs execute-command --profile <profile> --cluster <name> --task "$TASK" \
  --container web --interactive --command "python manage.py create-admin <username> <email>"
```

Log in, check a chat works, then stop the task: `aws ecs stop-task --profile <profile> --cluster <name> --task "$TASK"`.

**9. Go live.** When `cloze.certificate_status` says `ISSUED`, set `enable_https = true`, then plan and apply. This adds the HTTPS listener and starts the web service. Then add a CNAME from your hostname to `cloze.load_balancer_dns_name` (DNS only, on Cloudflare).

## Instance colours

Set `theme` in `terraform.tfvars` to give an instance its own palette, then plan and apply. Any of `primary`, `hover`, `accent`, `tint`, `on_dark`, `on_dark_hover`, `dark_page`, `dark_sidebar`, `dark_card`, `dark_raised` and `dark_border` can be set; the rest keep the Cloze palette. A custom `primary` also recolours the soft tints the app derives from it. The app checks the values at startup and refuses to start on a typo.

## Deploying a new version

1. **Snapshot the database:**

   ```bash
   aws rds create-db-snapshot --profile <profile> --db-instance-identifier <name> \
     --db-snapshot-identifier <name>-before-<version>
   ```

2. **Build the image** (step 7) from the release tag, and note the commit SHA it pushed.

3. **Run the migration, if the release has one**, with the **new** image and **before** the app moves to it. The release's changelog says under **Upgrade** whether there is one.

   The app and the admin task share `image_tag`. So first point only the admin task definition at the new image. Otherwise the admin task runs the *old* `migrate_schema.py`, which doesn't know about the new columns.

   ```bash
   terraform apply -var "image_tag=<sha>" -target=module.cloze.aws_ecs_task_definition.admin
   ```

   (`module.cloze` is the module's address in `examples/single-instance`; use yours if your configuration names it differently.)

   Then run the admin task as in step 8, overriding its command. Run it first without `--apply`, which prints what it will change, then with it:

   ```bash
   aws ecs run-task --profile <profile> --cluster <name> --task-definition <name>-admin \
     --launch-type FARGATE --network-configuration "$NET" \
     --overrides '{"containerOverrides":[{"name":"admin","command":["python","migrate_schema.py","--apply"]}]}'
   aws logs tail /<name>/admin --profile <profile> --follow
   ```

   New columns are nullable, so the running version is unaffected. The new version would fail against the old schema, which is why this comes first.

4. **Move the app:** set `image_tag` to the new commit SHA in `terraform.tfvars`, then plan and apply.

ECS starts new tasks, waits for them to pass health checks, then drains the old ones. If they never become healthy, it rolls back automatically. To roll back by hand, set `image_tag` back to the previous SHA and apply. The migration's new columns can stay, because older versions ignore them.

## Requirements this places on the app

- **An image built from the repo's `Dockerfile`**, whose default command runs gunicorn with HTTPS on port 8000. It must not start the dev server or seed data on boot.
- **A `GET /healthz` that returns 200 without logging in or touching the database.** The load balancer uses it to decide whether a task is alive.
- **Setup commands for a fresh install:** `manage.py init-production`, which also creates the restricted database user from `CLOZE_APP_DATABASE_URL`, and `manage.py create-admin`.
- **Only one web task**, until the in-process report scheduler moves out of the web app. Otherwise every task runs it (`web_desired_count` defaults to 1).

## Not managed here (on purpose)

- **DNS records:** each institution has its own DNS host.
- **SES domain verification and production access:** these need human steps and AWS review.
- **CloudTrail, GuardDuty and budgets:** these are account-wide, so they're set up once per account outside Terraform.
