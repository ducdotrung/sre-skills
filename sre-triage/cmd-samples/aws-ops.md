# AWS Operations

## Secrets Manager

### Get current secret value

```bash
aws secretsmanager get-secret-value \
  --secret-id eks-{cluster-prefix}-{app-name} \
  --region ap-northeast-1 \
  --query SecretString \
  --output text
```

### Update secret (always include ALL existing keys)

```bash
aws secretsmanager put-secret-value \
  --secret-id eks-{cluster-prefix}-{app-name} \
  --region ap-northeast-1 \
  --secret-string '{"EXISTING_KEY": "old-val", "NEW_KEY": "new-val"}'
```

### Create new secret

```bash
aws secretsmanager create-secret \
  --name eks-{cluster-prefix}-{app-name} \
  --description "Secrets for {app-name} on {env}" \
  --region ap-northeast-1 \
  --secret-string '{"KEY": "value"}'
```

### Backup secret before modifying

```bash
aws secretsmanager get-secret-value \
  --secret-id eks-{cluster-prefix}-{app-name} \
  --query SecretString \
  --output text > backup-$(date +%Y%m%d-%H%M%S).json
```

### Merge new keys into existing secret (jq pattern)

```bash
CURRENT=$(aws secretsmanager get-secret-value \
  --secret-id eks-{cluster-prefix}-{app-name} \
  --query SecretString \
  --output text)

echo "$CURRENT" | jq '. + {"NEW_KEY": "new-val"}' > merged-secret.json

aws secretsmanager update-secret \
  --secret-id eks-{cluster-prefix}-{app-name} \
  --secret-string file://merged-secret.json
```

---

## ECR

### Check image exists before deploy

```bash
aws ecr describe-images \
  --repository-name {ecr-repo-name} \
  --image-ids imageTag={tag} \
  --region ap-northeast-1
```

### Full ECR image URL pattern

```
{ECR_PREFIX}{repo-name}:{tag}
```

---

## RDS Snapshots

### Create snapshot before migration/deploy

```bash
aws rds create-db-snapshot \
  --db-instance-identifier {rds-instance-id} \
  --db-snapshot-identifier {app}-pre-{version}-$(date +%Y%m%d) \
  --region ap-northeast-1
```

---

## S3

### Sync between buckets

```bash
aws s3 sync s3://{source-bucket}/{path}/ s3://{dest-bucket}/{path}/ \
  --region ap-northeast-1
```

### Delete all versioned objects (before deleting bucket)

```bash
aws s3api list-object-versions \
    --bucket {bucket-name} \
    --output json | jq -r '.Versions[], .DeleteMarkers[] | select(.Key != null) | "--key \"\(.Key)\" --version-id \(.VersionId)"' | \
    while read -r line; do
        eval "aws s3api delete-object --bucket {bucket-name} $line"
    done

# Then force-remove the (now empty) bucket
aws s3 rb s3://{bucket-name} --force
```

### CloudFront invalidation

```bash
aws cloudfront create-invalidation \
  --distribution-id {distribution-id} \
  --paths "/*"
```

---

## SES — Suppression List

### List suppressed destinations in a date range

```bash
aws sesv2 list-suppressed-destinations \
  --region ap-northeast-1 \
  --start-date {YYYY-MM-DDT00:00:00Z} \
  --end-date {YYYY-MM-DDT00:00:00Z} \
  --page-size 1000 \
  --output json > suppressed.json
```

### Remove specific addresses from suppression list

```bash
aws sesv2 delete-suppressed-destination \
  --region ap-northeast-1 \
  --email-address "{email}"
```

---

## EC2 / IAM

### Describe instance IAM profile

```bash
aws ec2 describe-instances \
  --instance-ids {instance-id} \
  --query 'Reservations[*].Instances[*].IamInstanceProfile.Arn' \
  --output text
```

### Get IAM role from instance metadata (run on the instance)

```bash
curl -s http://169.254.169.254/latest/meta-data/iam/info
```

### Create ECR-push IAM user

```bash
aws iam create-user --user-name {username}
aws iam attach-user-policy \
  --user-name {username} \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser
aws iam create-access-key --user-name {username}
```

---

## GCP / gcloud

### Grant service account role

```bash
gcloud iam service-accounts add-iam-policy-binding \
  {sa-email} \
  --member="serviceAccount:{sa-email}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project={project-id}
```

### Export and diff IAM policy

```bash
gcloud projects get-iam-policy {project-id} \
  --format=json > iam-policy-$(date +%Y%m%d).json

diff iam-policy-old.json iam-policy-new.json
```

### Apply IAM policy

```bash
gcloud projects set-iam-policy {project-id} iam-policy.json
```
