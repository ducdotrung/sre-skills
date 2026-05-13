---
description: Fetch open Jira tickets, classify them, generate resolution guides as local Markdown files, and save notifications. Run when the user says "check tickets", "process tickets", or "check tickets".
---

# SRE Ticket Triage

**Before starting:** Read `sre-config.md` (or `sre-config.example` if missing) to load:
- `JIRA_PROJECT` — Jira project key (e.g. `INF`)
- `JIRA_CLOUD_ID` — Jira cloud ID
- `JIRA_BASE_URL` — e.g. `https://your-org.atlassian.net`

Run all steps below **in order** for each ticket found.

---

## Step 1 — Fetch open tickets

Call `searchJiraIssuesUsingJql` with:
- cloudId: `{JIRA_CLOUD_ID from sre-config.md}`
- JQL: `project = {JIRA_PROJECT} AND issuetype not in subTaskIssueTypes() AND issuetype not in ("Epic", "Sprint Goal") AND status in ("To Do", "Open", "In Progress") AND (created >= -7d OR updated >= -7d) ORDER BY created DESC`
- Default window: the JQL above only returns tickets created or updated in the last 7 days. If the user specifies a different window, adjust the JQL before running it.
- Fields: `summary`, `description`, `issuetype`, `status`, `priority`, `labels`, `assignee`, `created`

### Local repo path resolution

At the start of each run, read `.local-repos` (project root) to build a `{repo-name → local-path}` map.

- Format: one `repo-name=~/path/to/clone` entry per line; `#` lines are comments.
- When a step needs a local file (Helm values, Terraform configs, SQL scripts), resolve via this map first.
- If the repo is not in `.local-repos`, attempt auto-discovery:
  ```bash
  find ~ -maxdepth 4 -type d -name "{repo-name}" 2>/dev/null | head -1
  ```
- If auto-found, use the path and suggest the SRE add it to `.local-repos`.
- If still not found, mark the reference as `{TBD — add {repo-name} to .local-repos}`.

See `.local-repos.example` for the full list of expected repo names.

---

## Step 2 — Classify each ticket

Read title + description and assign one type:

| Type | Keywords / Signals |
|---|---|
| `DEPLOY` | RELEASE, deploy, rollout, image tag, promote, `[PROD]`, `[STAG]`, `[UAT]`, version, hotfix, docker image |
| `INFRA_CHANGE` | scale, replica, CORS, S3 bucket, nginx, timeout, ENV var, IAM, presigned, CDN, EKS, Terraform, WAF, RDS |
| `SECRET` | secret, credential, token, key, password, rotate, AWS Secrets Manager, api key, `<sent via email>`, `<SRE-To be updated>` |
| `ACCOUNT_MGMT` | grant access, invite, add to repo, GitHub access, Metabase, VPN, ZeroTrust, Claude account, AI tool |
| `OFFBOARDING` | offboard, deactivate, delete account, remove access, leaving |
| `DNS` | DNS, domain, CNAME, A record, Cloudflare, Route53 |
| `DNS_ZT` | zero trust, ZT, VPN, Cloudflare Access, tunnel |
| `NEW_RESOURCE` | new app, new service, onboard, create repo, create bucket, add ECR, new ingress, setup email, new database, new db, CREATE DATABASE, new postgres db, new mysql db, new redis, redis instance, add redis |
| `DEBUG` | down, crash, error, OOM, 502, 504, 503, pod restart, CrashLoopBackOff, not working, incident, 403, AccessDenied |
| `DIFY` | Dify, flow, knowledge, workflow, Dify flow, import flow |
| `UNKNOWN` | Cannot confidently classify |

> **Priority rule:** `[RELEASE]` or `[PROD/STAG/UAT]` + image tag → always `DEPLOY`, even if ENV/SQL/S3 steps are present (those are sub-steps inside the DEPLOY playbook).
> **DB rule:** "create new database / new DB" → `NEW_RESOURCE` (SQL command in existing instance). "create new RDS instance / new DB server" → `INFRA_CHANGE` (provision new RDS — rare).

### Base SAFETY label (compute now, before Step 3)

| Ticket type | Sub-type / Signal | Base Safety |
|---|---|---|
| `DEBUG` | Read-only investigation, log review | SAFE |
| `ACCOUNT_MGMT` | Grant access, invite user | SAFE |
| `NEW_RESOURCE` | New DB, Redis, S3, ECR, email, new app | SAFE |
| `DNS` / `DNS_ZT` | Add a new record | SAFE |
| `DIFY` | Import / update flow or knowledge base | SAFE |
| `OFFBOARDING` | Account deactivation, revoke access | CAUTION |
| `DNS` / `DNS_ZT` | Modify or delete an existing record | CAUTION |
| `SECRET` | Update or rotate a secret value | CAUTION |
| `INFRA_CHANGE` | Scale, ENV update, nginx/Ingress, Terraform | CAUTION |
| `DEPLOY` | Standard image deploy (no SQL, or only 🟡 SQL) | CAUTION |
| `DEPLOY` | + SQL with 🟠 risk | CAUTION |
| `DEPLOY` | + SQL with 🔴 risk, or DROP / TRUNCATE / DELETE without WHERE | RISKY |

