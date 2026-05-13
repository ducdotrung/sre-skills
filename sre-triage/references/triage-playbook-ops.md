# Triage Playbook: Ops / Resource / Debug

Used by Step 4 of `.claude/skills/sre-triage.md` when the ticket type is `ACCOUNT_MGMT`, `OFFBOARDING`, `NEW_RESOURCE`, `DIFY`, `DEBUG`, or `UNKNOWN`.

Read `sre-config.md` to get `GITHUB_ORG`, cluster/secret naming, server IPs, and observability URLs.

## Playbook: ACCOUNT_MGMT

**GitHub access:** `github.com/{GITHUB_ORG}/{repo}` → Settings → Collaborators → add username with role.

**GitHub new repo:** `github.com/{GITHUB_ORG}` → New repository → Private → initialize → add members.

**Cloudflare Zero Trust:** Dashboard → Access → Groups → add email to appropriate access group. IaC: `github.com/{GITHUB_ORG}/cloudflare-zero-trust-tf`.

**Internal tools (Metabase, dashboards):** See `sre-triage/docs/infra-overview.md` → Observability section for URLs. Admin → People → Invite user → assign Group.

**AI tools (Claude, ChatGPT, etc.):** Log into team/org account → invite user email → assign seat/role → notify user.

**Outcome checklist:**
- [ ] Access granted in relevant system
- [ ] User notified
- [ ] Approver confirmed in Jira

## Playbook: OFFBOARDING

Apply items mentioned in the ticket:
- [ ] Gmail / Google Workspace — disable, transfer Drive data
- [ ] Slack — deactivate account
- [ ] Claude / ChatGPT — remove from org
- [ ] VPN (Cloudflare Zero Trust + OpenVPN) — remove from access groups
- [ ] GitHub (`{GITHUB_ORG}` org) — remove member
- [ ] Jira & Confluence — deactivate Atlassian account
- [ ] AWS SSO — remove from AWS Identity Center
- [ ] Internal tools (Metabase, etc.) — deactivate user

> ⚠️ Revoke email **last** — needed for password resets during offboarding.

## Playbook: NEW RESOURCE

**New database (MySQL or PostgreSQL):**

> ⚠️ **DB is created via SQL command, not Terraform.** RDS instances are not managed by Terraform. Only provision a new RDS instance if the ticket explicitly says "create new DB instance" / "new RDS". Default is always: CREATE DATABASE in the existing instance.

