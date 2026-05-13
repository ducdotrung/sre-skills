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

When the ticket contains SQL — either as one or more GitHub SQL file URLs or as inline SQL blocks in the description — apply the following review for **each** script or block:

1. **Fetch / extract the SQL content:**
   - **GitHub URL:** convert to raw URL and fetch:
     `https://github.com/{your-github-org}/{repo}/blob/{branch}/{path}.sql` → `https://raw.githubusercontent.com/{your-github-org}/{repo}/{branch}/{path}.sql`
   - **Local repo** (`.local-repos` has the repo path): read `{local-path}/{path}.sql` directly.
   - **Inline SQL** (pasted in ticket description): extract the SQL block as-is; no fetch needed.

2. Read the script and check for every item below:

| Risk | What to look for |
|---|---|
| 🔴 Full-table wipe | `DELETE FROM {table}` or `UPDATE {table} SET` **without a `WHERE` clause** |
| 🔴 Data loss | `DROP TABLE`, `DROP DATABASE`, `TRUNCATE TABLE` |
| 🔴 Breaking schema change | `DROP COLUMN`, `RENAME COLUMN` — app may still reference the old name |
| 🟠 Table lock (MySQL) | `ALTER TABLE` adding a `NOT NULL` column **without a `DEFAULT`** on a large table |
| 🟠 Type change risk | `MODIFY COLUMN` / `ALTER COLUMN ... TYPE` — implicit cast may fail or truncate data |
| 🟠 No transaction wrapper | Script not wrapped in `START TRANSACTION` / `BEGIN` … `COMMIT` — partial apply on failure |
| 🟠 Sequence / auto_increment reset | `ALTER TABLE … AUTO_INCREMENT =` or `SELECT setval(…)` — collision risk if value too low |
| 🟡 Unindexed large write | Mass `INSERT`/`UPDATE`/`DELETE` on a large table without batching — may cause lock timeout |
| 🟡 Run order dependency | Script references objects created later in the same batch |

3. **If any 🔴 or 🟠 risk is found**, post a Jira comment using `addCommentToJiraIssue` **before proceeding**:

```
⚠️ SQL Script Review — Potential Risk Found

File: {github_url}

{For each risk found:}
🔴/🟠 **{Risk name}**
Line ~{n}: `{offending SQL snippet}`
Concern: {plain-English explanation of what could go wrong}
Suggestion: {how to fix or mitigate}

Please confirm you have reviewed and are OK to proceed, or update the script.

— SRE Bot 🤖
```

4. If all checks pass (only 🟡 or none), proceed without a comment — note in the guide that scripts were reviewed and look clean.

5. **Rollback check** — Regardless of risk level, check whether the script (or ticket description) includes a rollback / undo plan. Look for: a `-- rollback` section, a backup-table creation step, or explicit undo instructions from the developer.

   If **no rollback is provided**, always post a dedicated Jira comment (separate from the risk comment, or appended to it if one was already posted):

   ```
   ⚠️ SQL Rollback — No rollback script provided

   File: {github_url | "inline SQL in ticket description"}

   A rollback plan was not found. **Developer should provide the authoritative rollback script — they know the data best.** The sample below is SRE-generated for reference only.

   🔁 Suggested rollback (reference only):

   {For each mutating statement in the script, generate the matching rollback pattern:}

   -- Before UPDATE or DELETE: create a backup table immediately before execution
   CREATE TABLE {table}_backup_{YYYYMMDD} AS SELECT * FROM {table} WHERE {same_condition};

   -- Rollback UPDATE: restore original values from backup
   UPDATE {table} t JOIN {table}_backup_{YYYYMMDD} b ON t.{pk} = b.{pk}
     SET {each changed column} = b.{column};

   -- Rollback DELETE: re-insert from backup
   INSERT INTO {table} SELECT * FROM {table}_backup_{YYYYMMDD};

   -- Rollback INSERT: delete inserted rows
   DELETE FROM {table} WHERE {identifying_col} IN ({inserted_values});
   -- If auto_increment was advanced, reset it:
   ALTER TABLE {table} AUTO_INCREMENT = {previous_value};

   -- Rollback ALTER TABLE ADD COLUMN:
   ALTER TABLE {table} DROP COLUMN {new_column};

   -- Rollback CREATE TABLE:
   DROP TABLE IF EXISTS {new_table};

   ⚠️ The _backup_{YYYYMMDD} table must be created immediately before execution, within the same DB session. Confirm the backup was created before running the main script.

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
