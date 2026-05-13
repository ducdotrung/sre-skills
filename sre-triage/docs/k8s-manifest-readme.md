# K8S Manifest

This repository stores all Kubernetes manifests for our infrastructure. It manages **90+ microservices** across three environments (`dev`, `uat`, `prod`) using a GitOps-first approach.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Repository Overview](#repository-overview)
3. [Folder Structure](#folder-structure)
4. [Environments](#environments)
5. [Deployment Methods](#deployment-methods)
   - [Helm (via Helmfile)](#1-helm-via-helmfile)
   - [ArgoCD (GitOps)](#2-argocd-gitops)
   - [Kustomize (kubectl)](#3-kustomize-kubectl)
   - [Raw Manifests](#4-raw-manifests)
6. [How Deployments Flow End-to-End](#how-deployments-flow-end-to-end)
7. [Adding a New Application](#adding-a-new-application)
8. [Managing Secrets](#managing-secrets)
9. [Infrastructure Components](#infrastructure-components)
10. [Persistent Volumes](#persistent-volumes)
11. [Common Operations](#common-operations)
12. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Install the following tools before working with this repo.

### Required Tools

| Tool | Purpose | Install |
|------|---------|---------|
| `kubectl` | Apply/diff Kubernetes manifests | `brew install kubectl` |
| `helm` | Kubernetes package manager | `brew install helm` |
| `helmfile` | Declarative Helm chart versioning | `brew install helmfile` |
| `helm-diff` | Preview Helm changes before apply | `helm plugin install https://github.com/databus23/helm-diff` |
| `argocd` (CLI) | Interact with ArgoCD | `brew install argocd` |
| `kustomize` | Built into `kubectl`, or install standalone | `brew install kustomize` |

### Cluster Access

Make sure your `kubeconfig` is configured to point to the correct cluster before running any commands.

```bash
# Verify your current context
kubectl config current-context

# List all available contexts
kubectl config get-contexts

# Switch context
kubectl config use-context <context-name>
```

---

## Repository Overview

The repo uses **three deployment strategies** depending on the nature of the workload:

| Strategy | Used For | Trigger |
|----------|----------|---------|
| **Helm + Helmfile** | Infrastructure tools (ArgoCD, Ingress, Prometheus, etc.) | Manual: `helmfile apply` |
| **ArgoCD (GitOps)** | Actively developed application services | Automatic: git push → ArgoCD reconciles |
| **Kustomize** | Stable/internal services, argo-deployer, {your-org}-api | Manual: `kubectl apply -k` |
| **Raw YAML** | One-off configs, vLLM, cert-manager issuers | Manual: `kubectl apply -f` |

---

## Folder Structure

```
k8s-manifest/
├── helm/                        # Helm charts managed by helmfile
│   ├── argocd/                  #   ArgoCD itself (bootstrapped first)
│   │   ├── prod/
│   │   ├── stag/
│   │   └── uat/
│   ├── apps/                    #   One subfolder per application (~91 apps)
│   │   └── <app-name>/
│   │       ├── Chart.yaml
│   │       ├── values.yaml      #     Default values
│   │       ├── values-prod.yaml #     Production overrides
│   │       ├── values-stag.yaml #     Staging overrides
│   │       └── values-uat.yaml  #     UAT overrides
│   ├── ingress-nginx/           #   Ingress controller per domain
│   ├── cert-manager/
│   ├── kube-prometheus-stack/
│   └── ...                      #   Other infra charts
│
├── argocd/                      # ArgoCD Application definitions (GitOps apps)
│   ├── base/
│   │   ├── repos.yaml           #   Git credentials via ExternalSecret
│   │   └── projects/            #   ArgoCD Project definitions
│   └── overlays/
│       ├── prod/
│       │   └── apps/            #   One .yaml per app in production
│       ├── uat/
│       │   └── apps/
│       └── stag/
│           └── apps/
│
├── argo-deployer/               # The argo-deployer app itself (Kustomize)
│   ├── base/
│   └── overlays/
│       ├── dev/
│       └── uat/
│
├── {your-org}-api/                 # Castalk API platform (Kustomize)
│   ├── base/
│   └── overlays/
│       ├── dev/
│       ├── prod/
│       └── uat/
│
├── PersistentVolumes/           # PV/PVC definitions for stateful workloads
│   └── overlays/
│       ├── dev/
│       ├── prod/
│       ├── stag/
│       └── uat/
│
├── infra/                       # Infrastructure components (applied manually)
│   ├── dcgm-exporter/           #   GPU metrics
│   ├── external-secrets/        #   ClusterSecretStore + demo configs
│   ├── ingress-nginx/           #   Extra RBAC/jobs
│   ├── metrics-server/
│   ├── node-exporter/
│   └── nvidia/                  #   GPU device plugin
│
├── jaeger/                      # Distributed tracing
├── cloudflared/                 # Cloudflare tunnel config
└── raw/                         # Raw YAML applied directly with kubectl
    ├── prod/
    ├── uat/
    ├── staging/
    └── dev/
```

---

## Environments

| Env | Description | Notes |
|-----|-------------|-------|
| `dev` | Development / experimental | Reduced resources, not always stable |
| `uat` | User Acceptance Testing / pre-prod | Mirrors production config closely |
| `stag` | Staging | Used primarily for Helm infra charts |
| `prod` | Production | Full resources, high availability |

Most applications have environment-specific overrides in their `overlays/{env}/` directories.

---

## Deployment Methods

### 1. Helm (via Helmfile)

Helm is used for **infrastructure-level** services such as ArgoCD, Ingress Nginx, Cert-Manager, Prometheus, Dify, Filebeat, and LiveKit.

We use [helmfile](https://github.com/helmfile/helmfile) to lock chart versions declaratively.

#### Workflow

```bash
# 1. Navigate to the chart + environment directory
cd helm/argocd/uat

# 2. Preview what would change (always do this first)
helmfile diff

# 3. Apply the changes
helmfile apply
```

#### Example: Update Ingress Nginx on Production

```bash
cd helm/ingress-nginx/prod
helmfile diff   # Review changes
helmfile apply  # Apply
```

#### Helm App Directory Layout

Each application under `helm/apps/<app-name>/` follows this pattern:

```
helm/apps/livekit-agent/
├── Chart.yaml          # Chart metadata + dependencies
├── values.yaml         # Shared defaults
├── values-prod.yaml    # Production-specific values (image tag, replicas, resources)
├── values-stag.yaml
└── values-uat.yaml
```

---

### 2. ArgoCD (GitOps)

ArgoCD manages all **actively developed application services**. Once an ArgoCD Application resource is created, deployments happen automatically when manifests are pushed to git.

#### How It Works

1. A developer pushes a code change to an application repository.
2. The CI/CD pipeline builds a Docker image and tags it.
3. **Argo Deployer** (an automated bot) commits the new image tag to this repo (`argocd/overlays/{env}/apps/<app>.yaml`).
4. ArgoCD detects the git change and syncs the cluster to the new state.

> You will see automated commits in git history like:
> `[Argo Deployer] Update livekit-agent to abc1234 on uat`

#### ArgoCD App Directory Layout

```
argocd/
├── base/
│   ├── repos.yaml              # ExternalSecret pulling git credentials
│   └── projects/
│       └── ai-service.yaml       # ArgoCD Project definition
└── overlays/
    ├── prod/
    │   └── apps/
    │       ├── livekit-agent.yaml
    │       ├── stt-agent.yaml
    │       └── ...
    └── uat/
        └── apps/
            └── ...
```

#### Applying the ArgoCD Layer Itself

When you add or modify an ArgoCD Application manifest, apply it to the cluster:

```bash
# Apply the entire overlay for an environment
kubectl apply -k argocd/overlays/uat

# Apply a single app definition
kubectl apply -f argocd/overlays/uat/apps/livekit-agent.yaml
```

After applying, ArgoCD will take over and manage the application automatically.

#### Checking App Status

```bash
# List all apps
argocd app list

# Get status of a specific app
argocd app get livekit-agent-uat

# Manually trigger a sync
argocd app sync livekit-agent-uat

# View sync history
argocd app history livekit-agent-uat
```

#### ArgoCD Sync Options Used

Most apps are configured with these sync options:

| Option | Effect |
|--------|--------|
| `CreateNamespace=true` | Auto-create the namespace if it doesn't exist |
| `PruneLast=true` | Delete removed resources only after new ones are healthy |
| `PrunePropagationPolicy=foreground` | Wait for child resources to be deleted |
| `RespectIgnoreDifferences=true` | Ignore known drift (e.g., batch Job specs) |

---

### 3. Kustomize (kubectl)

Used for stable services (`argo-deployer`, `{your-org}-api`) and infrastructure components (`infra/`). Changes are applied manually.

#### Workflow

```bash
# Preview what would change
kubectl diff -k ./<app>/overlays/<env>

# Apply changes
kubectl apply -k ./<app>/overlays/<env>
```

#### Examples

```bash
# Deploy {your-org}-api to UAT
kubectl diff -k ./{your-org}-api/overlays/uat
kubectl apply -k ./{your-org}-api/overlays/uat

# Deploy argo-deployer to dev
kubectl apply -k ./argo-deployer/overlays/dev

# Apply infrastructure components
kubectl apply -k ./infra/external-secrets
kubectl apply -k ./infra/nvidia
```

#### Kustomize Directory Layout

```
{your-org}-api/
├── base/
│   ├── kustomization.yaml      # Lists all resources
│   ├── deployment.yaml
│   ├── service.yaml
│   └── ...
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml  # References base, applies patches
    │   └── deployment.yaml     # Patch: image tag, replicas, env vars
    ├── uat/
    └── prod/
```

---

### 4. Raw Manifests

The `raw/` directory contains standalone YAML files that don't fit into Helm, ArgoCD, or Kustomize patterns. These are applied directly.

```bash
# Apply a specific raw manifest
kubectl apply -f raw/prod/vllm-deployment.yaml

# Apply all manifests in a directory
kubectl apply -f raw/uat/
```

> Raw manifests are used for: vLLM deployments, cert-manager ClusterIssuers, RabbitMQ/Redis exporters, gateway CRDs.

---

## How Deployments Flow End-to-End

```
Developer pushes code
        │
        ▼
CI/CD builds Docker image
        │
        ▼
Argo Deployer updates image tag in this repo
(commits to argocd/overlays/{env}/apps/<app>.yaml)
        │
        ▼
ArgoCD detects git change (polls every 3 min or via webhook)
        │
        ▼
ArgoCD applies the new manifest to the cluster
        │
        ▼
Kubernetes rolls out the new deployment
```

For Helm and Kustomize, a DevOps engineer manually runs `helmfile apply` or `kubectl apply -k` after reviewing the diff.

---

## Adding a New Application

### Option A: ArgoCD-managed (recommended for active services)

**Step 1**: Create the Kubernetes manifest directory for your app:

```bash
mkdir -p my-new-app/base
mkdir -p my-new-app/overlays/uat
mkdir -p my-new-app/overlays/prod
```

**Step 2**: Create `my-new-app/base/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
```

**Step 3**: Add your `base/deployment.yaml`, `base/service.yaml`, etc.

**Step 4**: Create environment overlays (`overlays/uat/kustomization.yaml`):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
patches:
  - path: deployment.yaml   # Image tag, resource overrides
```

**Step 5**: Create an ArgoCD Application definition at `argocd/overlays/uat/apps/my-new-app.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-new-app-uat
  namespace: argocd
spec:
  project: default
  source:
    repoURL: git@github.com:your-org/k8s-manifest.git
    targetRevision: main
    path: my-new-app/overlays/uat
  destination:
    server: https://kubernetes.default.svc
    namespace: my-new-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - PruneLast=true
```

**Step 6**: Apply the ArgoCD app definition:

```bash
kubectl apply -f argocd/overlays/uat/apps/my-new-app.yaml
```

ArgoCD will now manage and auto-sync `my-new-app`.

---

### Option B: Helm Chart (for infrastructure or external charts)

**Step 1**: Create the chart directory:

```bash
mkdir -p helm/apps/my-new-app
```

**Step 2**: Add `Chart.yaml`, `values.yaml`, and environment-specific values files:

```
helm/apps/my-new-app/
├── Chart.yaml
├── values.yaml
├── values-prod.yaml
└── values-uat.yaml
```

**Step 3**: Add a `helmfile.yaml` in your env directory (or add to existing one) and run:

```bash
cd helm/apps/my-new-app
helmfile diff
helmfile apply
```

---

## Managing Secrets

**We never commit secrets to this repository.** All secrets are managed via [External Secrets Operator](https://external-secrets.io/) which pulls values from AWS Secrets Manager / Vault at runtime.

### How It Works

1. A `ClusterSecretStore` is defined in `infra/external-secrets/ClusterSecretStore.yaml` — it authenticates to AWS.
2. Each application references an `ExternalSecret` resource that maps secret keys to Kubernetes Secret fields.
3. The operator syncs secrets on a schedule (or on-demand).

### Example ExternalSecret

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: my-app-secrets
  namespace: my-app
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: cluster-secret-store
    kind: ClusterSecretStore
  target:
    name: my-app-secrets
    creationPolicy: Owner
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: /prod/my-app/database-url
```

> Never put `.env` files or raw secret values in YAML. The `.gitignore` already excludes `.env` files.

---

## Infrastructure Components

Components under `infra/` are applied manually and are not GitOps-managed.

| Component | Purpose | Apply Command |
|-----------|---------|---------------|
| `infra/external-secrets` | ClusterSecretStore for AWS integration | `kubectl apply -k infra/external-secrets` |
| `infra/nvidia` | GPU device plugin + test pod | `kubectl apply -k infra/nvidia` |
| `infra/dcgm-exporter` | GPU metrics exporter | `kubectl apply -k infra/dcgm-exporter` |
| `infra/metrics-server` | Kubernetes metrics API (HPA support) | `kubectl apply -k infra/metrics-server` |
| `infra/node-exporter` | Node-level Prometheus metrics | `kubectl apply -k infra/node-exporter` |
| `infra/ingress-nginx` | Extra RBAC and job configs | `kubectl apply -k infra/ingress-nginx` |

---

## Persistent Volumes

Stateful applications have their PV/PVC definitions in `PersistentVolumes/overlays/{env}/`.

```bash
# Apply persistent volume configs for UAT
kubectl apply -k PersistentVolumes/overlays/uat

# Apply for production
kubectl apply -k PersistentVolumes/overlays/prod
```

Applications with persistent volumes include: `bert-vits2-tts`, `livekit-agent`, `stt-agent`, `wav2lip`, `tts-inhouse`, `meeting-minutes-be`, and others.

---

## Common Operations

### Update an Image Tag Manually

If Argo Deployer hasn't run yet and you need to deploy urgently:

```bash
# Edit the image tag in the overlay
vim argocd/overlays/uat/apps/my-app.yaml

# Commit and push — ArgoCD will pick it up automatically
git add argocd/overlays/uat/apps/my-app.yaml
git commit -m "Update my-app to <new-image-tag> on uat"
git push
```

### Scale a Deployment

```bash
kubectl scale deployment <app-name> --replicas=3 -n <namespace>
```

> For ArgoCD-managed apps, scaling via kubectl is temporary — ArgoCD will revert it on the next sync. Update the manifest in git instead.

### Rollback an Application

```bash
# Via ArgoCD CLI
argocd app rollback <app-name> <history-id>

# Or revert the git commit and push
git revert <commit-hash>
git push
```

### View Logs

```bash
kubectl logs -f deployment/<app-name> -n <namespace>

# For multi-container pods
kubectl logs -f deployment/<app-name> -c <container-name> -n <namespace>
```

### Check Resource Usage

```bash
kubectl top pods -n <namespace>
kubectl top nodes
```

### Force ArgoCD Sync

```bash
argocd app sync <app-name> --force
```

---

## Troubleshooting

### ArgoCD App is Out of Sync

```bash
# Check what's different
argocd app diff <app-name>

# Sync manually
argocd app sync <app-name>
```

### Pod is CrashLoopBackOff

```bash
# Check logs
kubectl logs <pod-name> -n <namespace> --previous

# Describe the pod for events
kubectl describe pod <pod-name> -n <namespace>
```

### Helmfile Apply Fails

```bash
# Run diff first to see what's happening
helmfile diff

# Check if helm-diff plugin is installed
helm plugin list

# Reinstall if missing
helm plugin install https://github.com/databus23/helm-diff
```

### ExternalSecret Not Syncing

```bash
# Check the ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>

# Check ClusterSecretStore health
kubectl describe clustersecretstore cluster-secret-store
```

### Kustomize Build Errors

```bash
# Test the kustomize build locally before applying
kubectl kustomize ./<app>/overlays/<env>

# Then apply if it looks correct
kubectl apply -k ./<app>/overlays/<env>
```

---

## Repository Conventions

- **Never commit secrets** — use External Secrets instead.
- **Always run `diff` before `apply`** — review changes before deploying.
- **Use overlays for environment differences** — never modify `base/` for env-specific config.
- **Commit messages for image updates** follow the pattern: `[Argo Deployer] Update <app> to <commit> on <env>`.
- **One ArgoCD Application per service per environment** — keeps blast radius small.
