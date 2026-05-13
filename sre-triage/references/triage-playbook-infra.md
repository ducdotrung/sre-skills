# Triage Playbook: INFRA / SECRET / DNS

Used by Step 4 of `.claude/skills/sre-triage.md` when the ticket type is `INFRA_CHANGE`, `SECRET`, `DNS`, or `DNS_ZT`.

Read `sre-config.md` to get cluster names, secret prefixes, AWS region, and GitHub org before generating commands.

## Playbook: INFRA_CHANGE

Detect the sub-type and generate the matching guide.

**Scale pods:**
```bash
# Permanent: edit helm/apps/{app}/values-{env}.yaml → replicaCount: {n}, commit → ArgoCD syncs
# Temporary (dev/uat only):
kubectl scale deployment {app-name} --replicas={n} -n {namespace}
```

**Detect ENV target before acting:**

| Signal | Where the ENV lives |
|---|---|
| Prefix `VITE_APP_*`, `NEXT_PUBLIC_*`, or repo is `cms-*` / frontend app | **GitHub Actions Variables/Secrets** (see below) |
| Backend service on EKS (repo is `*-backend`, `*-agent`, etc.) | **AWS Secrets Manager** + ESO (see below) |

**Update ENV variables — Frontend / CMS apps (GitHub Actions):**

> CMS and Next.js/Vite frontend apps store build-time env vars in the GitHub repo's
> **Settings → Secrets and variables → Actions**, not in Secrets Manager.
> - Non-sensitive values (URLs, feature flags): add as **Variables**
> - Sensitive values (API keys, tokens): add as **Secrets**

Steps per environment (repeat for each env in the ticket):
1. Go to `https://github.com/{GITHUB_ORG}/{repo}/settings/variables/actions`
2. Under **Variables** tab → **New repository variable**
   - Name: `{VAR_NAME}` (e.g. `VITE_APP_HOST_API`)
   - Value: the value for this env
   - Note: GitHub Actions variables are **not** env-scoped natively — use separate variable names per env (e.g. `VITE_APP_HOST_API_UAT`, `VITE_APP_HOST_API_PROD`) or rely on the workflow's branch/env conditional logic
3. For sensitive vars → **Secrets** tab → **New repository secret** instead
4. Trigger a re-deploy (re-run the GitHub Actions workflow or push a dummy commit) so the build picks up the new values
5. Verify on the target URL that the correct API endpoint is being used

**Update ENV variables — Backend apps (Secrets Manager):**

Use the secret naming pattern `eks-{cluster-prefix}-{app-name}` from `sre-config.md`.

```bash
# Get current values first
aws secretsmanager get-secret-value \
  --secret-id {SECRET_PREFIX_FOR_ENV}-{app-name} --region {AWS_PRIMARY_REGION} \
  --query SecretString --output text

# Update — include ALL existing keys (put-secret-value replaces entire secret)
aws secretsmanager put-secret-value \
  --secret-id {SECRET_PREFIX_FOR_ENV}-{app-name} \
  --secret-string '{"EXISTING_KEY": "val", "NEW_KEY": "new-val"}' \
  --region {AWS_PRIMARY_REGION}

# Force ESO resync + restart
kubectl annotate externalsecret {app-name} force-sync=$(date +%s) --overwrite -n {namespace}
kubectl rollout restart deployment/{app-name} -n {namespace}
```

For non-secret Helm vars: edit `values-{env}.yaml` and commit.

**S3 CORS** — edit `s3-*.tf`, add `cors_rule {}`, then `terraform plan/apply -target=module.{bucket}`.

**S3 IAM** — add ARN to `white_list_full_access_identifiers` in `s3-*.tf`, then plan/apply.

**Nginx/Ingress** — add annotations to app's ingress in `helm/ingress-nginx/{env}/`:
```yaml
nginx.ingress.kubernetes.io/proxy-body-size: "50m"
nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
```
Then `helmfile diff . && helmfile apply .`.

**General Terraform:**
```bash
terraform fmt && terraform validate
terraform plan -target={resource_type}.{resource_name}
terraform apply -target={resource_type}.{resource_name}
```

## Playbook: SECRET UPDATE

Secret naming: `eks-{cluster-prefix}-{app-name}` — read the exact prefix for each env from `sre-config.md`.

> If ticket is a DEPLOY with secret values → handle as sub-step inside DEPLOY, not here.

**Update existing:**
```bash
# 1. Get current values
aws secretsmanager get-secret-value \
  --secret-id {SECRET_PREFIX_FOR_ENV}-{app-name} --region {AWS_PRIMARY_REGION} \
  --query SecretString --output text

# 2. Update (ALL keys)
aws secretsmanager put-secret-value \
  --secret-id {SECRET_PREFIX_FOR_ENV}-{app-name} \
  --secret-string '{"EXISTING_KEY": "val", "UPDATED_KEY": "new-val"}' \
  --region {AWS_PRIMARY_REGION}

# 3. Force ESO resync + restart app
kubectl annotate externalsecret {app-name} force-sync=$(date +%s) --overwrite -n {namespace}
kubectl rollout restart deployment/{app-name} -n {namespace}
```

**Create new:**
```bash
aws secretsmanager create-secret \
  --name {SECRET_PREFIX_FOR_ENV}-{app-name} \
  --description "Secrets for {app-name} on {env}" \
  --secret-string '{"KEY": "value"}' \
  --region {AWS_PRIMARY_REGION}
```
Then add `ExternalSecret` manifest to the app's Helm chart (`additionalManifests:` section).

## Playbook: DNS

Map your domains to their Terraform repos in `sre-config.md` or `sre-triage/docs/infra-overview.md`. Examples:

| Domain | Terraform Repo |
|---|---|
| `primary-domain.com` | `github.com/{GITHUB_ORG}/route53-primary-domain-tf` |
| `secondary-domain.com` | `github.com/{GITHUB_ORG}/route53-secondary-domain-tf` |
| Cloudflare-managed domains | `github.com/{GITHUB_ORG}/cloudflare-tf` |
| Zero Trust / VPN | `github.com/{GITHUB_ORG}/cloudflare-zero-trust-tf` |

Generate the exact Terraform block and run:
```bash
terraform fmt && terraform validate && terraform plan && terraform apply
```

Cloudflare CNAME example:
```hcl
resource "cloudflare_record" "{name}" {
  zone_id = cloudflare_zone.{zone}.id
  name    = "{subdomain}"
  value   = "{target}"
  type    = "CNAME"
  ttl     = var.ttl_app_endpoint
  proxied = false
}
```

Route 53 CNAME example:
```hcl
resource "aws_route53_record" "{name}" {
  zone_id = aws_route53_zone.{zone}.zone_id
  name    = "{subdomain}.{domain}"
  type    = "CNAME"
  ttl     = 60
  records = ["{target}"]
}
```
