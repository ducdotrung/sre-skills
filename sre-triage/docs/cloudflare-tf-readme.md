# cloudflare-{yourcompany}-tf

Terraform project for managing **all Cloudflare DNS zones and records** for {YourCompany}'s products. Changes to DNS (A, CNAME, MX, TXT, etc.) across all domains must go through this repository — do **not** edit records manually in the Cloudflare dashboard.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Managed Domains](#managed-domains)
3. [Prerequisites](#prerequisites)
4. [Initial Setup](#initial-setup)
5. [Project Structure](#project-structure)
6. [Day-to-Day Workflow](#day-to-day-workflow)
7. [Adding a New DNS Record](#adding-a-new-dns-record)
8. [Adding a New Domain (Zone)](#adding-a-new-domain-zone)
9. [Variables Reference](#variables-reference)
10. [Remote State](#remote-state)
11. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              This Repository (Terraform)         │
│                                                  │
│  zones.tf          → Cloudflare Zone resources   │
│  *-records.tf      → DNS records per domain      │
│  variables.tf      → Shared variables / LB ARNs  │
│  data.tf           → AWS data sources (LBs)      │
│  main.tf           → Provider config + S3 backend│
│  outputs.tf        → Zone IDs / name servers     │
└────────────────┬────────────────────────────────┘
                 │ terraform apply
                 ▼
        Cloudflare API (DNS)
                 │
       ┌─────────┴──────────┐
       │  AWS S3 (tfstate)  │  bucket: cloudflare-{your-org}-dns-tf
       │  DynamoDB (lock)   │  table:  cloudflare-dns-tf-lock
       └────────────────────┘  region: ap-southeast-1
```

Two cloud providers are configured:

| Provider    | Purpose                                              |
|-------------|------------------------------------------------------|
| Cloudflare  | Create/update DNS zones and records                  |
| AWS         | Read ALB/NLB DNS names as data sources; remote state |

---

## Managed Domains

| File                          | Domain(s)                                        |
|-------------------------------|--------------------------------------------------|
| `{yourcompany}-dev-records.tf`| {yourcompany}.dev                                |
| `zones.tf`                    | Zone definitions for all domains above           |

---

## Prerequisites

Install the following tools before you begin:

| Tool        | Min version | Install                                      |
|-------------|-------------|----------------------------------------------|
| Terraform   | >= 1.0      | `brew install terraform` (macOS)             |
| AWS CLI     | >= 2.x      | `brew install awscli`                        |
| Git         | any         | pre-installed on most systems                |

You also need:

- **Cloudflare API token** — create one at [Cloudflare Dashboard → My Profile → API Tokens](https://dash.cloudflare.com/profile/api-tokens). The token requires these permissions:
  - `Zone → DNS → Edit`
  - `Zone → Zone → Edit`
- **AWS credentials** with at least read access to the S3 bucket `cloudflare-{your-org}-dns-tf` and the DynamoDB table `cloudflare-dns-tf-lock` (ap-southeast-1), plus read access to EC2/ELB resources in ap-northeast-1 (for data sources).

---

## Initial Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd cloudflare-{yourcompany}-tf
```

### 2. Configure AWS credentials

The project uses two AWS regions. Make sure your AWS profile/env vars are configured:

```bash
# Option A — environment variables
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-southeast-1   # for S3 state backend

# Option B — named profile
aws configure --profile {yourcompany}
export AWS_PROFILE={yourcompany}
```

Verify access:

```bash
aws sts get-caller-identity
```

### 3. Create the `.auto.tfvars` file

This file is **gitignored** (never commit it). Create it in the repo root:

```hcl
# .auto.tfvars
cloudflare_api_token = "your-cloudflare-api-token-here"
```

> **Tip:** The `.auto.tfvars` suffix means Terraform loads it automatically — no `-var-file` flag needed.

### 4. Initialize Terraform

```bash
terraform init
```

This downloads the Cloudflare and AWS providers and connects to the remote S3 state backend. Expected output ends with:

```
Terraform has been successfully initialized!
```

### 5. Verify the plan runs cleanly

```bash
terraform plan
```

If you see `No changes. Your infrastructure matches the configuration.`, your setup is correct.

---

## Project Structure

```
cloudflare-{yourcompany}-tf/
├── main.tf                       # Provider versions + S3 backend
├── variables.tf                  # All input variables (LB ARNs, CDN URLs, TTLs)
├── data.tf                       # AWS data sources + locals (environment map)
├── zones.tf                      # cloudflare_zone resources (one per domain)
├── outputs.tf                    # Zone IDs and name servers
├── {yourcompany}-dev-records.tf        # DNS records for {yourcompany}.dev
├── .auto.tfvars                  # (gitignored) your API token
├── .gitignore
└── README.md
```

### TTL variables (defined in `variables.tf`)

| Variable              | Default | Use case                              |
|-----------------------|---------|---------------------------------------|
| `ttl_auto`            | 1       | Proxied records (Cloudflare manages)  |
| `ttl_app_endpoint`    | 60      | API / CMS endpoints                   |
| `ttl_cdn`             | 300     | CDN / CloudFront distributions        |
| `ttl_email`           | 600     | MX, SPF, DMARC records                |
| `ttl_verification`    | 1800    | ACM / TikTok / Google verification    |
| `ttl_dkim`            | 3600    | DKIM TXT records                      |

> **Note:** For proxied records (`proxied = true`), Cloudflare ignores TTL and always returns 300. Use `ttl_auto = 1` as a convention.

---

## Day-to-Day Workflow

Always follow this workflow — never apply unreviewed changes.

```
git pull                    # get latest state
# make your changes
terraform fmt               # format code
terraform validate          # check syntax
terraform plan              # review the diff
terraform apply             # apply after review
git add .
git commit -m "INF-XXXX Description of change"
git push
```

### Key commands

| Command              | What it does                                              |
|----------------------|-----------------------------------------------------------|
| `terraform init`     | Download providers, connect to remote backend             |
| `terraform fmt`      | Auto-format all `.tf` files                               |
| `terraform validate` | Check HCL syntax and provider schema                      |
| `terraform plan`     | Show what will change (dry run, safe to run anytime)      |
| `terraform apply`    | Apply changes to Cloudflare (prompts for confirmation)    |
| `terraform output`   | Print zone IDs and name servers                           |
| `terraform state list` | List all resources tracked in remote state              |

---

## Adding a New DNS Record

1. Open the `.tf` file for the relevant domain (e.g., `{your-domain}-ai-records.tf` for `{your-domain}.ai`).

2. Add a `cloudflare_record` block. Use the existing records as templates:

```hcl
# Short description of what this record is for
resource "cloudflare_record" "my_new_record" {
  zone_id = cloudflare_zone.{your-domain}_ai.id
  name    = "app"                  # subdomain, or "@" for root
  type    = "CNAME"                # A | CNAME | MX | TXT | etc.
  content = "example.com"         # target value
  ttl     = var.ttl_app_endpoint  # pick the right TTL variable
  proxied = true                  # true = orange cloud, false = grey cloud
}
```

3. Run the workflow:

```bash
terraform fmt
terraform plan   # verify only your record is added
terraform apply
```

### Record type quick reference

| Type  | `content` field              | `proxied` |
|-------|------------------------------|-----------|
| A     | IP address (`1.2.3.4`)       | true/false |
| CNAME | Hostname (`foo.example.com`) | true/false |
| MX    | Mail server hostname         | false      |
| TXT   | Quoted string value          | false      |

> MX and TXT records **cannot** be proxied — always set `proxied = false`.

---

## Adding a New Domain (Zone)

### Step 1 — Add the zone to `zones.tf`

```hcl
resource "cloudflare_zone" "my_new_domain_com" {
  account_id = var.account_id
  zone       = "mynewdomain.com"
  plan       = "free"
  type       = "full"
}
```

### Step 2 — Create a records file

Create `my-new-domain-com-records.tf` and add DNS records (see above).

### Step 3 — (Optional) Add outputs to `outputs.tf`

```hcl
output "my_new_domain_com_zone_id" {
  value       = cloudflare_zone.my_new_domain_com.id
  description = "Zone ID for mynewdomain.com"
}

output "my_new_domain_com_name_servers" {
  value       = cloudflare_zone.my_new_domain_com.name_servers
  description = "Name servers for mynewdomain.com"
}
```

### Step 4 — Apply and update nameservers at registrar

```bash
terraform apply
terraform output my_new_domain_com_name_servers
```

Copy the two Cloudflare nameservers printed by `terraform output` and update them at your domain registrar (e.g., GoDaddy, Namecheap). DNS propagation typically takes a few minutes to 48 hours.

---

## Variables Reference

### LB / CDN variables (in `variables.tf`)

When a load balancer or CloudFront distribution URL changes, update the default value of the corresponding variable in `variables.tf` and run `terraform apply`. This keeps the source-of-truth in one place.

| Variable                      | Description                            |
|-------------------------------|----------------------------------------|
| `{your-domain}_ai_lb_prod`            | {your-domain}.ai NLB (prod)                    |
| `{your-domain}_ai_lb_uat`             | {your-domain}.ai NLB (UAT)                     |
| `{your-domain}_ai_lb_staging`         | {your-domain}.ai NLB (staging)                 |
| `cdn_{your-domain}_ai`                | {your-domain}.ai CloudFront (prod)             |
| `cdn_{your-domain}_ai_uat`            | {your-domain}.ai CloudFront (UAT)              |
| `cdn_{your-domain}_ai_staging`        | {your-domain}.ai CloudFront (staging)          |
| `cdn_{your-domain}_ai_dev`            | {your-domain}.ai CloudFront (dev)              |

---

## Remote State

The Terraform state is stored remotely so the team shares a single source of truth:

| Setting       | Value                              |
|---------------|------------------------------------|
| Backend       | S3                                 |
| Bucket        | `cloudflare-{your-org}-dns-tf`        |
| Key           | `terraform.tfstate`                |
| Region        | `ap-southeast-1`                   |
| Lock table    | `cloudflare-dns-tf-lock` (DynamoDB)|
| Encryption    | Enabled (SSE-S3)                   |

**Never run `terraform state` destructive commands** (`rm`, `mv`, `push`) without discussing with the team first. Corrupted state can take significant effort to recover.

---

## Troubleshooting

### `Error: No valid credential sources found`

Your AWS credentials are not configured. Run `aws configure` or export the `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables.

### `Error acquiring the state lock`

Another `terraform apply` is in progress, or a previous run crashed without releasing the lock. Check with your team. If you are sure no one else is running Terraform:

```bash
terraform force-unlock <LOCK_ID>
```

The lock ID is printed in the error message.

### `Error: Invalid Cloudflare API token`

Your token in `.auto.tfvars` is wrong or expired. Generate a new one at [Cloudflare Dashboard → API Tokens](https://dash.cloudflare.com/profile/api-tokens).

### `Error: Record already exists`

A record with the same name and type already exists in Cloudflare (created manually). Either:
- Delete the manual record in the Cloudflare dashboard, then re-run `terraform apply`.
- Or import it: `terraform import cloudflare_record.<resource_name> <zone_id>/<record_id>`

### Changes show up in plan unexpectedly

Run `git pull` to make sure you have the latest `.tf` files and re-run `terraform plan`. If the diff is still unexpected, compare against the Cloudflare dashboard to identify drift from manual edits.
