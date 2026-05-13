# route53-{yourcompany}-ai-tf

Terraform repository for managing all AWS Route53 DNS records for the `{yourcompany}.ai` domain.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Repository Structure](#repository-structure)
4. [Architecture](#architecture)
5. [DNS Naming Conventions](#dns-naming-conventions)
6. [Getting Started](#getting-started)
7. [Day-to-Day Tasks](#day-to-day-tasks)
   - [Add a New DNS Record (Expose a Service)](#add-a-new-dns-record-expose-a-service)
   - [Add a New CloudFront CDN Record](#add-a-new-cloudfront-cdn-record)
   - [Remove a DNS Record](#remove-a-dns-record)
   - [Add a New Load Balancer Data Source](#add-a-new-load-balancer-data-source)
8. [Applying Changes](#applying-changes)
9. [Terraform State](#terraform-state)
10. [Variables Reference](#variables-reference)
11. [Troubleshooting](#troubleshooting)

---

## Overview

This repo uses **Terraform** to declare and manage Route53 DNS records pointing `{yourcompany}.ai` subdomains to AWS infrastructure (NLBs, CloudFront distributions, and static IPs). Every DNS change to `{yourcompany}.ai` must go through this repo — no manual changes in the AWS Console.

**Key facts:**
- Domain: `{yourcompany}.ai`
- AWS Account: `{AWS_ACCOUNT_ID}`
- Primary region (Route53 / LBs): `ap-northeast-1` (Tokyo)
- State backend region: `ap-southeast-1` (Singapore)
- Terraform version: AWS Provider `5.51.1`

---

## Prerequisites

Before working with this repo, make sure you have the following installed and configured:

### 1. Terraform

```bash
# macOS (via Homebrew)
brew install terraform

# Verify
terraform -version
# Should show: Terraform v1.x.x
```

### 2. AWS CLI + Credentials

You need AWS credentials with permissions to:
- Read/write Route53 records
- Read S3 (for Terraform state)
- Read/write DynamoDB (for state locking)
- Describe EC2 Load Balancers and CloudFront distributions

```bash
# Install AWS CLI (macOS)
brew install awscli

# Configure credentials
aws configure
# Enter: AWS Access Key ID, Secret Access Key, default region (ap-northeast-1), output format (json)
```

Alternatively, if the team uses AWS SSO or IAM roles, ask a senior DevOps for the login method.

Verify your credentials work:

```bash
aws sts get-caller-identity
```

### 3. Clone this Repository

```bash
git clone <repo-url>
cd route53-{yourcompany}-ai-tf
```

---

## Repository Structure

```
route53-{yourcompany}-ai-tf/
├── main.tf            # Backend config (S3 state) and AWS provider setup
├── variables.tf       # Input variables (region, TTL, static IPs)
├── data.tf            # Data sources: Load Balancers and CloudFront distributions
├── route53_zones.tf   # Route53 hosted zone definition for {yourcompany}.ai
├── records_prod.tf    # Production DNS records (no prefix)
├── records_uat.tf     # UAT and Dev DNS records (uat-*, dev-* prefix)
├── records_stag.tf    # Staging DNS records (stag-*, staging-* prefix)
├── records_devops.tf  # DevOps/infrastructure records (monitoring, corp network)
├── outputs.tf         # Outputs (e.g., UAT LB DNS name)
└── .gitignore         # Ignores .tfstate, .tfvars, .terraform/
```

### File purposes at a glance

| File | What to edit |
|---|---|
| `records_prod.tf` | Add/remove production subdomains |
| `records_uat.tf` | Add/remove UAT or dev subdomains |
| `records_stag.tf` | Add/remove staging subdomains |
| `records_devops.tf` | Add/remove internal tools, monitoring endpoints |
| `data.tf` | Register a new LB or CloudFront distribution as a data source |
| `variables.tf` | Add new variables (rarely needed) |

---

## Architecture

### Terraform State Backend

State is stored remotely so the whole team shares one source of truth:

```
S3 Bucket:      route53-{yourcompany}-ai-tf       (ap-southeast-1)
DynamoDB Table: route53-{yourcompany}-ai-tf-lock  (ap-southeast-1, used for locking)
State key:      terraform.tfstate
```

DynamoDB locking prevents two people from running `terraform apply` at the same time.

### DNS Infrastructure

All DNS records point to one of the following backends:

| Data source name | What it is | Used for |
|---|---|---|
| `{yourcompany}-ai-prod` | Production NLB (ap-northeast-1) | All production service records |
| `{yourcompany}-ai-uat` | UAT NLB (ap-northeast-1) | UAT and dev service records |
| `{yourcompany}-ai-stag` | Staging NLB (ap-northeast-1) | Staging service records |
| `{yourcompany}-gateway-uat` | UAT Gateway NLB | UAT internal monitoring |
| `monitoring-{yourcompany}-ai` | Prod monitoring NLB | Prometheus / Alertmanager |
| `stag-monitoring-{yourcompany}-ai` | Staging monitoring NLB | Stag Prometheus / Alertmanager |
| CloudFront distributions | CDN endpoints | CDN-backed services (`*-cdn`) |

### Record Type Summary

| Record type | Syntax | Points to |
|---|---|---|
| `CNAME` | Most records | NLB DNS name or CloudFront domain |
| `A` | Static IP records | Self-hosted servers (e.g., LiveKit) or corp VPN IPs |
| `MX` | Mail records | Google Workspace MX servers |
| `TXT` | Verification records | Google/Atlassian/Figma domain verification, SPF |

---

## DNS Naming Conventions

Subdomains follow a strict environment-prefix pattern:

| Environment | Prefix | Example | LB target |
|---|---|---|---|
| Production | _(no prefix)_ | `{your-cluster-prefix}-api.{yourcompany}.ai` | `{yourcompany}-ai-prod` |
| UAT | `uat-` | `uat-{your-cluster-prefix}-api.{yourcompany}.ai` | `{yourcompany}-ai-uat` |
| Dev | `dev-` | `dev-{your-cluster-prefix}-api.{yourcompany}.ai` | `{yourcompany}-ai-uat` |
| Staging | `stag-` or `staging-` | `stag-{your-cluster-prefix}-api.{yourcompany}.ai` | `{yourcompany}-ai-stag` |

> **Note:** Both `dev-*` and `uat-*` records point to the same `{yourcompany}-ai-uat` load balancer. The differentiation is done at the ingress/k8s level, not at the DNS level.

CDN records follow the same pattern with a `-cdn` suffix:

- `{your-cluster-prefix}-cdn.{yourcompany}.ai` → Production CloudFront
- `uat-{your-cluster-prefix}-cdn.{yourcompany}.ai` → UAT CloudFront
- `staging-{your-cluster-prefix}-cdn.{yourcompany}.ai` → Staging CloudFront

---

## Getting Started

### Initialize Terraform (first time only)

After cloning the repo, initialize Terraform to download providers and connect to the S3 state backend:

```bash
terraform init
```

Expected output:
```
Initializing the backend...
Initializing provider plugins...
- Finding hashicorp/aws versions matching "5.51.1"...
- Installed hashicorp/aws v5.51.1

Terraform has been successfully initialized!
```

You only need to re-run `terraform init` if:
- Someone updates the provider version in `main.tf`
- You're running this on a new machine for the first time

---

## Day-to-Day Tasks

### Add a New DNS Record (Expose a Service)

This is the most common task. Follow these steps:

**Step 1: Identify the target environment**

- Production → edit `records_prod.tf`
- UAT / Dev → edit `records_uat.tf`
- Staging → edit `records_stag.tf`
- DevOps/internal tools → edit `records_devops.tf`

**Step 2: Add the resource block**

Use the appropriate template below.

#### Template: CNAME pointing to a Load Balancer

```hcl
# <subdomain>.{yourcompany}.ai
resource "aws_route53_record" "<unique-resource-name>" {
  zone_id = aws_route53_zone.{yourcompany}-ai-public.zone_id
  ttl     = var.ttl
  name    = "<subdomain>"
  type    = "CNAME"
  records = [data.aws_lb.<lb-data-source-name>.dns_name]
}
```

**Example — add `uat-my-new-service.{yourcompany}.ai` pointing to UAT:**

```hcl
# uat-my-new-service.{yourcompany}.ai
resource "aws_route53_record" "uat-my-new-service" {
  zone_id = aws_route53_zone.{yourcompany}-ai-public.zone_id
  ttl     = var.ttl
  name    = "uat-my-new-service"
  type    = "CNAME"
  records = [data.aws_lb.{yourcompany}-ai-uat.dns_name]
}
```

**Example — add `my-new-service.{yourcompany}.ai` pointing to Production:**

```hcl
# my-new-service.{yourcompany}.ai
resource "aws_route53_record" "my-new-service" {
  zone_id = aws_route53_zone.{yourcompany}-ai-public.zone_id
  ttl     = var.ttl
  name    = "my-new-service"
  type    = "CNAME"
  records = [data.aws_lb.{yourcompany}-ai-prod.dns_name]
}
```

**Available LB data sources** (already defined in `data.tf`):

| Reference | Environment |
|---|---|
| `data.aws_lb.{yourcompany}-ai-prod.dns_name` | Production |
| `data.aws_lb.{yourcompany}-ai-uat.dns_name` | UAT / Dev |
| `data.aws_lb.{yourcompany}-ai-stag.dns_name` | Staging |

**Step 3: Name your resource block**

The resource name (the string after `aws_route53_record`) must be **unique within the entire repo**. Use the same name as the subdomain, replacing dots with dashes. Examples:
- subdomain `uat-my-service` → resource name `uat-my-service`
- subdomain `stag-my-service` → resource name `stag-my-service`

**Step 4: Plan and apply** — see [Applying Changes](#applying-changes) below.

---

### Add a New CloudFront CDN Record

If the service routes through a CloudFront distribution, you need two steps:

**Step 1: Register the CloudFront distribution in `data.tf`**

Find the CloudFront distribution ID from the AWS Console (CloudFront → Distributions → copy the ID, e.g. `E1ABC123DEF456`).

Add to `data.tf`:

```hcl
data "aws_cloudfront_distribution" "<descriptive-name>-cdn-{yourcompany}-ai" {
  id = "<CLOUDFRONT_DISTRIBUTION_ID>"
}
```

Example:

```hcl
data "aws_cloudfront_distribution" "uat-my-new-service-cdn-{yourcompany}-ai" {
  id = "E1ABC123DEF456"
}
```

**Step 2: Add the Route53 record in the appropriate records file**

```hcl
# uat-my-new-service-cdn.{yourcompany}.ai
resource "aws_route53_record" "uat-my-new-service-cdn" {
  zone_id = aws_route53_zone.{yourcompany}-ai-public.zone_id
  ttl     = var.ttl
  name    = "uat-my-new-service-cdn"
  type    = "CNAME"
  records = [data.aws_cloudfront_distribution.uat-my-new-service-cdn-{yourcompany}-ai.domain_name]
}
```

**Step 3: Plan and apply** — see [Applying Changes](#applying-changes) below.

---

### Remove a DNS Record

**Step 1: Find and delete the resource block**

Search the relevant records file for the subdomain or resource name:

```bash
grep -r "my-service" records_*.tf
```

Delete the entire `resource "aws_route53_record" "..." { ... }` block.

If the record was a CDN record, also delete its `data "aws_cloudfront_distribution" "..." { ... }` block from `data.tf`.

**Step 2: Plan and apply** — see [Applying Changes](#applying-changes) below.

Terraform will show a `destroy` action in the plan. Confirm it targets only the record you want to remove.

---

### Add a New Load Balancer Data Source

If a new Kubernetes cluster or NLB is created and you need to point DNS to it:

**Step 1: Get the LB ARN and name from AWS**

```bash
aws elbv2 describe-load-balancers --region ap-northeast-1 \
  --query 'LoadBalancers[?LoadBalancerName==`<lb-name>`].[LoadBalancerArn,DNSName]' \
  --output table
```

**Step 2: Add to `data.tf`**

```hcl
data "aws_lb" "<descriptive-name>" {
  arn  = "<LB_ARN>"
  name = "<LB_NAME>"
}
```

Example:

```hcl
data "aws_lb" "{yourcompany}-ai-newenv" {
  arn  = "arn:aws:elasticloadbalancing:ap-northeast-1:{AWS_ACCOUNT_ID}:loadbalancer/net/k8s-ingressn-ingressn-xxxx/xxxx"
  name = "{yourcompany}-ai-newenv"
}
```

**Step 3:** Reference it in your DNS records using `data.aws_lb.{yourcompany}-ai-newenv.dns_name`.

---

## Applying Changes

Always follow this sequence — never skip the plan step.

### Step 1: Format the code

```bash
terraform fmt
```

This fixes indentation and formatting. Always run this before committing.

### Step 2: Validate the configuration

```bash
terraform validate
```

Checks for syntax errors. Fix any reported errors before continuing.

### Step 3: Review the plan

```bash
terraform plan
```

Carefully read the output:
- `+ create` — a new record will be added (safe)
- `- destroy` — a record will be deleted (double-check this is intentional)
- `~ update in-place` — a record value will change (verify the new value is correct)

If the plan shows unexpected changes, investigate before applying.

### Step 4: Apply

```bash
terraform apply
```

Type `yes` when prompted. Terraform will:
1. Acquire a DynamoDB lock (to block other users during apply)
2. Make the changes in AWS Route53
3. Update the S3 state file
4. Release the lock

DNS changes typically propagate within the TTL value (default: **60 seconds**).

### Verify the change

After apply, confirm the record resolves correctly:

```bash
# Check the DNS record
dig uat-my-new-service.{yourcompany}.ai

# Or use nslookup
nslookup uat-my-new-service.{yourcompany}.ai
```

---

## Terraform State

The state file tracks what Terraform has deployed. It lives in S3 and must never be edited manually.

| Resource | Value |
|---|---|
| S3 bucket | `route53-{yourcompany}-ai-tf` |
| S3 key | `terraform.tfstate` |
| S3 region | `ap-southeast-1` |
| DynamoDB table | `route53-{yourcompany}-ai-tf-lock` |

### If someone is already running Terraform

If you get a lock error like:
```
Error: Error acquiring the state lock
```

It means someone else is running `terraform apply`. Wait for them to finish. If the lock is stale (the previous apply crashed), ask a senior DevOps to manually release it in DynamoDB.

### Never commit state files

The `.gitignore` already excludes `*.tfstate` and `*.tfstate.*`. Never force-add these files.

---

## Variables Reference

Defined in `variables.tf`:

| Variable | Default | Description |
|---|---|---|
| `region` | `ap-northeast-1` | AWS region for the Route53 provider |
| `ttl` | `60` | DNS record TTL in seconds |
| `livekit_selfhost_ip` | `13.231.124.201` | IP address of the self-hosted LiveKit server (used for A records) |

To override a variable without editing the file, use `-var`:

```bash
terraform plan -var="ttl=300"
```

---

## Troubleshooting

### `Error: Duplicate resource "aws_route53_record"`

You used the same resource name as an existing record. Choose a unique name for your new resource block.

### `Error: Reference to undeclared resource`

You referenced a `data.aws_lb.*` or `data.aws_cloudfront_distribution.*` that doesn't exist in `data.tf`. Add the data source block first, then re-run.

### `Error: Unsupported argument` or `Error: An argument named ... is not expected`

Syntax error in your HCL. Run `terraform validate` to identify the exact location.

### Plan shows unexpected destroys

Check that you haven't accidentally deleted or modified an existing resource block. Run `git diff` to review your changes before applying.

### DNS not resolving after apply

- Check the TTL — records cached for up to 60 seconds by default
- Run `dig +short <subdomain>.{yourcompany}.ai` and verify the CNAME target is correct
- Check that the target load balancer is healthy in the AWS Console

### State lock stuck

If a previous apply crashed, the DynamoDB lock may still be held. To force-unlock (use only after confirming no one else is running Terraform):

```bash
terraform force-unlock <LOCK_ID>
```

The lock ID is printed in the error message when you try to run plan/apply.
