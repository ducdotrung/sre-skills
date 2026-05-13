# Cloudflare Zero Trust — Terraform

Manages Cloudflare Zero Trust (WARP VPN) settings for {YourCompany} / AI Avatar via Terraform.  
All changes go through code review — never edit settings directly in the Cloudflare dashboard.

Related Jira project: `INF-*` tickets in [Castalk Jira](https://{your-org}.atlassian.net)

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure](#project-structure)
3. [First-time Setup](#first-time-setup)
4. [How It Works — Architecture Overview](#how-it-works--architecture-overview)
5. [Common Tasks](#common-tasks)
   - [Grant VPN access to a new user](#1-grant-vpn-access-to-a-new-user)
   - [Revoke VPN access from a user](#2-revoke-vpn-access-from-a-user)
   - [Add a new private IP route](#3-add-a-new-private-ip-route)
   - [Add a new split-tunnel exclusion](#4-add-a-new-split-tunnel-exclusion)
6. [Applying Changes](#applying-changes)
7. [User Groups Reference](#user-groups-reference)
8. [Device Policy Reference](#device-policy-reference)
9. [Terraform State Backend](#terraform-state-backend)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Terraform | >= 1.3 | `brew install terraform` |
| AWS CLI | >= 2 | `brew install awscli` |
| AWS credentials | — | Must have access to `{your-org}-cloudflare-zero-trust-tf` S3 bucket (ap-southeast-1) |

You also need a Cloudflare API token (see [First-time Setup](#first-time-setup)).

---

## Project Structure

```
.
├── main.tf                        # Terraform backend (S3) + Cloudflare provider
├── variables.tf                   # Input variable declarations
├── data.tf                        # Local variables: users, policy configs, IP lists
├── device_settings.tf             # cloudflare_device_settings_policy resources
├── access_policies.tf             # Device enrollment access policies
├── routes.tf                      # Tunnel routes (private IP → tunnel mappings)
├── split-tunnel-Default.tf        # Split tunnel for the Default policy (include mode)
├── split-tunnel-{yourcompany}-default.tf
├── split-tunnel-{yourcompany}-sre.tf
├── split-tunnel-{yourcompany}-ai-team.tf
├── split-tunnel-jp-team.tf
├── split-tunnel-jp-freelancer.tf
├── split-tunnel-partner.tf
└── local_data/
    └── tunnels/
        └── eks-{your-cluster-prefix}-uat/
            └── private_networks/   # Plain-text IP lists loaded by data.tf
                ├── ec2.txt         # EC2 instance IPs
                ├── eks-{your-cluster-prefix}-uat.txt
                ├── ai-avatar.txt
                ├── s3_ips.txt
                └── smtp_ips.txt
```

### Key concepts

- **Device policy** (`data.tf` → `policy_configs`) — a named WARP profile assigned to a set of users.  
  Each policy controls which traffic goes through the tunnel (via split tunnels) and DNS fallback domains.
- **Split tunnel** (`split-tunnel-*.tf`) — per-policy rules for which hosts/CIDRs bypass (`exclude` mode) or are forced through (`include` mode) the tunnel.
- **Tunnel routes** (`routes.tf`) — maps private IP ranges to the `eks-{your-cluster-prefix}-uat` Cloudflare Tunnel so WARP clients can reach them.
- **Enrollment policy** (`access_policies.tf`) — controls which email addresses / domains are allowed to enroll a device into WARP.

---

## First-time Setup

### 1. Create a Cloudflare API Token

1. Go to [Cloudflare → Profile → API Tokens](https://dash.cloudflare.com/profile/api-tokens).
2. Click **Create Token** → **Custom Token**.
3. Add the following permissions:

   | Permission | Level |
   |-----------|-------|
   | Cloudflare Tunnel | Edit |
   | Zero Trust | Edit |

4. Set **Account Resources** to the {YourCompany} account.
5. Click **Continue to summary** → **Create Token** and copy the token.

### 2. Create the `.auto.tfvars` file

In the repo root, create a file named `terraform.auto.tfvars` (it is git-ignored):

```hcl
cloudflare_api_token = "your-token-here"
```

> `.auto.tfvars` files are loaded automatically by Terraform. Do **not** commit this file.

### 3. Configure AWS credentials

The Terraform state is stored in S3 (ap-southeast-1). Make sure your AWS profile has read/write access:

```bash
aws s3 ls s3://{your-org}-cloudflare-zero-trust-tf   # should list the state file
```

### 4. Initialise Terraform

```bash
terraform init
```

Expected output ends with:
```
Terraform has been successfully initialized!
```

---

## How It Works — Architecture Overview

```
data.tf
  └─ local.users           (email lists per team)
  └─ local.policy_configs  (maps team → precedence, users, fallback DNS)
  └─ local.*_ips           (IP lists read from local_data/*.txt files)

device_settings.tf         → cloudflare_device_settings_policy  (one per team)
access_policies.tf         → cloudflare_zero_trust_access_policy (enrollment rules)
routes.tf                  → cloudflare_tunnel_route              (private IP routing)
split-tunnel-*.tf          → cloudflare_split_tunnel              (per-policy traffic rules)
```

When a user connects with Cloudflare WARP:
1. Cloudflare matches their email to a **device policy** (by precedence order).
2. The policy's **split tunnel** rules decide which traffic goes through the tunnel.
3. For private IPs in the tunnel, **tunnel routes** forward the traffic to `eks-{your-cluster-prefix}-uat`.

---

## Common Tasks

### 1. Grant VPN access to a new user

**Step 1 — Decide which team the user belongs to** (see [User Groups Reference](#user-groups-reference)).

**Step 2 — Add their email to `data.tf`**

Open `data.tf` and find the `users` local block. Add the email to the correct list:

```hcl
# Example: adding someone to {your-company}_default
{your-company}_default = [
  ...existing emails...,
  "newuser@{your-org}.com",   # ← add here
]
```

**Step 3 — Check enrollment policy**

Most `@{your-org}.com` addresses are covered by the existing `{your-org}` enrollment policy. For other domains (e.g. `@a*.work`, `@s*.com`), verify the email is included in the matching `enrollment_policy_configs` block in `data.tf`.

**Step 4 — Apply** (see [Applying Changes](#applying-changes))

---

### 2. Revoke VPN access from a user

**Step 1 — Remove the email from `data.tf`**

Find the email in the `users` local block and delete that line.

**Step 2 — Apply** (see [Applying Changes](#applying-changes))

> Revoking from `users` removes the person from the device policy match rule. Their enrolled device will lose access on the next policy sync (usually within a few minutes).

---

### 3. Add a new private IP route

Private IP routes tell Cloudflare which CIDRs should be reachable through the `eks-{your-cluster-prefix}-uat` tunnel.

**Step 1 — Add the IP to the appropriate text file under `local_data/`**

Format: one entry per line — `<CIDR>  # optional comment`

```
10.0.5.0/24  # new-service-subnet
```

Available files:

| File | Used for |
|------|---------|
| `ec2.txt` | EC2 instance IPs |
| `eks-{your-cluster-prefix}-uat.txt` | EKS pod/service CIDRs |
| `ai-avatar.txt` | AI Avatar cluster IPs |
| `s3_ips.txt` | S3 endpoint IPs |
| `smtp_ips.txt` | SMTP relay IPs |

**Step 2 — Apply** (see [Applying Changes](#applying-changes))

---

### 4. Add a new split-tunnel exclusion

Split tunnels control which traffic bypasses (or is forced through) the tunnel for a specific policy.

**Step 1 — Open the right split-tunnel file** for the affected policy:

| File | Policy |
|------|--------|
| `split-tunnel-Default.tf` | Default (all other users) |
| `split-tunnel-{yourcompany}-default.tf` | {YourCompany} general staff |
| `split-tunnel-{yourcompany}-sre.tf` | SRE team |
| `split-tunnel-{yourcompany}-ai-team.tf` | AI team |
| `split-tunnel-jp-team.tf` | JP team |
| `split-tunnel-jp-freelancer.tf` | JP freelancers |
| `split-tunnel-partner.tf` | Partner |

**Step 2 — Add a `tunnels` block**

For a hostname exclusion:
```hcl
tunnels {
  address     = null
  description = "brief description"
  host        = "example.com"
}
```

For a CIDR exclusion:
```hcl
tunnels {
  address     = "10.0.5.0/24"
  description = "brief description"
  host        = null
}
```

**Step 3 — Apply** (see [Applying Changes](#applying-changes))

---

## Applying Changes

Always run `plan` before `apply` and review the diff carefully.

```bash
# Preview what will change
terraform plan

# Apply after reviewing the plan output
terraform apply
```

When prompted `Do you want to perform these actions?`, type `yes` to confirm.

> For user additions/removals, the plan will show an **in-place update** to the affected `cloudflare_device_settings_policy` resource (the `match` string changes). This is expected and safe.

### Commit message convention

Follow the existing pattern: `INF-<ticket> <short description>`

```
INF-6868 Add VPN for new members
INF-6668 Remove VPN access - John
```

---

## User Groups Reference

| Group key | Description | Domain(s) |
|-----------|-------------|-----------|
| `{your-company}_default` | All general {YourCompany} staff | `@{your-org}.com`, `-company.com` |
| `{your-company}_sre` | SRE / DevOps team | `@{your-org}.com` |
| `{your-company}_ai_team` | AI / ML team | `@{your-org}.com` |
| `jp_team` | Japan team | `@{your-org}.com`, `@aiavatar.work`, `@suzuverse.com` |
| `partner` | External partners | `@suzuverse.com` |
| `jp_freelancer` | Japan freelancers | mixed |

Policies are matched in **precedence order** (1 = highest). A user who appears in multiple lists will be matched by the highest-precedence policy.  
The `Default` policy catches everyone else and has no explicit user list.

---

## Device Policy Reference

| Policy | Precedence | Split tunnel mode | Notes |
|--------|-----------|-------------------|-------|
| `{your-company}_sre` | 2 | `exclude` | Many sites excluded (GitHub, Google, Slack, etc.) |
| `{your-company}_default` | 1 | `exclude` | Standard exclusions |
| `{your-company}_ai_team` | 3 | `exclude` | Similar to default |
| `jp-team` | 5 | `exclude` | JP-specific exclusions |
| `partner` | 6 | `exclude` | — |
| `jp-freelancer` | 7 | `exclude` | — |
| `Default` | — | `include` | Include-mode: only listed hosts go through tunnel |

All policies share the same base settings defined in `local.policy_defaults` in `data.tf`.

---

## Terraform State Backend

State is stored remotely so the team shares a single source of truth.

| Setting | Value |
|---------|-------|
| S3 bucket | `{your-org}-cloudflare-zero-trust-tf` |
| State key | `terraform.tfstate` |
| Region | `ap-southeast-1` |
| Lock table | `{your-org}-cloudflare-zero-trust-tf-lock` (DynamoDB) |
| Encryption | Enabled (AES-256) |

The DynamoDB lock prevents two people from running `terraform apply` at the same time.  
If a lock is stuck (e.g. after a crash), check the DynamoDB table and delete the lock item manually — but confirm no one else is running `apply` first.

---

## Troubleshooting

### `Error: No valid credential sources found`
Your AWS credentials are not configured. Run `aws configure` or export `AWS_PROFILE`.

### `Error acquiring the state lock`
Someone else (or a crashed process) holds the Terraform lock. Check with the team, then manually release via the DynamoDB console if confirmed safe.

### `Error: Invalid API Token`
The token in `terraform.auto.tfvars` is wrong or expired. Generate a new one following [First-time Setup](#first-time-setup).

### User connected but can't reach a private IP
1. Check the IP is in a `.txt` file under `local_data/tunnels/eks-{your-cluster-prefix}-uat/private_networks/`.
2. Check the IP is **not** in the user's split-tunnel exclude list.
3. Run `terraform plan` to verify the route exists.

### Changes applied but user's WARP client didn't update
Cloudflare WARP policies sync automatically, but it can take 1–5 minutes. Ask the user to toggle WARP off and on again to force a re-sync.
