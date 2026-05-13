# Triage Playbook: DEPLOY

Used by Step 4 of `.claude/skills/sre-triage.md` when the ticket type is `DEPLOY`.

Read `sre-config.md` to get cluster names, secret prefixes, ECR prefix, and AWS region before generating commands.

Parse from description: app name, target env, image tag, rollback image.

**Detect sub-steps first** — execute these *before* the image deploy if present:

| Signal | Sub-step |
|---|---|
| `Config/Secret update` section | Update AWS Secrets Manager first |
| `<sent via email>` / `<SRE-To be updated>` | ⚠️ Secret pending — do not deploy until received |
| `ENV:` section | Update Helm values or Secrets Manager |
| `SQL:` section with GitHub URL(s) | **Fetch + review each script first**, then run migration (check if before or after deploy) |
| `S3 Migration:` / `s3://` sync | Run `aws s3 sync` |
| `clean the cache` / CDN cache | Invalidate CloudFront |
| `Backup` tables | Take RDS snapshot first |

**SQL Script Review (run before generating the ordered guide):**

When the ticket contains SQL — either as one or more GitHub SQL file URLs or as inline SQL blocks in the description — **delegate to the `sql-reviewer` sub-agent**:

```
Use the sql-reviewer agent with:
- Ticket key: {TICKET_KEY}
- Target environment: {env}
- SQL inputs: {list of GitHub URLs and/or inline SQL blocks from the ticket}
```

The agent will fetch all scripts, run the full risk checklist, check rollback coverage, and return a structured report. Wait for the report before continuing.

**Act on the report:**

| Report outcome | Action |
|---|---|
| 🔴 CRITICAL risk found | Post a Jira comment with the agent's findings. Block deploy until developer addresses. Set SAFETY = RISKY. |
| 🟠 HIGH risk found | Post a Jira comment with the agent's findings. Proceed at SRE discretion. |
| 🟡 MEDIUM or 🟢 OK | Note in the guide that scripts were reviewed and look clean. No Jira comment needed. |
| Missing rollback (any risk level) | Include the agent's generated rollback reference in the Jira comment. |
| FETCH_FAILED for any URL | Note in guide and Jira that the script could not be fetched and must be reviewed manually. |

**Jira comment format (when posting findings):**

```
⚠️ SQL Script Review — {risk level} Risk Found

{Paste the agent's Findings table for each affected script}

{If rollback missing:}
🔁 Suggested rollback (SRE-generated reference — developer should supply authoritative version):
{Paste the agent's generated rollback SQL}

Please confirm you have reviewed and are OK to proceed, or update the script.

— SRE Bot 🤖
```

**S3 Rollback check** — If the ticket includes an `aws s3 sync`, `aws s3 cp`, or `aws s3 rm` command, check whether a rollback plan is provided (e.g. "revert to version X" or a saved copy step). If not, always post a Jira comment:

```
⚠️ S3 Rollback — No rollback plan provided

No rollback plan was found for the S3 operation. Ensure your S3 buckets have versioning enabled.

🔁 Suggested rollback approach (reference only):

# Step 0 — Before executing, record the current version IDs (run this first)
aws s3api list-object-versions \
  --bucket {bucket-name} \
  --prefix {affected-prefix}/ \
  --region {AWS_PRIMARY_REGION} \
  --query 'Versions[?IsLatest].[Key,VersionId,LastModified]' \
  --output table

# Step 1a — Restore a specific object to its previous version
aws s3api copy-object \
  --bucket {bucket-name} \
  --copy-source "{bucket-name}/{key}?versionId={recorded-version-id}" \
  --key {key} \
  --region {AWS_PRIMARY_REGION}

# Step 1b — Restore a deleted object (remove the delete marker)
aws s3api delete-object \
  --bucket {bucket-name} \
  --key {key} \
  --version-id {delete-marker-version-id} \
  --region {AWS_PRIMARY_REGION}

⚠️ Run Step 0 BEFORE the sync so you have the version IDs on hand. Developer should confirm which version is the correct rollback target.

— SRE Bot 🤖
```

**Generate ordered guide:** pre-flight → secrets → SQL review → S3 sync → SQL/backup → deploy → verify → rollback.

```bash
# Pre-flight — substitute {ECR_PREFIX} and {AWS_PRIMARY_REGION} from sre-config.md
aws ecr describe-images --repository-name {ecr-repo-name} \
  --image-ids imageTag={tag} --region {AWS_PRIMARY_REGION}
argocd app get {app-name}-{env}

# S3 sync (if needed)
aws s3 sync s3://{source}/{path}/ s3://{dest}/{path}/ --region {AWS_PRIMARY_REGION}

# RDS backup + SQL (if needed)
aws rds create-db-snapshot --db-instance-identifier {rds-instance} \
  --db-snapshot-identifier {app}-pre-{version}-$(date +%Y%m%d)

# CloudFront invalidation (if needed)
aws cloudfront create-invalidation --distribution-id {ID} --paths "/*"

# Deploy (staging/prod = manual sync)
argocd app sync {app-name}-{env}
argocd app wait {app-name}-{env} --health --timeout 180
kubectl get pods -n {namespace} -l app={app-name}

# Rollback
argocd app rollback {app-name}-{env}
# or revert image tag commit in k8s-manifest and re-sync
```

**Outcome checklist:**
- [ ] SQL scripts fetched and reviewed (risks flagged on Jira if found)
- [ ] Sub-steps completed (secrets / S3 / SQL / cache as applicable)
- [ ] Image confirmed in ECR
- [ ] ArgoCD sync completed without errors
- [ ] All pods Running/Ready
- [ ] Smoke test passed on target URL
- [ ] No error spike in metrics dashboard (see `GRAFANA_URL` in sre-config.md)
