# Terraform EKS Module

An opinionated Terraform wrapper module around [terraform-aws-modules/eks/aws](https://github.com/terraform-aws-modules/terraform-aws-eks/) (~> 20.0) that provisions a production-ready AWS EKS cluster with essential add-ons pre-configured.

## What This Module Creates

### EKS Cluster
- EKS cluster (Kubernetes 1.33) with IPv4 networking
- Public + private API endpoint access (public restricted by CIDR)
- Secrets encryption via KMS
- IRSA (IAM Roles for Service Accounts) enabled
- Managed node groups (configurable)

### EKS Managed Add-ons

| Add-on | Version | Description |
|--------|---------|-------------|
| CoreDNS | v1.13.2-eksbuild.4 | Cluster DNS, pinned to management nodes |
| kube-proxy | v1.33.10-eksbuild.2 | Network proxy |
| VPC-CNI | v1.21.1-eksbuild.7 | Pod networking with NetworkPolicy enabled |
| EBS CSI Driver | v1.58.0-eksbuild.1 | EBS volume support with IRSA |

### Helm Releases

| Chart | Version | Description |
|-------|---------|-------------|
| [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/) | 1.17.1 (app v2.17.1) | ALB/NLB ingress controller |
| [External Secrets Operator](https://external-secrets.io/) | v0.20.3 | Syncs AWS Secrets Manager to Kubernetes secrets |
| [Mountpoint S3 CSI Driver](https://github.com/awslabs/mountpoint-s3-csi-driver) | 2.5.0 | Mount S3 buckets as volumes |

### IRSA Roles

| Role | Service Account | Purpose |
|------|-----------------|---------|
| `{cluster_name}-vpc-cni` | kube-system:aws-node | VPC CNI networking |
| `{cluster_name}-ebs-csi` | kube-system:ebs-csi-controller-sa | EBS volume management |
| `{cluster_name}-efs-csi` | kube-system:efs-csi-controller-sa | EFS volume management |
| `{cluster_name}-alb-controller` | kube-system:aws-load-balancer-controller | Load balancer management |
| `{cluster_name}-external-secret` | kube-system:external-secrets | Secrets Manager access |
| `{cluster_name}-s3-csi` | kube-system:s3-csi-driver-sa | S3 bucket access |

### Networking / Security

- Security group `{cluster_name}-remote-access` for SSH (port 22) from `10.0.0.0/8`
- Kubeconfig auto-generated at `~/.kube/{env}_config`

## Architecture

All system-level pods (CoreDNS, ALB controller, External Secrets, S3 CSI controller) are isolated on management nodes using:
- `nodeSelector: { nodegroup: management }`
- `toleration: { key: workload, value: management, effect: NoSchedule }`

This keeps management workloads separated from application workloads.

## Prerequisites

- Terraform >= 1.0
- AWS CLI installed and configured
- Pre-existing VPC with subnets
- IAM permissions to create EKS clusters, IAM roles, and KMS keys

## Usage

```hcl
module "eks" {
  source = "git::https://github.com/{your-github-org}/terraform-eks-module.git?ref=v1.3.7"

  cluster_name              = "my-cluster"
  region                    = "ap-northeast-1"
  env                       = "prod"
  vpc_id                    = "vpc-0123456789abcdef0"
  control_plane_subnet_ids  = ["subnet-aaa", "subnet-bbb"]
  subnet_ids                = ["subnet-ccc", "subnet-ddd"]
  cluster_service_ipv4_cidr = "172.20.0.0/16"
  secret_prefix             = "my-app"

  cluster_endpoint_public_access_cidrs = ["203.0.113.0/24"]

  eks_managed_node_groups = {
    management = {
      instance_types = ["t3.medium"]
      min_size       = 2
      max_size       = 3
      desired_size   = 2

      taints = {
        management = {
          key    = "workload"
          value  = "management"
          effect = "NO_SCHEDULE"
        }
      }

      labels = {
        nodegroup = "management"
      }
    }

    application = {
      instance_types = ["t3.large"]
      min_size       = 2
      max_size       = 10
      desired_size   = 3
    }
  }

  kms_key_administrators = ["arn:aws:iam::123456789012:role/admin"]
}
```

### Restricting S3 CSI Driver Access

By default the S3 CSI driver has access to all S3 buckets. To restrict it:

```hcl
module "eks" {
  # ...

  s3_csi_bucket_arns = [
    "arn:aws:s3:::my-data-bucket",
    "arn:aws:s3:::my-other-bucket",
  ]
  s3_csi_path_arns = [
    "arn:aws:s3:::my-data-bucket/*",
    "arn:aws:s3:::my-other-bucket/prefix/*",
  ]
}
```

### Allowing Additional Secrets Manager ARNs

By default, External Secrets can read secrets matching `eks-{secret_prefix}-*`. To allow additional patterns:

```hcl
module "eks" {
  # ...

  secrets_manager_arns_allow_list = [
    "arn:aws:secretsmanager:ap-northeast-1:*:secret:shared-*",
  ]
}
```

## Variables

### Required

| Name | Type | Description |
|------|------|-------------|
| `cluster_name` | `string` | Name of the EKS cluster |
| `secret_prefix` | `string` | Prefix for secret names in AWS Secrets Manager (`eks-{prefix}-*`) |
| `cluster_service_ipv4_cidr` | `string` | CIDR block for Kubernetes service IPs |
| `control_plane_subnet_ids` | `list(string)` | Subnet IDs for the EKS control plane |
| `subnet_ids` | `list(string)` | Subnet IDs for worker nodes |
| `vpc_id` | `string` | VPC ID for the cluster |
| `eks_managed_node_groups` | `any` | Map of managed node group definitions (see [upstream docs](https://github.com/terraform-aws-modules/terraform-aws-eks/tree/master/examples/eks_managed_node_group)) |

### Optional

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `region` | `string` | `"ap-northeast-1"` | AWS region |
| `env` | `string` | `"dev"` | Environment name (used in tags and kubeconfig path) |
| `cluster_endpoint_public_access_cidrs` | `list(string)` | `["54.64.90.76/32"]` | CIDRs allowed to access the public API endpoint |
| `default_instance_types` | `list(string)` | `["t2.small"]` | Default instance types for node groups |
| `s3_csi_bucket_arns` | `list(string)` | `["arn:aws:s3:::*"]` | S3 bucket ARNs the CSI driver can access |
| `s3_csi_path_arns` | `list(string)` | `["arn:aws:s3:::*"]` | S3 path ARNs the CSI driver can access |
| `secrets_manager_arns_allow_list` | `list(string)` | `[]` | Additional Secrets Manager ARN patterns |
| `kms_key_administrators` | `list(string)` | `[]` | IAM ARNs for KMS key administrators |
| `kms_key_users` | `list(string)` | `[]` | IAM ARNs for KMS key users |
| `kms_key_source_policy_documents` | `list(string)` | `[]` | Additional IAM policy documents for the KMS key |

## Outputs

| Name | Description |
|------|-------------|
| `remote_access_sg_id` | Security group ID for SSH remote access to nodes |

## File Structure

```
terraform-eks-module/
  eks.tf                             # EKS cluster, providers, IRSA roles (VPC-CNI, EBS, EFS), security group
  variables.tf                       # Input variables
  aws_load_balancer_controller.tf    # ALB controller Helm release + IRSA role
  aws_secret_k8s.tf                  # External Secrets Helm release + IRSA role
  s3-csi-driver.tf                   # S3 CSI driver Helm release + IRSA role
  fsx-csi-driver.tf                  # FSX CSI driver (currently disabled)
```

## Version Pinning

All add-on and chart versions are explicitly pinned (no `most_recent = true`). To update versions, modify the version strings in the respective `.tf` files and commit a new module tag. Consumers pin to a specific git tag:

```hcl
source = "git::https://github.com/{your-github-org}/terraform-eks-module.git?ref=v1.3.7"
```

## Notes

- The module configures `kubernetes` and `helm` providers internally using `aws eks get-token` for authentication. This requires the AWS CLI to be installed where Terraform runs.
- `eks_managed_node_groups` uses `type = any` because Terraform's `map(any)` requires all elements to have the same type, which doesn't work for heterogeneous node group configurations. See [hashicorp/terraform#21384](https://github.com/hashicorp/terraform/issues/21384).
- The FSX CSI driver (`fsx-csi-driver.tf`) is currently disabled because the EKS add-on does not support tolerating all taints. It may be re-enabled via Helm in a future version.
