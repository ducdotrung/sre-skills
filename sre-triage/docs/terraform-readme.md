# Terraform Infrastructure

This repository contains all Terraform code for managing the AWS infrastructure powering the platform. It covers networking, compute, storage, security, messaging, and Kubernetes clusters across multiple AWS regions and environments.

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Repository Structure](#repository-structure)
- [Terraform Backend](#terraform-backend)
- [Provider Configuration](#provider-configuration)
- [Environments](#environments)
- [Global Variables](#global-variables)
- [Networking (VPC)](#networking-vpc)
- [EKS Clusters](#eks-clusters)
- [EC2 Instances](#ec2-instances)
- [S3 Buckets](#s3-buckets)
- [IAM](#iam)
- [Lambda Functions](#lambda-functions)
- [Other Key Resources](#other-key-resources)
- [Reusable Modules](#reusable-modules)
- [Day-to-Day Workflows](#day-to-day-workflows)
- [Naming Conventions](#naming-conventions)
- [Git Workflow](#git-workflow)

---

## Overview

| Item | Value |
|------|-------|
| Primary AWS region | `ap-northeast-1` (Tokyo) |
| State backend | S3 `{your-tf-state-bucket}` in `ap-southeast-1` |
| State lock table | DynamoDB `{your-tf-lock-table}` |
| Environments | `dev`, `uat`, `prod` (plus `staging` for EKS) |
| Terraform version | >= 1.0 |
| AWS provider | 5.95.0 |

All 112+ Terraform configuration files live at the **root level** of this repository — there are no environment-specific subdirectories. Resources for different environments are separated within the same files using naming conventions, `for_each` maps, and local variables.

---

## Prerequisites

Before running any Terraform commands, make sure you have the following installed and configured:

| Tool | Purpose |
|------|---------|
| [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.0 | Infrastructure provisioning |
| [AWS CLI v2](https://aws.amazon.com/cli/) | Authentication, EKS token generation |
| [kubectl](https://kubernetes.io/docs/tasks/tools/) | Kubernetes cluster interaction |
| [Helm](https://helm.sh/docs/intro/install/) | Kubernetes chart management (used internally by Terraform) |

**AWS Authentication:**

You must be authenticated to the correct AWS account before running Terraform. The team uses AWS SSO. Run:

```bash
aws sso login --profile <your-profile>
```

Confirm you can reach the state bucket:

```bash
aws s3 ls s3://{your-tf-state-bucket} --region ap-southeast-1
```

---

## Repository Structure

```
terraform/
├── main.tf                     # Terraform backend + provider configuration
├── variables.tf                # Global input variables
├── data.tf                     # Data sources (VPCs, subnets, EKS clusters, AMIs)
├── output.tf                   # Output values (subnet IDs, API endpoints)
├── vpc.tf                      # VPC, subnets, NAT gateways, IGWs, VPN, peering
├── vpc-config.tf               # VPC CIDR blocks and subnet definitions (locals)
├── eks-config.tf               # EKS node group local definitions for all clusters
├── eks-{your-cluster-prefix}-prod.tf       # Production EKS cluster module call
├── eks-{your-cluster-prefix}-staging.tf    # Staging EKS cluster module call
├── eks-{your-cluster-prefix}-uat.tf        # UAT EKS cluster module call
├── eks-cluster-autoscaler-*.tf # Cluster autoscaler for prod / staging / uat
├── ec2.tf                      # General EC2 instances
├── ec2-*.tf                    # Service-specific EC2 instances
├── s3-*.tf                     # S3 buckets (one file per service)
├── iam-services-*.tf           # IAM users/policies per environment
├── iam-role-policy.tf          # IAM roles and managed policies
├── custom-policies.tf          # Custom IAM policy documents
├── sg.tf                       # Security groups
├── sg-config.tf                # Security group rule locals
├── alb-*.tf                    # Application Load Balancers
├── cloudfront.tf               # CloudFront distributions
├── acm.tf                      # ACM SSL/TLS certificates
├── api-gateway-rest.tf         # REST API Gateway
├── api-gateway-v2.tf           # HTTP API Gateway (v2)
├── ecr.tf                      # Elastic Container Registry repositories
├── lambda-*.tf                 # Lambda function resources
├── ses-*.tf                    # Simple Email Service
├── sns.tf                      # SNS topics
├── mq.tf / mq-config.tf        # Amazon MQ (RabbitMQ)
├── msk.tf                      # Managed Streaming for Kafka
├── dms-*.tf                    # Database Migration Service
├── dynamodb-tables.tf          # DynamoDB tables
├── cloudwatch.tf               # CloudWatch alarms and log groups
├── eventbridge.tf              # EventBridge rules
├── waf.tf                      # Web Application Firewall
├── modules/                    # Reusable internal Terraform modules
│   ├── solo_ec2/               # Single EC2 instance abstraction
│   ├── s3-default-perm/        # S3 bucket with access policy management
│   ├── cloudfront-s3/          # CloudFront + S3 static hosting
│   ├── ecr/                    # ECR repository wrapper
│   ├── efs-access-point/       # EFS access point
│   └── logging-system/         # Centralized logging setup
└── lambda_functions/           # Lambda function source code and zip archives
```

---

## Terraform Backend

State is stored remotely so the whole team shares a single source of truth.

```hcl
terraform {
  backend "s3" {
    bucket         = "{your-tf-state-bucket}"
    key            = "terraform.tfstate"
    dynamodb_table = "{your-tf-lock-table}"
    region         = "ap-southeast-1"   # State bucket lives in Singapore
    encrypt        = true
  }
}
```

**Important:** The state bucket is in `ap-southeast-1` (Singapore) even though most resources are in `ap-northeast-1` (Tokyo). This is intentional and must not be changed.

DynamoDB state locking prevents two engineers from running `terraform apply` at the same time. If a lock gets stuck (e.g., after a crash), you can force-unlock it with:

```bash
terraform force-unlock <LOCK_ID>
```

---

## Provider Configuration

Four AWS provider aliases are configured in `main.tf`:

| Alias | Region | Used For |
|-------|--------|----------|
| *(default)* | `ap-northeast-1` (Tokyo) | Most resources |
| `sg` | `ap-southeast-1` (Singapore) | Singapore-specific resources |
| `us-west-1` | `us-west-1` (N. California) | TTS and US-West services |
| `us-east-1` | `us-east-1` (N. Virginia) | CloudFront ACM certs (must be us-east-1) |

When creating a resource in a non-default region, pass the provider explicitly:

```hcl
module "tts-dev" {
  source    = "./modules/s3-default-perm"
  providers = { aws = aws.us-west-1 }
  # ...
}
```

A `random_string` resource (`rand_suffix`) generates a 6-character lowercase suffix appended to EKS cluster names for uniqueness. Change the `rand_me` variable to trigger regeneration.

---

## Environments

Three environments are recognized:

| Environment | Description |
|-------------|-------------|
| `dev` | Development / experimental workloads |
| `uat` | User Acceptance Testing — internal QA |
| `prod` | Production — customer-facing traffic |

A fourth label, `staging` (also abbreviated as `stag` in some resource names), is used only for the Cheercast staging EKS cluster (it sits between UAT and production in the release pipeline). You may see both spellings in file names and resource names — they refer to the same environment.

The `env` variable is validated and defaults to `uat`:

```hcl
variable "env" {
  default = "uat"
  validation {
    condition     = contains(["dev", "prod", "uat"], var.env)
    error_message = "allowed values are one of prod,dev,uat"
  }
}
```

Most resources carry the environment in their name (e.g., `tts-prod`, `tts-dev`). There is a single shared state file for all environments — not separate workspaces.

---

## Global Variables

Defined in `variables.tf`:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `region` | `string` | `ap-northeast-1` | Primary AWS region |
| `env` | `string` | `uat` | Active environment (`dev`/`uat`/`prod`) |
| `rand_me` | `number` | `0` | Increment to regenerate the EKS cluster random suffix |
| `notification_email` | `string` | `sre@{your-org}.com` | Email for SES notifications |

Pass variables on the CLI when needed:

```bash
terraform apply -var="env=prod" -var="region=ap-northeast-1"
```

---

## Networking (VPC)

Defined in `vpc.tf` and `vpc-config.tf`.

Five VPCs are managed:

| VPC Key | Name | Purpose |
|---------|------|---------|
| `main` | main | General-purpose (jump boxes, shared services) |
| `prod-ai` | prod-ai | Production AI workloads and EKS |
| `uat-ai` | uat-ai | UAT AI workloads and EKS |
| `staging-ai` | staging-ai | Staging AI workloads and EKS |
| `devops` | devops | DevOps tooling (SonarQube, monitoring, CI/CD) |

Each VPC includes:
- Public and private subnets (multiple AZs)
- Internet Gateway (IGW)
- NAT Gateway with Elastic IP for private subnet outbound traffic
- EKS-specific pod subnets and node group subnets (tagged `*eks-pod*`, `*eks-nodegroup*`)
- VPC peering connections between environments as needed
- VPN gateway for site-to-site VPN access

**Subnet tagging matters for EKS.** The AWS Load Balancer Controller and EKS auto-discovery rely on specific subnet tags. These are configured via `vpc-config.tf` locals.

---

## EKS Clusters

Three Kubernetes clusters are managed, each using the internal `terraform-eks-module`:

| Cluster | File | Environment | Node pools |
|---------|------|-------------|------------|
| `{your-cluster-prefix}-prod-<suffix>` | `eks-{your-cluster-prefix}-prod.tf` | Production | management, green/blue, livekit-agent, recorder-agent, dify |
| `{your-cluster-prefix}-staging-<suffix>` | `eks-{your-cluster-prefix}-staging.tf` | Staging | management, green/blue, livekit-agent, recorder-agent |
| `{your-cluster-prefix}-uat-<suffix>` | `eks-{your-cluster-prefix}-uat.tf` | UAT | management, green/blue, livekit-agent, recorder-agent, dify |

### EKS Module Source

All three clusters use the same private module:

```hcl
module "eks_prod" {
  source = "git::https://github.com/{your-github-org}/terraform-eks-module.git?ref=v1.3.7"
  # ...
}
```

See the [terraform-eks-module README](https://github.com/{your-github-org}/terraform-eks-module/blob/main/README.md) for full module documentation.

### Node Pool Design

Node groups are defined as locals in `eks-config.tf` and passed to the EKS module:

| Node Pool | Instance | Purpose | Taint |
|-----------|----------|---------|-------|
| `management` | t3.medium | System pods (CoreDNS, ALB, ESO, S3-CSI) | `workload=management:NoSchedule` |
| `green` / `blue` | m6a.2xlarge | General application workloads | None |
| `livekit-agent` | c6a.2xlarge | LiveKit media processing (high CPU) | `{your-org}.com/project=livekit-agent:NoSchedule` |
| `recorder-agent` | c6a.2xlarge | Recording agents | `{your-org}.com/project=recorder-agent:NoSchedule` |
| `dify` | m6a.xlarge | Dify AI platform | `workload=dify:NoSchedule` |

**Cluster autoscaler** is deployed separately for each cluster via `eks-cluster-autoscaler-*.tf` files. It scales node groups within their configured `min_size`/`max_size` bounds.

### Accessing Clusters

After a `terraform apply`, kubeconfig is auto-generated to `~/.kube/{env}_config`.

To switch between clusters:

```bash
export KUBECONFIG=~/.kube/prod_config
kubectl get nodes
```

---

## EC2 Instances

EC2 instances are created using the `./modules/solo_ec2` wrapper (`ec2.tf` and `ec2-*.tf`).

Notable instances:

| Instance Name | Type | Purpose |
|---------------|------|---------|
| `prod-jump-box` | t2.micro | SSH bastion for production VPC |
| `a10-llm` | g5.xlarge | GPU instance for LLM inference |
| `ec2-redis-*` | Various | Standalone Redis for specific services |
| `ec2-rabbitmq-*` | Various | Standalone RabbitMQ (MQ) |
| `ec2-livekit-selfhosted` | Various | Self-hosted LiveKit media server |
| `sonarqube` | Various | Code quality scanning in devops VPC |

The `solo_ec2` module manages security group assignment, subnet placement, EBS root volume sizing, optional Elastic IPs, and environment tagging automatically.

---

## S3 Buckets

S3 buckets are managed in individual `s3-*.tf` files — one file per service. All buckets use the `./modules/s3-default-perm` module which provides:

- Bucket creation with server-side encryption
- Public access blocking (all four settings)
- CORS configuration where needed
- IAM whitelist: full-access identifiers (IAM roles/users) and IP-based access restrictions
- Optional cross-region replication

Examples of buckets managed:

| File | Bucket(s) | Service |
|------|-----------|---------|
| `s3-tts.tf` | `tts-dev`, `tts-prod` | Text-to-Speech audio storage |
| `s3-video-gen.tf` | `video-gen-*` | AI video generation output |
| `s3-livekit-agent.tf` | `livekit-agent-*` | LiveKit agent recordings |
| `s3-llm-agent.tf` | `llm-agent-*` | LLM agent artifacts |
| `s3-streaming-process.tf` | `streaming-process-*` | Stream processing data |

Each IAM user that needs programmatic S3 access is declared in the same `s3-*.tf` file alongside the bucket, e.g.:

```hcl
resource "aws_iam_user" "tts-dev" {
  name = "tts-dev"
}

module "tts-dev" {
  source = "./modules/s3-default-perm"
  providers = { aws = aws.us-west-1 }
  bucket_name = "tts-dev"
  white_list_full_access_identifiers = [
    aws_iam_user.tts-dev.arn,
    "arn:aws:iam::ACCOUNT_ID:role/AWSReservedSSO_tts-developers_...",
  ]
  whitelist_ips = ["192..."]
}
```

---

## IAM

IAM configuration is split across several files:

| File | Contents |
|------|----------|
| `iam-services-dev.tf` | IAM users and policies for dev-environment services |
| `iam-services-staging.tf` | IAM users and policies for staging services |
| `iam-services-uat.tf` | IAM users and policies for UAT services |
| `iam-services-prod.tf` | IAM users and policies for production services |
| `iam-role-policy.tf` | IAM roles with assume-role policies |
| `custom-policies.tf` | Custom managed IAM policy documents |

IRSA (IAM Roles for Service Accounts) roles for Kubernetes pods are created by the `terraform-eks-module` for each cluster. They follow the pattern `{cluster_name}-{component}` (e.g., `{prod-cluster-name}-alb-controller`).

---

## Lambda Functions

Lambda function code lives in `lambda_functions/`. Terraform manages:

| File | Function | Purpose |
|------|----------|---------|
| `lambda-ffmpeg-function.tf` | FFmpeg processor | Video transcoding triggered by S3 events |
| `lambda-dms.tf` | DMS task manager | Starts/stops DMS replication tasks |
| `lambda-ses-event-processor.tf` | SES event handler | Processes SES delivery/bounce notifications |
| `lambda-ses-bounce-api.tf` | Bounce API | HTTP API for querying SES bounce records |

Lambda `.zip` archives are committed to the repository (tracked in git). When updating function code, rebuild the zip locally and commit it:

```bash
cd lambda_functions/<function-name>
zip -r ../function.zip .
```

---

## Other Key Resources

### CloudFront & ACM

- `cloudfront.tf` — All CloudFront distributions (CDN for static assets, custom origins)
- `acm.tf` — ACM certificates (note: certificates used by CloudFront **must** be created in `us-east-1`)

### API Gateway

- `api-gateway-rest.tf` — REST APIs (v1)
- `api-gateway-v2.tf` — HTTP APIs (v2) with Lambda integrations

### Messaging

- `mq.tf` / `mq-config.tf` — Amazon MQ (RabbitMQ broker) for async message queuing
- `msk.tf` — Amazon MSK (Managed Kafka) for streaming pipelines

### Database Migration Service

- `dms-*.tf` — DMS replication instances, endpoints, and tasks for database migrations

### Email & Notifications

- `ses-*.tf` — SES sending identities, DKIM, and event configurations per service
- `sns.tf` — SNS topics for alerting and fan-out
- `ses-monitoring.tf` — CloudWatch alarms for SES bounce/complaint rates

### Security

- `sg.tf` — All security groups (large file, organized by service)
- `waf.tf` — WAF web ACLs for ALBs and CloudFront distributions
- `cloudwatch.tf` — CloudWatch log groups, metric alarms
- `eventbridge.tf` — EventBridge rules for event-driven automation

### Container Registry

- `ecr.tf` — All ECR repositories for Docker images, with lifecycle policies

---

## Reusable Modules

Located in `./modules/`:

### `solo_ec2`

Creates a single EC2 instance with sensible defaults.

**Key variables:**

| Variable | Description |
|----------|-------------|
| `name` | Instance name (also used for tagging) |
| `instance_type` | EC2 instance type |
| `vpc_security_group_ids` | List of security group IDs |
| `subnet_id` | Subnet to launch in |
| `env` | Environment tag |
| `root_volume_size` | Root EBS volume size in GiB |
| `delete_root_on_termination` | Whether to delete EBS on terminate (default: true) |
| `associate_public_ip_address` | Attach a public IP (default: false) |
| `key_name` | SSH key pair name |

### `s3-default-perm`

Creates an S3 bucket with opinionated IAM access control.

**Key variables:**

| Variable | Description |
|----------|-------------|
| `bucket_name` | S3 bucket name |
| `white_list_full_access_identifiers` | IAM ARNs with full bucket access |
| `white_list_read_only_identifiers` | IAM ARNs with read-only access |
| `whitelist_ips` | IP addresses allowed to access the bucket |

### `cloudfront-s3`

Pairs a CloudFront distribution with an S3 origin for static content hosting.

### `ecr`

Creates an ECR repository with a lifecycle policy to limit stored image count.

### `efs-access-point`

Creates an EFS access point for POSIX-compliant container filesystem access.

### `logging-system`

Sets up centralized logging infrastructure (CloudWatch log groups and subscriptions).

---

## Day-to-Day Workflows

### Initial Setup (first time)

```bash
# Clone the repo
git clone git@github.com:{your-org}/terraform.git
cd terraform

# Initialize Terraform (downloads providers, connects to backend)
terraform init

# Verify you can see the existing plan without changes
terraform plan
```

### Making Infrastructure Changes

```bash
# 1. Create a feature branch (follow git workflow below)
git checkout -b INF-XXXX-short-description

# 2. Edit the relevant .tf file(s)
# 3. Format your code
terraform fmt

# 4. Validate syntax
terraform validate

# 5. Preview changes — ALWAYS do this before applying
terraform plan

# 6. Apply changes
terraform apply

# 7. Commit and open a PR
git add <changed-files>
git commit -m "INF-XXXX #time 30m Short description"
```

### Targeting Specific Resources

To apply changes to a single resource without touching others:

```bash
terraform apply -target=module.tts-dev
terraform apply -target=aws_iam_user.tts-dev
```

### Refreshing State

If AWS resources were changed outside Terraform:

```bash
terraform refresh
```

### Importing Existing Resources

If a resource was created manually and needs to come under Terraform management:

```bash
terraform import aws_s3_bucket.example my-existing-bucket-name
```

### Destroying Resources

**Use with caution.** Always target specific resources — never run `terraform destroy` without `-target`:

```bash
terraform destroy -target=module.old-service-dev
```

---

## Naming Conventions

| Resource | Pattern | Example |
|----------|---------|---------|
| EKS cluster | `{service}-{env}-{6-char-random}` | `{prod-cluster-name}` |
| EC2 instance | `{service}-{env}` | `redis-prod`, `jump-box-prod` |
| S3 bucket | `{service}-{env}` | `tts-dev`, `livekit-agent-prod` |
| IAM user | `{service}-{env}` | `tts-dev`, `ai-be-staging` |
| IAM role | `{cluster}-{component}` | `{prod-cluster-name}-alb-controller` |
| Security group | descriptive name | `prod_bastion_allowed_ssh` |
| VPC | `{name}-ai` | `prod-ai`, `uat-ai` |
| Terraform file | `{resource-type}-{service}.tf` | `s3-tts.tf`, `ec2-redis.tf` |

---

## Git Workflow

All commits reference a Jira issue in the `INF` project with time tracking:

```
INF-XXXX #time 30m Short description of what changed
```

Examples from recent history:
```
INF-6933 Upgrade EKS cluster PROD to version 1.34
INF-6984 #time 1h Update S3 bucket CORS settings for Twomi support TV show staging
INF-6959 #time 30m Add permission for ai-be staging read write s3 livekit staging
```

**Branch naming:** `INF-XXXX-short-description`

**Recommended review checklist before merging:**
- `terraform fmt` — no formatting issues
- `terraform validate` — no syntax errors
- `terraform plan` output reviewed and attached to the PR
- No sensitive data (secrets, private keys) committed — see `.gitignore`
- State-altering operations (destroy, rename) flagged explicitly in the PR description
