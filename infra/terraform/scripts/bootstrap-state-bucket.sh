#!/usr/bin/env bash
# Creates the S3 bucket that holds Terraform state for one AWS account.
# Run once per account, before the first `terraform init`.
#
#   scripts/bootstrap-state-bucket.sh <aws-profile> <expected-account-id> [region]
#
# The bucket is named cloze-tfstate-<account-id>. It is versioned (so a bad
# state write can be rolled back), encrypted, never public, and refuses
# non-TLS access. Terraform's own S3 lockfile handles locking, so no DynamoDB
# table is needed. Safe to re-run: every step is idempotent.

set -euo pipefail

PROFILE="${1:?usage: $0 <aws-profile> <expected-account-id> [region]}"
EXPECTED_ACCOUNT="${2:?usage: $0 <aws-profile> <expected-account-id> [region]}"
REGION="${3:-us-east-1}"
BUCKET="cloze-tfstate-${EXPECTED_ACCOUNT}"

actual_account="$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)"
if [[ "$actual_account" != "$EXPECTED_ACCOUNT" ]]; then
  echo "Refusing: profile '$PROFILE' is account $actual_account, expected $EXPECTED_ACCOUNT." >&2
  exit 1
fi
echo "Account $actual_account confirmed. Bucket: $BUCKET ($REGION)"

if aws s3api head-bucket --bucket "$BUCKET" --profile "$PROFILE" 2>/dev/null; then
  echo "Bucket already exists; re-applying settings."
elif [[ "$REGION" == "us-east-1" ]]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" --profile "$PROFILE" >/dev/null
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" --profile "$PROFILE" \
    --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
fi

aws s3api put-public-access-block --bucket "$BUCKET" --profile "$PROFILE" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-versioning --bucket "$BUCKET" --profile "$PROFILE" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption --bucket "$BUCKET" --profile "$PROFILE" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}'

aws s3api put-bucket-policy --bucket "$BUCKET" --profile "$PROFILE" --policy "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyInsecureTransport",
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:*",
    "Resource": ["arn:aws:s3:::${BUCKET}", "arn:aws:s3:::${BUCKET}/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }]
}
EOF
)"

# Old state versions are only for recovery; don't keep them forever.
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --profile "$PROFILE" \
  --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-old-state-versions","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":90}}]}'

aws s3api put-bucket-tagging --bucket "$BUCKET" --profile "$PROFILE" \
  --tagging 'TagSet=[{Key=Project,Value=cloze},{Key=ManagedBy,Value=bootstrap-script}]'

echo "Done. Use bucket = \"$BUCKET\" in backend.hcl."
