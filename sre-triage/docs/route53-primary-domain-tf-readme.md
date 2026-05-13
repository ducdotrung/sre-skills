# route53-{your-org}-com-tf

Terraform project to manage all DNS records for `{your-org}.com` via AWS Route 53.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Repository Structure](#repository-structure)
4. [How It Works](#how-it-works)
5. [Getting Started](#getting-started)
6. [Common Tasks](#common-tasks)
   - [Add a new DNS record](#add-a-new-dns-record)
   - [Add a new CloudFront data source + record](#add-a-new-cloudfront-data-source--record)
   - [Remove a DNS record](#remove-a-dns-record)
   - [Change the target of an existing record](#change-the-target-of-an-existing-record)
7. [Environment Conventions](#environment-conventions)
8. [Backend & State](#backend--state)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This repo is the single source of truth for every DNS record under `{your-org}.com`. All changes to DNS must go through this Terraform code — never edit records manually in the AWS Console, as the next `terraform apply` will overwrite any manual change.

Records are split by environment across separate files to keep diffs focused and easy to review.

---

## Prerequisites

Make sure you have the following installed and configured before working with this repo.

### Required tools

| Tool | Version | Install |
|------|---------|---------|
| Terraform | `~> 1.x` (provider requires AWS `5.51.1`) | [terraform.io](https://developer.hashicorp.com/terraform/install) |
| AWS CLI | `v2` | [aws.amazon.com/cli](https://aws.amazon.com/cli/) |

### AWS credentials

You need an IAM role/user with at minimum these permissions:
- `route53:*` on the hosted zone
- `elasticloadbalancing:DescribeLoadBalancers` (for data sources)
- `cloudfront:GetDistribution` (for data sources)
- `s3:GetObject`, `s3:PutObject` on bucket `route53-{your-org}-com-tf`
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:DeleteItem` on table `route53-{your-org}-com-tf-lock`

Configure your credentials before running any Terraform command:

```bash
# Option A — environment variables
export AWS_ACCESS_KEY_ID=<your-key>
export AWS_SECRET_ACCESS_KEY=<your-secret>
export AWS_DEFAULT_REGION=ap-northeast-1

# Option B — AWS profile
aws configure --profile {your-org}
export AWS_PROFILE={your-org}
```

---

## Repository Structure

```
.
├── main.tf              # Terraform backend (S3 + DynamoDB lock) and provider config
├── variables.tf         # Input variables (region, default TTL)
├── route53_zones.tf     # The Route 53 hosted zone resource for {your-org}.com
├── data.tf              # Data sources — looks up existing Load Balancers and CloudFront distributions
├── records_dev.tf       # DNS records for the dev environment
├── records_uat.tf       # DNS records for the uat environment
├── records_staging.tf   # DNS records for the staging environment
├── records_prod.tf      # DNS records for production (and shared/unversioned records)
└── outputs.tf           # Outputs (e.g. LB DNS names for reference)
```

### Key concepts

**`data.tf`** — Terraform data sources that *look up* existing AWS resources (Load Balancers, CloudFront distributions) by ARN or ID. They don't create anything; they just expose attributes like `dns_name` or `domain_name` so that DNS records can reference them dynamically.

**`records_*.tf`** — Each file contains `aws_route53_record` resources for one environment. Every record points either to:
- A Load Balancer DNS name via `data.aws_lb.<name>.dns_name`, or
- A CloudFront distribution domain via `data.aws_cloudfront_distribution.<name>.domain_name`.

**`var.ttl`** — Default TTL is `60` seconds (set in `variables.tf`). This keeps propagation fast in non-prod environments. Production NS/SOA records use longer TTLs set inline.

---

## How It Works

```
New service/subdomain needed
        │
        ▼
 Does a data source already exist       ──No──► Add data source block in data.tf
 in data.tf for the target LB or CDN?             (AWS LB ARN or CloudFront ID)
        │
       Yes
        │
        ▼
 Add aws_route53_record in the          (use records_dev.tf / records_uat.tf /
 correct records_*.tf file              records_staging.tf / records_prod.tf)
        │
        ▼
 terraform plan  →  review diff  →  terraform apply
```

---

## Getting Started

### 1. Clone the repo

```bash
git clone <repo-url>
cd route53-{your-org}-com-tf
```

### 2. Initialize Terraform

This downloads the AWS provider and connects to the remote S3 backend.

```bash
terraform init
```

Expected output ends with:
```
Terraform has been successfully initialized!
```

### 3. Verify your changes with plan

Always run `plan` before `apply` so you can review exactly what will change.

```bash
terraform plan
```

Read the output carefully:
- `+ create` — a new record will be added
- `~ update in-place` — an existing record's value will change
- `- destroy` — a record will be deleted (treat with extra caution in prod)

### 4. Apply changes

```bash
terraform apply
```

Type `yes` when prompted. Terraform will acquire a DynamoDB lock so only one person can apply at a time.

---

## Common Tasks

### Add a new DNS record

Use this when a new service is deployed and needs a subdomain.

**Step 1 — Find the target**

Identify whether the service sits behind:
- A **Load Balancer** — get its ARN and logical name from the AWS Console or the team that deployed it.
- A **CloudFront distribution** — get its distribution ID (e.g. `E1ABC2DEF3GHI4`).

**Step 2 — Check if a matching data source already exists in `data.tf`**

Open `data.tf` and search for the LB name or CloudFront ID. If it already exists, skip Step 3.

**Step 3 (if needed) — Add a data source to `data.tf`**

For a Load Balancer:
```hcl
data "aws_lb" "{your-org}-com-<env>" {
  arn  = "arn:aws:elasticloadbalancing:ap-northeast-1:<account-id>:loadbalancer/net/<lb-name>/<lb-id>"
  name = "{your-org}-com-<env>"
}
```

For a CloudFront distribution:
```hcl
data "aws_cloudfront_distribution" "<descriptive-name>-cdn-{your-org}-com" {
  id = "EXXX..."
}
```

**Step 4 — Add the `aws_route53_record` to the correct environment file**

Pick the right file:

| Environment | File |
|-------------|------|
| dev | `records_dev.tf` |
| uat | `records_uat.tf` |
| staging | `records_staging.tf` |
| prod / no env prefix | `records_prod.tf` |

Add a block like this (CNAME to a Load Balancer):
```hcl
# <subdomain>.{your-org}.com
resource "aws_route53_record" "<subdomain>" {
  zone_id = aws_route53_zone.{your-org}-com-public.zone_id
  name    = "<subdomain>"
  type    = "CNAME"
  ttl     = var.ttl
  records = [data.aws_lb.{your-org}-com-<env>.dns_name]
}
```

Or to a CloudFront distribution:
```hcl
# <subdomain>.{your-org}.com
resource "aws_route53_record" "<subdomain>" {
  zone_id = aws_route53_zone.{your-org}-com-public.zone_id
  name    = "<subdomain>"
  type    = "CNAME"
  ttl     = var.ttl
  records = [data.aws_cloudfront_distribution.<data-source-name>.domain_name]
}
```

**Step 5 — Plan and apply**

```bash
terraform plan
terraform apply
```

---

### Add a new CloudFront data source + record

This is a combined walkthrough for the common case of a new CDN-backed subdomain.

1. Get the CloudFront distribution ID from the team (or AWS Console → CloudFront → copy the ID column, e.g. `E2ABC1DEF2GHI3`).

2. Add to `data.tf`:
```hcl
data "aws_cloudfront_distribution" "<env>-<service>-cdn-{your-org}-com" {
  id = "E2ABC1DEF2GHI3"
}
```

3. Add to the appropriate `records_*.tf`:
```hcl
# <env>-<service>-cdn.{your-org}.com
resource "aws_route53_record" "<env>-<service>-cdn" {
  zone_id = aws_route53_zone.{your-org}-com-public.zone_id
  name    = "<env>-<service>-cdn"
  type    = "CNAME"
  ttl     = var.ttl
  records = [data.aws_cloudfront_distribution.<env>-<service>-cdn-{your-org}-com.domain_name]
}
```

4. Run `terraform plan` then `terraform apply`.

---

### Remove a DNS record

1. Delete the `aws_route53_record` block from the relevant `records_*.tf` file.
2. If the data source in `data.tf` is **no longer referenced by any record**, delete it too. Leaving orphaned data sources is harmless but adds clutter.
3. Run `terraform plan` — confirm only the intended record shows `- destroy`.
4. Run `terraform apply`.

> **Warning:** Deleting a production record will immediately stop routing traffic to that service. Double-check the subdomain is retired before applying.

---

### Change the target of an existing record

For example, to point `uat-api.{your-org}.com` to a different load balancer:

1. Open the relevant `records_*.tf` file and update the `records` value:
```hcl
records = [data.aws_lb.{your-org}-com-staging.dns_name]  # was {your-org}-com-uat
```
2. If the new target is a data source that doesn't exist yet, add it to `data.tf` first.
3. Run `terraform plan` to verify the record shows an `~ update`.
4. Run `terraform apply`.

---

## Environment Conventions

Records follow a strict naming prefix convention:

| Prefix | Environment | Load Balancer data source |
|--------|-------------|--------------------------|
| `dev-` | Development | `data.aws_lb.{your-org}-com-uat` |
| `uat-` | UAT | `data.aws_lb.{your-org}-com-uat` |
| `staging-` | Staging | `data.aws_lb.{your-org}-com-staging` |
| *(none)* | Production | `data.aws_lb.{your-org}-com-prod` |

Note that both `dev-` and `uat-` currently share the same UAT load balancer (`{your-org}-com-uat`). This is intentional — dev traffic runs on the UAT cluster.

CDN records use the suffix `-cdn` in the subdomain name and always reference a CloudFront data source, not a load balancer.

---

## Backend & State

Terraform state is stored remotely so the whole team shares one source of truth.

| Setting | Value |
|---------|-------|
| S3 bucket | `route53-{your-org}-com-tf` |
| S3 key | `terraform.tfstate` |
| Region | `ap-southeast-1` |
| DynamoDB lock table | `route53-{your-org}-com-tf-lock` |
| Encryption | enabled |

The state file is encrypted at rest and locked during `apply` via DynamoDB. Never manually edit or delete the state file.

---

## Troubleshooting

### `Error: Reference to undeclared resource`

You added a record that references a data source name that doesn't exist in `data.tf`. Add the data source block and run `terraform init` (if a new provider was added) then `terraform plan` again.

### `Error acquiring the state lock`

Another `terraform apply` is in progress, or a previous run crashed and left a stale lock. Check with your team first. To forcefully release a stale lock (only when certain no one else is running):

```bash
terraform force-unlock <LOCK_ID>
```

The lock ID is shown in the error message.

### `Error: creating Route 53 record: InvalidChangeBatch`

This usually means you're trying to create a CNAME at the zone apex (`{your-org}.com` itself). The root domain already has NS/MX/TXT records, and CNAMEs cannot coexist with other record types at the apex. Use an ALIAS record type instead, or use a subdomain.

### Record exists in AWS but not in Terraform

The record was created manually. Import it first so Terraform can manage it:

```bash
terraform import aws_route53_record.<resource_name> <zone_id>_<name>_<type>
```

Example:
```bash
terraform import aws_route53_record.my-new-service Z1ABC2DEF3GHI4_my-new-service.{your-org}.com_CNAME
```

Then run `terraform plan` — if the imported record matches your code there should be no diff.
