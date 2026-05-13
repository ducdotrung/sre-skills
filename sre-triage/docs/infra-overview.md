# {YourCompany} DevOps System — Overview & Onboarding Guide

> **Audience:** New DevOps engineers joining {YourCompany}.  
> **Purpose:** High-level map of the entire DevOps landscape — infrastructure, CI/CD, Kubernetes, observability, and day-to-day operations. Each section links to the relevant repository or README for deeper detail.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Map](#2-repository-map)
3. [AWS Infrastructure (Terraform)](#3-aws-infrastructure-terraform)
4. [Kubernetes Clusters (EKS)](#4-kubernetes-clusters-eks)
5. [CI/CD Pipeline](#5-cicd-pipeline)
6. [GitOps & Deployment (k8s-manifest)](#6-gitops--deployment-k8s-manifest)
7. [DNS Management](#7-dns-management)
8. [Secrets Management](#8-secrets-management)
9. [Observability](#9-observability)
10. [DevOps Servers ({DEVOPS_SERVER_1} & {APM_SERVER})](#10-devops-servers)
11. [Self-Hosted GitHub Runner ({GITHUB_RUNNER_SERVER})](#11-self-hosted-github-runner-101021​3)
12. [Environments Summary](#12-environments-summary)
13. [Common Day-to-Day Tasks](#13-common-day-to-day-tasks)
14. [Key Contacts & Access](#14-key-contacts--access)

---

## 1. System Overview

{YourCompany} runs a multi-product, multi-environment platform on AWS. All infrastructure is managed as code. The high-level architecture looks like this:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Developer pushes code to GitHub                                    │
│         │                                                           │
│         ▼                                                           │
│  GitHub Actions (self-hosted runner on {GITHUB_RUNNER_SERVER})                  │
│    1. Lint / Test                                                   │
│    2. Build Docker image → push to AWS ECR                          │
│    3. Call Argo Deployer API → update image tag in k8s-manifest     │
│         │                                                           │
│         ▼                                                           │
│  ArgoCD (running in EKS) detects git change                         │
│    → auto-sync (dev/uat) or manual-sync (staging/prod)             │
│    → Kubernetes rolls out new deployment                            │
└─────────────────────────────────────────────────────────────────────┘

AWS Infrastructure:
  VPC (5x)  ──►  EKS Clusters (prod-ai, uat-ai, staging-ai, devops)
                      │
              ┌───────┼───────┐
           RDS (MySQL/PG)  Amazon MQ (RabbitMQ)
           ElastiCache(Redis) MSK (Kafka)
           S3  CloudFront  ECR  SES  Lambda
```

All AWS resources are provisioned via Terraform. All Kubernetes workloads (90+ microservices) are managed via the `k8s-manifest` repository.

---

## 2. Repository Map

| Repository | Purpose | README |
|---|---|---|
| `github.com/{your-github-org}/terraform` | All AWS infrastructure (VPCs, EKS, RDS, S3, IAM, etc.) | [README](https://github.com/{your-github-org}/terraform) |
| `github.com/{your-github-org}/terraform-eks-module` | Reusable Terraform module to provision an EKS cluster with standard add-ons | [README](https://github.com/{your-github-org}/terraform-eks-module) |
| `github.com/{your-github-org}/k8s-manifest` | All Kubernetes manifests — Helm, ArgoCD, Kustomize | [README](https://github.com/{your-github-org}/k8s-manifest) |
| `github.com/{your-github-org}/cloudflare-{yourcompany}-tf` | Cloudflare DNS zones and records for all {YourCompany} domains | [README](https://github.com/{your-github-org}/cloudflare-{yourcompany}-tf) |
| `github.com/{your-github-org}/route53-{your-org}-com-tf` | AWS Route 53 DNS records for `{your-org}.com` | [README](https://github.com/{your-github-org}/route53-{your-org}-com-tf) |
| `github.com/{your-github-org}/route53-{yourcompany}-ai-tf` | AWS Route 53 DNS records for `{yourcompany}.ai` | [README](https://github.com/{your-github-org}/route53-{yourcompany}-ai-tf) |
| `github.com/{your-github-org}/cloudflare-zero-trust-tf` | Cloudflare Zero Trust configuration (access policies, tunnels) | [README](https://github.com/{your-github-org}/cloudflare-zero-trust-tf) |
| `github.com/{your-github-org}/action-docker-build` | Reusable GitHub Action for building and pushing Docker images to ECR | — |
| `github.com/{your-github-org}/argo-deployer` | HTTP API service that receives a deploy trigger and commits the new image tag to `k8s-manifest` | — |

---

## 3. AWS Infrastructure (Terraform)

**Repo:** `github.com/{your-github-org}/terraform`

All 112+ Terraform configuration files live at the **root level** of the repository (no subdirectories per environment). Different environments are separated by naming conventions and `for_each` maps within the same state.

### State Backend

| Item | Value |
|---|---|
| S3 Bucket | `{your-tf-state-bucket}` |
| Region | `ap-southeast-1` (Singapore) — intentional, do not change |
| DynamoDB Lock Table | `{your-tf-lock-table}` |

### AWS Regions in Use

| Alias | Region | Used For |
|---|---|---|
| *(default)* | `ap-northeast-1` (Tokyo) | Most resources |
| `sg` | `ap-southeast-1` (Singapore) | Singapore-specific resources |
| `us-west-1` | N. California | TTS S3 buckets |
| `us-east-1` | N. Virginia | CloudFront ACM certificates |

### Key Infrastructure Components

**Networking:** Five VPCs are managed — `main`, `prod-ai`, `uat-ai`, `staging-ai`, and `devops`. Each has public/private subnets, IGW, NAT Gateway, and EKS-specific subnet tags. VPC peering connects environments as needed.

**EKS Clusters:** Provisioned via the `terraform-eks-module` (see Section 4). Each cluster is defined in a dedicated `eks-*.tf` file.

**Storage:**
- S3 buckets are defined in `s3-*.tf` files (one file per service). All use the `./modules/s3-default-perm` module with encryption, public-access blocking, and IAM whitelisting.
- EFS access points for stateful container filesystems.

**Messaging & Streaming:**
- **Amazon MQ (RabbitMQ):** `mq.tf` / `mq-config.tf` — async message queuing across all environments.
- **Amazon MSK (Kafka):** `msk.tf` — streaming pipelines (e.g., `buzzencer-prod-msk`, Kafka 3.6.0).

**Databases:** RDS MySQL and PostgreSQL instances per environment (defined in `sg.tf` security groups and separate RDS config files).

**Compute:**
- EC2 instances via `./modules/solo_ec2` (jump boxes, utility servers).
- Lambda functions in `lambda_functions/` — FFmpeg processing, DMS task manager, SES event handling.

**Container Registry:** ECR repositories with lifecycle policies — one per service, defined in `ecr.tf`.

**CDN & Certificates:** CloudFront distributions (`cloudfront.tf`) + ACM certificates (`acm.tf`, must be `us-east-1` for CloudFront).

**Email:** SES sending identities, DKIM, bounce/complaint monitoring via CloudWatch alarms.

**Security:** WAF web ACLs for ALBs and CloudFront. All security groups centralized in `sg.tf`.

### Authentication

The team uses **AWS SSO**. Authenticate before running Terraform:

```bash
aws sso login --profile <your-profile>
```

### Basic Workflow

```bash
git checkout -b INF-XXXX-description
# Make changes
terraform fmt && terraform validate
terraform plan        # Always review before applying
terraform apply
git add . && git commit -m "INF-XXXX #time 30m Description"
# Open PR for review
```

---

## 4. Kubernetes Clusters (EKS)

**Module:** `github.com/{your-github-org}/terraform-eks-module`

All EKS clusters are provisioned using the shared `terraform-eks-module`, which wraps the official `terraform-aws-modules/eks/aws` (~> 20.0) with {YourCompany}'s standard add-ons pre-configured.

### Cluster Inventory

| Cluster | VPC | Environment |
|---|---|---|
| `{prod-cluster-name}` | `prod-ai` | Production |
| `{uat-cluster-name}` | `uat-ai` | UAT + Dev (shared cluster, separate namespaces) |
| `{staging-cluster-name}` | `staging-ai` | Staging |

*The 6-char suffix (`yazvvz`) was generated once via Terraform's `random_string` resource and is fixed unless explicitly regenerated. Kubeconfigs are saved to `~/.kube/{env}_config`.*

### Every Cluster Includes

**Managed Add-ons (version-pinned):**

| Add-on | Version |
|---|---|
| CoreDNS | v1.13.2-eksbuild.4 |
| kube-proxy | v1.33.x |
| VPC-CNI (with NetworkPolicy) | v1.21.1-eksbuild.7 |
| EBS CSI Driver | v1.58.0-eksbuild.1 |

**Helm Releases (auto-installed by module):**

| Chart | Purpose |
|---|---|
| AWS Load Balancer Controller v2.17.1 | ALB/NLB ingress |
| External Secrets Operator v0.20.3 | Sync AWS Secrets Manager → K8s Secrets |
| Mountpoint S3 CSI Driver 2.5.0 | Mount S3 buckets as pod volumes |

**IRSA Roles:** Each cluster has dedicated IAM roles for `vpc-cni`, `ebs-csi`, `efs-csi`, `alb-controller`, `external-secrets`, and `s3-csi` service accounts.

### Node Group Convention

All system-level pods (CoreDNS, ALB controller, External Secrets) run on **management nodes** and are isolated using:

```yaml
nodeSelector:
  nodegroup: management
tolerations:
  - key: workload
    value: management
    effect: NoSchedule
```

This keeps management workloads separated from application workloads.

---

## 5. CI/CD Pipeline

### Overview

Every application repository on GitHub contains environment-specific workflow files under `.github/workflows/`. The pipelines follow a consistent 3-job pattern:

```
prepare  ──►  build-and-push  ──►  deploy
```

All jobs run on **self-hosted GitHub runners** (label: `{your-org}`) hosted on the server at `{GITHUB_RUNNER_SERVER}` (see Section 11).

### Trigger Rules

| Workflow | Trigger |
|---|---|
| `dev` | PR merged to `dev` branch |
| `uat` | PR merged to `uat`/`develop` branch |
| `staging` | PR merged to `staging` branch |
| `prod` / `release` | Git tag pushed matching `v*` |

### Image Tagging Convention

| Environment | Tag Format | Example |
|---|---|---|
| dev | `{short-sha}-dev-{YYMMDD.HHmm}` | `a1b2c3d-dev-250418.1430` |
| uat | `{short-sha}-uat-{YYMMDD}` | `a1b2c3d-uat-250418` |
| staging | `{short-sha}-staging` | `a1b2c3d-staging` |
| prod/release | `{git-tag}` (e.g. `v1.2.3`) | `v1.2.3` |

### Custom Actions

| Action | Purpose |
|---|---|
| `{your-org}/action-docker-build@v1` | Wraps `docker buildx build` + ECR push with AWS auth |
| `{your-org}/argo-deployer@v2` | Calls the Argo Deployer HTTP API to commit the new image tag to `k8s-manifest` |

### Argo Deployer

`argo-deployer` is a lightweight HTTP API service running inside the cluster. When called by the GitHub Actions `deploy` job, it:

1. Receives the `application`, `environment`, and `image_tag` parameters.
2. Commits the new image tag to `argocd/overlays/{env}/apps/{app}.yaml` in the `k8s-manifest` repo.
3. ArgoCD detects the commit and syncs the cluster.

You will see automated commits in `k8s-manifest` git history like:

```
[Argo Deployer] Update cc-backend to a1b2c3d-uat on uat
```

### Some Apps Have Additional Steps

More complex apps (e.g., Python services) run lint and test jobs before the build:

```
prepare  ──►  lint  ──►  test  ──►  build-and-push  ──►  deploy
```

---

## 6. GitOps & Deployment (k8s-manifest)

**Repo:** `github.com/{your-github-org}/k8s-manifest`

This repo is the single source of truth for all Kubernetes workloads — **90+ microservices** across `dev`, `uat`, `staging`, and `prod`.

### Three Deployment Strategies

| Strategy | Used For | How to Apply |
|---|---|---|
| **Helm + Helmfile** | Infrastructure tools: ArgoCD, Ingress Nginx, Cert-Manager, Prometheus, Filebeat, LiveKit, Dify | `helmfile apply` (manual) |
| **ArgoCD (GitOps)** | All actively developed application services | Automatic — Argo Deployer commits → ArgoCD syncs |
| **Kustomize** | Stable services (`argo-deployer`, `{your-org}-api`) and infra components | `kubectl apply -k` (manual) |

### End-to-End Deployment Flow

```
Developer pushes code
        │
        ▼
GitHub Actions builds Docker image → pushes to ECR
        │
        ▼
{your-org}/argo-deployer@v2 calls Argo Deployer API
        │
        ▼
Argo Deployer commits new image tag to:
  argocd/overlays/{env}/apps/{app}.yaml
        │
        ▼
ArgoCD detects git change (polls every 3 min or via webhook)
  ├── dev/uat   → AUTO SYNC
  └── staging/prod → MANUAL SYNC (DevOps triggers in ArgoCD UI or CLI)
        │
        ▼
Kubernetes rolls out the new deployment
```

### ArgoCD Sync Modes

| Environment | Sync Mode |
|---|---|
| `dev` | Automatic |
| `uat` | Automatic |
| `staging` | Manual |
| `prod` | Manual |

### Adding a New Application (ArgoCD-managed)

1. Create the Helm chart directory: `helm/apps/{app-name}/` with `Chart.yaml`, `values.yaml`, `values-{env}.yaml`.
2. Create the ArgoCD Application manifest: `argocd/overlays/{env}/apps/{app-name}.yaml`.
3. Apply the ArgoCD layer using Kustomize — run this once to register the app with ArgoCD:
   ```bash
   # Apply the entire overlay for an environment (recommended)
   kubectl apply -k argocd/overlays/{env}

   # Or apply a single app definition
   kubectl apply -f argocd/overlays/{env}/apps/{app-name}.yaml
   ```
4. After that, all future deployments are handled automatically by the CI/CD pipeline.

### Repository Structure (simplified)

```
k8s-manifest/
├── helm/
│   ├── argocd/           # ArgoCD itself (bootstrapped first)
│   ├── apps/             # ~91 application Helm charts
│   ├── ingress-nginx/    # Ingress controllers (per domain)
│   ├── cert-manager/
│   ├── kube-prometheus-stack/
│   ├── filebeat/
│   └── ...
├── argocd/
│   ├── base/             # Repos, ArgoCD Projects
│   └── overlays/
│       ├── prod/apps/    # One .yaml per app per environment
│       ├── uat/apps/
│       └── stag/apps/
├── argo-deployer/        # Kustomize
├── {your-org}-api/          # Kustomize
├── PersistentVolumes/    # PV/PVC for stateful apps
├── infra/                # Manually applied infra components
└── raw/                  # One-off raw YAML (vLLM, cert issuers, etc.)
```

---

## 7. DNS Management

DNS is split across three systems depending on the domain:

### Cloudflare ({YourCompany} product domains)

**Repo:** `github.com/{your-github-org}/cloudflare-{yourcompany}-tf`

Manages DNS for all {YourCompany} product domains:

| Domain |
|---|
| `{yourcompany}.dev` |
| `{yourcompany}.com` |
| `{yourcompany}.ai` |

All records point to AWS ALBs (via CNAME) or CloudFront distributions. **Never edit DNS manually in the Cloudflare dashboard** — Terraform will overwrite any manual change.

### Cloudflare Zero Trust

**Repo:** `github.com/{your-github-org}/cloudflare-zero-trust-tf`

Manages Cloudflare Zero Trust configuration — access policies, tunnels, and application access controls.

### AWS Route 53

Two domains are managed via Route 53, each in its own repo:

**`{your-org}.com`** → `github.com/{your-github-org}/route53-{your-org}-com-tf`
DNS records split by environment: `records_dev.tf`, `records_uat.tf`, `records_staging.tf`, `records_prod.tf`.

**`{yourcompany}.ai`** → `github.com/{your-github-org}/route53-{yourcompany}-ai-tf`
Manages all DNS for `{yourcompany}.ai` including internal tool subdomains (`monitor.{yourcompany}.ai`, `log.{yourcompany}.ai`, `tracing.{yourcompany}.ai`, etc.).

---

## 8. Secrets Management

All secrets are managed via the **External Secrets Operator (ESO)** — secrets are never stored in Git.

### How It Works

1. Secrets are stored in **AWS Secrets Manager** with the naming pattern `eks-{cluster-prefix}-{secret-name}`.
2. A `ClusterSecretStore` named `ai-aws-vault` (defined in `infra/external-secrets/ClusterSecretStore.yaml`) authenticates to AWS using IRSA.
3. Each application defines an `ExternalSecret` resource that maps secret keys to a Kubernetes `Secret`.
4. ESO syncs secrets on a 1-hour schedule (or on-demand).

### Example ExternalSecret

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: my-app-secrets
  namespace: my-app
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: ai-aws-vault
    kind: ClusterSecretStore
  target:
    name: my-app-secrets
    creationPolicy: Owner
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: {SECRET_PREFIX_PROD}my-app
        property: database_url
```

> **Rule:** Never commit `.env` files or raw secret values to any repository.

---

## 9. Observability

### Metrics — kube-prometheus-stack

Deployed via Helmfile (`helm/kube-prometheus-stack/`) on every cluster. Components enabled:

| Component | Status |
|---|---|
| Prometheus | Enabled on all clusters |
| Alertmanager | Enabled on prod (alerts via Telegram bot) |
| Grafana | Enabled on prod only (`gr.{yourcompany}.ai`, Google OAuth, `-company.com` domain) |
| Node Exporter | Enabled on all clusters |
| kube-state-metrics | Enabled on all clusters |
| DCGM Exporter | GPU metrics (applied via `infra/dcgm-exporter/`) |

Custom dashboards committed in `helm/kube-prometheus-stack/dashboards/` (e.g., `llm-agent.json`, `nginx-ingress.json`).

**Internal access (not public-facing):**
- Prometheus: `prometheus-monitoring-internal.{yourcompany}.ai` (prod), `stag-prometheus-...`, `uat-prometheus-...`
- Alertmanager: `alertmanager-monitoring-internal.{yourcompany}.ai`

## 9. Observability

### Metrics — kube-prometheus-stack

Deployed via Helmfile (`helm/kube-prometheus-stack/`) on every cluster. Components enabled:

| Component | Status |
|---|---|
| Prometheus | Enabled on all clusters |
| Alertmanager | Enabled on all clusters — pushes alerts to **Slack** |
| Grafana | Disabled in-cluster; all environments use the centralized Grafana at `monitor.{yourcompany}.ai` |
| Node Exporter | Enabled on all clusters |
| kube-state-metrics | Enabled on all clusters |
| DCGM Exporter | GPU metrics (applied via `infra/dcgm-exporter/`) |

Custom dashboards committed in `helm/kube-prometheus-stack/dashboards/` (e.g., `llm-agent.json`, `nginx-ingress.json`).

**Internal access (not public-facing):**
- Prometheus: `prometheus-monitoring-internal.{yourcompany}.ai` (prod), `stag-prometheus-...`, `uat-prometheus-...`
- Alertmanager: `alertmanager-monitoring-internal.{yourcompany}.ai`

### Metrics Dashboard — Grafana

**URL:** `{GRAFANA_URL}`

Grafana runs on the **DevOps server (`{DEVOPS_SERVER_1}`)** via Docker Compose. It serves as the **centralized metrics dashboard for all three environments** (UAT/dev, staging, prod) — you can switch the Prometheus data source within Grafana to view any environment. It is exposed to the cluster via an `EndpointSlice` resource in the `monitoring` namespace (`raw/uat/monitor/`), then proxied through the UAT cluster's ingress controller.

### Log Aggregation — Graylog + OpenSearch

**URL:** `{LOGS_URL}`

Centralized log collection runs on the **DevOps server ({DEVOPS_SERVER_1})**. Like Grafana, Graylog aggregates logs from all environments into a single UI — logs from each cluster are tagged with their environment label via Filebeat.

- **OpenSearch** — runs as a systemd service (`/lib/systemd/system/opensearch.service`). Stores and indexes all container logs.
- **Graylog** — runs as a systemd service (`/lib/systemd/system/graylog-server.service`). Web UI for log search and alerting, backed by OpenSearch. Exposed via UAT cluster ingress → `raw/uat/logging/ingress.yaml`.
- **Filebeat** — deployed in **each EKS cluster** via Helmfile (`helm/filebeat/`, version `~8.5.1`). Collects container logs via Kubernetes autodiscover and ships them to Graylog's Logstash input on `{DEVOPS_SERVER_1}`:

| Environment | Logstash Endpoint |
|---|---|
| UAT | `{DEVOPS_SERVER_1}:8102` |
| Staging | `{DEVOPS_SERVER_1}:8104` |
| Prod | `{DEVOPS_SERVER_1}:8103` |

### APM Tracing — ELK Stack + ai-tracer

**URL:** `{TRACING_URL}` (Kibana)

APM tracing runs on a **dedicated server at `{APM_SERVER}`** (separate from the DevOps server). The stack consists of:

- **Elasticsearch** — port `9200`, log/trace storage backend.
- **Kibana** — port `5601`, APM UI. Exposed via UAT cluster ingress → `raw/uat/tracing/ingress.yaml`. A single Kibana URL serves all environments.
- **Elastic APM Server** — port `8200`, receives trace data from instrumented applications. All apps that support APM point to `http://{APM_SERVER}:8200`.

**`ai-tracer`** is an internal Kubernetes application (`helm/apps/ai-tracer/`) that consumes RabbitMQ events (Sessions, Messages, Emotions, Audio, etc.) and forwards structured traces to the APM Server. It is deployed per environment with the appropriate `APM_ENVIRONMENT` label so traces are filterable in Kibana.

The `tracing` and `ai-tracer` services are exposed to the cluster via `EndpointSlice` resources in the `monitoring` namespace (`raw/uat/tracing/`, `raw/uat/ai-tracer/`).

> **Note:** Jaeger was previously used for distributed tracing but is no longer active. The ELK APM stack is the current tracing solution.

---

## 10. DevOps Servers

### {DEVOPS_SERVER_1} — DevOps Tooling Server

A dedicated EC2 instance inside the `devops` VPC hosting shared DevOps tooling. Services run as Docker containers or systemd services. This server is **not managed by Terraform** — services were set up manually.

| Service | Type | Port | URL | Purpose |
|---|---|---|---|---|
| **OpenSearch** | systemd | 9200 | — | Log storage and indexing backend for Graylog |
| **Graylog** | systemd | 9000 | `{LOGS_URL}` | Centralized log search and alerting UI |
| **Grafana** | Docker Compose | 3000 | `{GRAFANA_URL}` | Aggregated metrics from all environments |
| **Metabase** | Docker Compose | 4000 | `{METABASE_URL}` | BI / data dashboards (UAT PostgreSQL RDS) |
| **Heimdall** | Docker Compose | 9080/9443 | `{HEIMDALL_URL}` | Internal portal / application launcher |

### {APM_SERVER} — APM / Tracing Server

A separate EC2 instance dedicated to the ELK APM stack. Also **not managed by Terraform**.

| Service | systemd unit | Port | URL | Purpose |
|---|---|---|---|---|
| **Elasticsearch** v8.19.4 | `elasticsearch` | 9200 | — | APM trace and log storage (`/etc/elasticsearch`) |
| **Kibana** | `kibana` | 5601 | `{TRACING_URL}` | APM UI — single URL for all environments (`/etc/kibana`) |
| **Elastic APM Server** | `apm-server` | 8200 | — | Receives traces from instrumented apps |

### Managing Services

```bash
# Systemd services (OpenSearch, Graylog, Elasticsearch, Kibana, APM Server)
sudo systemctl status opensearch
sudo systemctl restart graylog-server

# On {APM_SERVER} (APM server)
sudo systemctl status elasticsearch
sudo systemctl status kibana
sudo systemctl status apm-server
sudo systemctl restart apm-server

# Docker Compose services on {DEVOPS_SERVER_1} (Grafana, Metabase, Heimdall)
# Each service has its own compose file in /data/<service>/
cd /data/grafana && docker compose up -d
cd /data/metabase && docker compose up -d
cd /data/heimdall && docker compose up -d

# View logs
docker compose logs -f

# Update an image
docker compose pull && docker compose up -d
```

---

## 11. Self-Hosted GitHub Runner ({GITHUB_RUNNER_SERVER})

GitHub Actions CI/CD jobs run on a **self-hosted runner** (not GitHub-hosted machines). This server is separate from the DevOps server.

**Runner configuration (`/data/github-runner/docker-compose.yml`):**

| Setting | Value |
|---|---|
| Scope | Organization (`{your-org}`) |
| Auth | GitHub App (App ID: {YOUR_GITHUB_APP_ID}) |
| Labels | `linux`, `x64`, `{your-org}` |
| Mode | Ephemeral (each job gets a fresh container) |
| Replicas | 3 parallel runners |
| Image | `{ECR_PREFIX}system/github-runner:latest` |

The runner container has access to the host Docker socket (`/var/run/docker.sock`) to support Docker-in-Docker builds. It also mounts the host's Docker config (`/root/.docker/config.json`) for ECR authentication — this means the host must have valid ECR credentials.

**To restart or scale runners:**

```bash
cd /data/github-runner
docker compose up -d --scale worker=3
docker compose logs -f worker
```

---

## 12. Environments Summary

| Environment | Cluster | Namespace | ArgoCD Sync | Notes |
|---|---|---|---|---|
| `dev` | `{uat-cluster-name}` | `{DEV_NAMESPACE}` | **Automatic** | Shares cluster with UAT, reduced resources |
| `uat` | `{uat-cluster-name}` | `{UAT_NAMESPACE}` | **Automatic** | Mirrors production config closely |
| `staging` / `stag` | `{staging-cluster-name}` | — | **Manual** | Between UAT and prod in the release pipeline |
| `prod` | `{prod-cluster-name}` | — | **Manual** | Full HA, customer-facing traffic |

> `staging` and `stag` are used interchangeably across file names and resource names — they refer to the same environment. Dev and UAT share the same EKS cluster (`{uat-cluster-name}`) but are isolated by Kubernetes namespace.

---

## 13. Common Day-to-Day Tasks

### Deploy an app to dev/uat

Merge your PR to the `dev` or `uat` branch. The GitHub Actions workflow triggers automatically, builds the image, and calls Argo Deployer. ArgoCD auto-syncs within ~3 minutes.

### Deploy an app to staging/prod

Push a git tag (`v*`) to trigger the build workflow. Once the image is built and the tag is committed to `k8s-manifest`, **manually sync** in the ArgoCD UI or CLI:

```bash
argocd app sync {app-name}-prod
```

### Add a new application

1. Create the Helm chart in `k8s-manifest/helm/apps/{app-name}/`.
2. Create the ArgoCD Application YAML in `k8s-manifest/argocd/overlays/{env}/apps/{app-name}.yaml`.
3. Register the app with ArgoCD using Kustomize:
   ```bash
   kubectl apply -k argocd/overlays/{env}
   ```
4. Add the GitHub Actions workflow files to the application repository.

### Add a new AWS resource

Edit or create the relevant `.tf` file in the `terraform` repo, then:

```bash
terraform fmt && terraform validate && terraform plan
terraform apply
```

### Add a new DNS record

For {YourCompany} product domains → edit the appropriate `*-records.tf` file in `cloudflare-{yourcompany}-tf`.  
For `{your-org}.com` → edit the relevant `records_{env}.tf` file in `route53-{your-org}-com-tf`.

### Check app status

```bash
# List all ArgoCD apps
argocd app list

# Check a specific app
argocd app get {app-name}-uat

# View pod logs
kubectl logs -n {namespace} -l app={app-name} --tail=100 -f

# Check recent events
kubectl describe pod -n {namespace} {pod-name}
```

### Update a Helm-managed infra tool (e.g., Ingress Nginx, Prometheus)

Navigate to the chart directory for the target environment, then run helmfile from there:

```bash
cd k8s-manifest/helm/{chart-name}/{env}
helmfile diff    # Review changes first
helmfile apply .
```

---

## 14. Key Contacts & Access

| Area | URL / Location |
|---|---|
| AWS Console | AWS SSO — ask team lead for account access |
| GitHub Organization | `github.com/{your-github-org}` |
| ArgoCD UI | Per-cluster URL (internal, requires VPN or cluster access) |
| Grafana (all envs) | `{GRAFANA_URL}` (IP whitelist restricted) |
| Graylog (log search) | `{LOGS_URL}` (IP whitelist restricted) |
| Kibana APM (tracing) | `{TRACING_URL}` (IP whitelist restricted) |
| Terraform state | S3 bucket `{your-tf-state-bucket}` in `ap-southeast-1` |

> **New engineer checklist:** AWS SSO access → GitHub org membership → kubeconfig for each cluster → VPN/IP whitelist access → ArgoCD login.