**Env modifier** (applied on top of base safety):

| Env | Effect |
|---|---|
| `prod` | +1 riskier: SAFE → CAUTION, CAUTION → RISKY, RISKY stays RISKY |
| `staging` | No change |
| `dev` / `uat` | −1 safer: RISKY → CAUTION, CAUTION → SAFE, SAFE stays SAFE |
| Multi-env ticket | Use the highest-risk env for the final label |

Final SAFETY = base + env modifier. Carry this value forward to Steps 5 and 7.

---

## Step 3 — Check for missing required info

Verify the minimum required fields are present. If any are missing, post a comment on Jira with `addCommentToJiraIssue`:

| Type | Required |
|---|---|
| `DEPLOY` | App name, target env, image tag or commit SHA |
| `INFRA_CHANGE` | App/service name, target env, specific change (new value). For ENV var updates: GitHub repo URL (to detect frontend vs backend) + variable name(s) + value(s) per env |
| `SECRET` | App name, target env, secret key name(s), new value(s) — or "sent via email" confirmation |
| `ACCOUNT_MGMT` | Full name/email, system(s), role/permission, approver |
| `OFFBOARDING` | Full name/email, official last day, list of systems to revoke |
| `DNS` / `DNS_ZT` | Domain/subdomain, record type, target value, env |
| `NEW_RESOURCE` | Resource name, target env, team/owner. For new databases: DB name, engine (MySQL/PostgreSQL), app user name, access level. For new Redis: service name, target env. |
| `DEBUG` | App/service name, env, symptom, time issue started |
| `DIFY` | Flow/KB name, target env, YAML link or content |
| `UNKNOWN` | Any info that would allow classification |

**Jira comment format when info is missing:**

```
👋 Hi team,

To process this ticket, we need the following information:

❓ [Missing field 1]
❓ [Missing field 2]

Please update the ticket description or reply here so we can proceed.

— SRE Bot 🤖
```

**After posting the comment:**
- Partial info → still create the resolution guide; mark missing fields as `{TBD — awaiting requester input}`.
- No actionable info at all → skip guide creation; post Jira comment + save notification with `Needs more info ❓` + `💬 Comment posted on Jira requesting missing info.`

**Finalize EXECUTABILITY label after completing this step:**

| Condition | EXECUTABILITY |
|---|---|
| All required info present, no pending secrets | `READY` |
| Some TBD fields — Jira comment posted, guide created with `{TBD}` markers | `PARTIAL` |
| Secret is `<sent via email>` / `<SRE-To be updated>` (value not yet received) | `BLOCKED` |
| Critical required fields completely missing | `BLOCKED` |
| Type is `UNKNOWN` (no guide will be created) | `BLOCKED` |

Both labels (EXECUTABILITY + final SAFETY) are now set. Use them in Steps 5 and 7.

---

## Step 4 — Execute the matching playbook

Load exactly one reference file based on the classified ticket type, then generate the full,
ordered resolution guide from that file.

| Type | Reference file |
|---|---|
| `DEPLOY` | `sre-triage/references/triage-playbook-deploy.md` |
| `INFRA_CHANGE`, `SECRET`, `DNS`, `DNS_ZT` | `sre-triage/references/triage-playbook-infra.md` |
| `ACCOUNT_MGMT`, `OFFBOARDING`, `NEW_RESOURCE`, `DIFY`, `DEBUG`, `UNKNOWN` | `sre-triage/references/triage-playbook-ops.md` |

Rules:
- Read only the reference file needed for the current ticket type.
- Execute the matching playbook there exactly as written.
- Preserve the computed `EXECUTABILITY` and `SAFETY` labels from Steps 2–3.
- For `UNKNOWN`, follow the unknown-triage instructions in the reference file and do not create a guide.

## Step 5 — Deduplicate and save resolution guide

Read `sre-triage/references/triage-publishing.md` and execute Step 5 from that file exactly.

## Step 6 — Update Triage Dashboard

Continue using `sre-triage/references/triage-publishing.md` and execute Step 6 exactly.

## Step 7 — Save notification

Continue using `sre-triage/references/triage-publishing.md` and execute Step 7 exactly.

## Step 8 — Backlog summary

Continue using `sre-triage/references/triage-publishing.md` and execute Step 8 exactly.