MySQL (connect as admin, then):
```sql
CREATE DATABASE {db_name};
CREATE USER '{app_name}'@'10.10.%.%' IDENTIFIED BY '{strong-password}';
GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{app_name}`@`10.10.%.%`;
FLUSH PRIVILEGES;
-- For staging/prod also grant awsdms_control:
GRANT ALL PRIVILEGES ON `awsdms_control`.* TO '{app_name}'@'10.%.%.%';
```

PostgreSQL (connect as postgres admin, then):
```sql
CREATE USER {app_name} WITH PASSWORD '{strong-password}';
CREATE ROLE {app_name}_role;
GRANT {app_name}_role TO {app_name};
CREATE DATABASE {app_name} OWNER {app_name}_role;
\c {app_name}
GRANT USAGE ON SCHEMA public TO {app_name}_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO {app_name}_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {app_name}_role;
ALTER SCHEMA public OWNER TO {app_name}_role;
\q
```

After creating the DB: update the app's Secrets Manager entry (`{SECRET_PREFIX_FOR_ENV}-{app-name}`) with the new `DATABASE_URL` / connection string, then force ESO resync + restart.

See `sre-triage/cmd-samples/mysql-db-ops.md` and `postgresql-db-ops.md` for full patterns including dump/restore and read-only grants.

**New Redis instance:**

> Redis may run as Docker Compose on dedicated EC2 servers or as ElastiCache — check `sre-config.md` and `sre-triage/docs/infra-overview.md` for your setup.
> If running on EC2: one instance (container) per service, one folder per instance.

Steps for EC2-hosted Redis:
1. SSH into the target Redis server (host from `sre-config.md` for the target env).
2. Find the next free port: `grep -r "EXPOSED_PORT" /data/{env}/*/.env | sort -t= -k2 -n | tail -3`
3. Create folder `/data/{env}/{env}-{service-name}/` with `data/` and `config/` subdirs.
4. Write `.env`: `REDIS_PASSWORD={strong-password}` + `EXPOSED_PORT={next-port}`
5. Copy `sre-triage/configs/compose/redis.yml` and start: `docker compose -f redis.yml up -d`
6. **Check if new port is within the current SG range** (see `sre-triage/cmd-samples/redis-ops.md`). If it exceeds the `to_port`, update the security group in Terraform and apply.
7. Add to app config:
   - `REDIS_HOST` + `REDIS_PORT` → Helm values (`values-{env}.yaml`) as plain env vars
   - `REDIS_PASSWORD` → Secrets Manager `{SECRET_PREFIX_FOR_ENV}-{app-name}`, then force ESO resync + restart

See `sre-triage/cmd-samples/redis-ops.md` for full detail including port range tables and connect/debug commands.

**New app:** Generate Helm chart (`helm/apps/{app}/`), ArgoCD Application manifest, GitHub Actions workflows (prepare → build-and-push → deploy via your CI/CD actions), ExternalSecret if needed. Register with `kubectl apply -k argocd/overlays/{env}`.

**New S3 bucket:**
```hcl
resource "aws_iam_user" "{service}-{env}" { name = "{service}-{env}" }
module "{service}-{env}" {
  source      = "./modules/s3-default-perm"
  bucket_name = "{service}-{env}"
  white_list_full_access_identifiers = [aws_iam_user.{service}-{env}.arn]
}
```

**New ECR repo:**
```hcl
module "{service}" {
  source = "./modules/ecr"
  name   = "{service}"
}
```

**New email/SES:** AWS Console → SES → Verified identities → Create identity → verify domain → create SMTP credentials (IAM user + SESFullAccess) → send credentials via secure channel (not Jira).

## Playbook: DEBUG / INCIDENT

**Pod CrashLoopBackOff / app down:**
```bash
kubectl get pods -n {namespace} -l app={app-name}
kubectl describe pod -n {namespace} {pod-name}
kubectl logs -n {namespace} {pod-name} --tail=100
kubectl logs -n {namespace} {pod-name} --previous --tail=100
argocd app get {app-name}-{env}
```
Common causes: secret not found (check ESO), wrong image (ArgoCD spec), resource limits (Helm values), dependency not ready (DB/RabbitMQ/Redis).

**OOMKilled:**
```bash
kubectl top pod -n {namespace} -l app={app-name}
kubectl describe pod -n {namespace} {pod-name} | grep -A5 OOM
```
Fix: increase `resources.limits.memory` in `helm/apps/{app}/values-{env}.yaml`, commit and sync.

**HTTP 502/504:**
```bash
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx \
  --tail=100 | grep {hostname}
kubectl get endpoints -n {namespace} {app-name}
```

**S3 403 AccessDenied:** Add user ARN to `white_list_full_access_identifiers` in `s3-*.tf` (see INFRA_CHANGE → S3 IAM).

**Observability links** — read URLs from `sre-config.md`:
- Logs: `{LOGS_URL}` → filter by deployment name
- Metrics: `{GRAFANA_URL}`
- Tracing: `{TRACING_URL}`

## Playbook: TRIAGE (UNKNOWN)

1. Summarize what was understood from the ticket.
2. Ask 2–3 focused clarifying questions (env? app name? deploy or config change? urgent?).
3. Save a `Template C` notification to `output/alerts/` with the inline questions.
4. **Do NOT create a guide** until classified.
