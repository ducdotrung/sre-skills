# Claude SRE Assistant — How It Works

> **Audience:** SRE team members using the Claude SRE Assistant in their day-to-day workflow.
> **Purpose:** Explain what the assistant does, how to set it up, and how to use each skill effectively.

---

## Table of Contents

1. [What Is the SRE Assistant?](#1-what-is-the-sre-assistant)
2. [Two Ways to Run It](#2-two-ways-to-run-it)
3. [Setup: Claude Code CLI (Option A)](#3-setup-claude-code-cli-option-a)
4. [Setup: claude.ai Co-work (Option B)](#4-setup-claudeai-co-work-option-b)
5. [Skills Overview](#5-skills-overview)
6. [How /sre-triage Works](#6-how-sre-triage-works)
7. [Ticket Classification Types](#7-ticket-classification-types)
8. [Safety & Executability Labels](#8-safety--executability-labels)
9. [How /sre-execute Works](#9-how-sre-execute-works)
10. [The Local Repo Map (.local-repos)](#10-the-local-repo-map-local-repos)
11. [Tips & Common Patterns](#11-tips--common-patterns)

---

## 1. What Is the SRE Assistant?

The Claude SRE Assistant is a set of **Claude Code skills** that automate the {YourCompany} SRE ticket workflow:

1. Fetch open `INF` Jira tickets
2. Classify each ticket by type and risk level
3. Check for missing information and comment on Jira if needed
4. Generate a step-by-step resolution guide and publish it to Confluence
5. Update the SRE Triage Dashboard
6. Send a Slack notification to `#sre-team`
7. Maintain a backlog watch list

A second skill (`/sre-execute`) takes any ticket with a published guide and walks through it interactively — pausing for confirmation on risky steps, collecting placeholder values, and posting the completion result to Jira and Slack.

---

## 2. Two Ways to Run It

| Mode | Best For | Requires |
|---|---|---|
| **Claude Code CLI** | Running `/sre-execute` — executing commands locally | Claude Code installed, MCP integrations |
| **claude.ai Co-work** | `/sre-triage` planning from any browser | claude.ai SRE project, zip upload |

Both modes use the same skill logic. The CLI has the advantage of being able to run shell commands (`kubectl`, `aws`, `terraform`) directly in your terminal.

---

## 3. Setup: Claude Code CLI (Option A)

This is the **recommended** mode for full workflow execution.

### Prerequisites

- [Claude Code](https://claude.ai/code) installed
- Atlassian MCP integration enabled (Jira + Confluence)
- Slack MCP integration enabled

### Steps

```bash
# 1. Clone the sre-skill repo and open it in Claude Code
git clone github.com/{your-github-org}/sre-skill
cd sre-skill
claude  # or open in VS Code with Claude Code extension

# 2. Set up your local repo map (one-time)
cp .local-repos.example .local-repos
# Edit .local-repos — set each path to where you've cloned the repo locally
# This file is gitignored; never commit it
```

### Running a skill

In the Claude Code chat:

```
/sre-triage
```

or

```
/sre-execute INF-7131
```

---

## 4. Setup: claude.ai Co-work (Option B)

Use this when you want to run triage from the browser without the CLI.

### Steps

```bash
# 1. Build the upload zip
bash pack.sh
# → creates sre-skill-YYYYMMDD.zip

# 2. Go to claude.ai → open your SRE co-work project
# 3. Project knowledge → upload the zip
# 4. Claude loads CLAUDE.md as instructions and sre-triage/ files as context

# To update after code changes: run pack.sh again,
# delete the old zip from Project knowledge, upload the new one
```

---

## 5. Skills Overview

| Skill | Command | What It Does |
|---|---|---|
| **SRE Triage** | `/sre-triage` | Fetch open INF tickets → classify → generate resolution guides → publish to Confluence → notify Slack → backlog summary |
| **SRE Execute** | `/sre-execute INF-XXXX [--dry-run]` | Execute a ticket's resolution guide step-by-step with SAFE/CAUTION/RISKY/MANUAL confirmations → post completion to Jira and Slack |

---

## 6. How /sre-triage Works

Running `/sre-triage` triggers the following 8 steps automatically for each open INF ticket:

### Step 1 — Fetch Tickets

Queries Jira for open `INF` tickets created or updated in the **last 7 days** (status: To Do / Open / In Progress, excluding sub-tasks, epics, and sprint goals).

### Step 2 — Classify

Reads the ticket title and description, assigns a **type** (see Section 7), and computes a **base safety label** (see Section 8).

### Step 3 — Check for Missing Info

Verifies that the minimum required fields are present for the ticket type. If something is missing:
- Posts a comment on the Jira ticket requesting the missing info
- Still generates a partial Confluence page, marking unknown fields as `{TBD — awaiting requester input}`
- If the ticket has no actionable info at all, skips the page and marks it `Needs more info ❓`

### Step 4 — Execute Playbook

Loads the matching playbook reference for the ticket type and generates a full, ordered resolution guide. For deploy tickets with SQL, this includes fetching and reviewing SQL scripts for risk (see [SQL Review](#sql-review)).

### Step 5 — Publish to Confluence

Creates a resolution guide page in the correct Confluence sub-folder under `Ticket Resolutions`. The page title is `[INF-XXX] {ticket title} — Resolution Guide`.

Before creating, deduplication is performed — if a page already exists for that ticket key, it is reused and no duplicate is created.

Each Confluence page includes an **Execution Script section** at the bottom (used by `/sre-execute`), with steps tagged `[SAFE]`, `[CAUTION]`, `[RISKY]`, or `[MANUAL]`.

A Jira comment is posted with a link to the Confluence page.

### Step 6 — Update Triage Dashboard

Adds a row to the persistent **SRE Triage Dashboard** page on Confluence, keeping a running log of all processed tickets with their type, safety level, executability, and guide link.

### Step 7 — Notify Slack

Posts one message per ticket to `#sre-team` using a standard template:
- **Guide ready ✅** — guide created with full info
- **Needs more info ❓** — Jira comment posted requesting missing fields
- **Needs triage ⚠️** — ticket type is UNKNOWN, clarifying questions included

### Step 8 — Backlog Summary

Compiles a watch list of tickets still open after the run. Checks live Jira status (not cached) and flags stale/blocked tickets.

---

### SQL Review

When a DEPLOY ticket contains SQL scripts (linked GitHub URLs or inline blocks), the assistant automatically:

1. Fetches each SQL script
2. Scans for risks by severity:

| Icon | Risk | Example |
|---|---|---|
| 🔴 | Data loss / breaking change | `DROP TABLE`, `TRUNCATE`, `DELETE` without `WHERE`, `DROP COLUMN` |
| 🟠 | Potential lock or type issue | `ALTER TABLE` without DEFAULT on large table, no transaction wrapper |
| 🟡 | Large unindexed write | Mass `INSERT`/`UPDATE` without batching |

3. If 🔴 or 🟠 risks are found: posts a Jira comment before proceeding
4. If no rollback plan is found in the script: posts a Jira comment with a suggested rollback template

This happens **before** generating the resolution guide, so the developer can respond with fixes or confirmation.

---

## 7. Ticket Classification Types

| Type | Keywords / Signals |
|---|---|
| `DEPLOY` | RELEASE, deploy, rollout, image tag, `[PROD]`, `[STAG]`, `[UAT]`, version, hotfix, docker image |
| `INFRA_CHANGE` | scale, replica, CORS, S3 bucket, nginx, timeout, ENV var, IAM, CDN, EKS, Terraform, WAF, RDS |
| `SECRET` | secret, credential, token, key, password, rotate, AWS Secrets Manager, `<sent via email>`, `<SRE-To be updated>` |
| `ACCOUNT_MGMT` | grant access, invite, add to repo, GitHub access, Metabase, VPN, ZeroTrust, Claude account, AI tool |
| `OFFBOARDING` | offboard, deactivate, delete account, remove access, leaving |
| `DNS` | DNS, domain, CNAME, A record, Cloudflare, Route53, {yourcompany}.ai, {your-org}.com |
| `DNS_ZT` | zero trust, ZT, VPN, Cloudflare Access, tunnel |
| `NEW_RESOURCE` | new app, new service, onboard, create repo, create bucket, add ECR, new ingress, setup email, new database, new redis |
| `DEBUG` | down, crash, error, OOM, 502, 504, 503, pod restart, CrashLoopBackOff, not working, incident, 403 |
| `DIFY` | Dify, flow, knowledge, workflow, import flow |
| `UNKNOWN` | Cannot confidently classify |

**Priority rules:**
- `[RELEASE]` or `[PROD/STAG/UAT]` + image tag → always `DEPLOY`, even if ENV/SQL/S3 steps are present
- "Create new database" → `NEW_RESOURCE` (SQL command in existing RDS instance)
- "Create new RDS instance" → `INFRA_CHANGE` (provision new RDS — rare)

---

## 8. Safety & Executability Labels

### Safety Labels

Computed per ticket based on type and target environment. Used by `/sre-execute` to decide how to handle each step.

| Label | Meaning | Examples |
|---|---|---|
| **SAFE** | Read-only or low-risk operation | ECR image lookup, pod status check, log read |
| **CAUTION** | Makes changes, but reversible | Secret update, ESO resync, pod restart, S3 sync |
| **RISKY** | Potentially irreversible or prod-impacting | `argocd app sync *-prod`, SQL migration, `terraform apply` |
| **MANUAL** | Requires human action via a UI or has missing placeholders | GitHub access grant, Metabase invite, TBD values |

**Environment modifier:** Production environment escalates safety by one level (SAFE → CAUTION, CAUTION → RISKY). Dev/UAT de-escalates by one level.

### Executability Labels

Determines whether the guide can be executed.

| Label | Meaning |
|---|---|
| `READY` | All required info present — can execute immediately |
| `PARTIAL` | Some `{TBD}` fields — Jira comment posted, steps will need manual fill-in |
| `BLOCKED` | Missing critical info, or pending secret (not yet received) |

`/sre-execute` will refuse to run a `BLOCKED` ticket and explain what is needed.

---

## 9. How /sre-execute Works

Running `/sre-execute INF-XXXX` does the following:

### Pre-flight

1. Fetches the Jira ticket to check its status (warns if already Done)
2. Finds the Confluence resolution guide (from the Jira comment, or by search)
3. Reads the `## 🖥️ Execution Script` section — extracts steps and labels
4. Gates on `EXECUTABILITY`: refuses to run `BLOCKED` tickets
5. Assigns the ticket to the current user in Jira

### Execution Plan

Prints all steps with their tags before running anything:

```
📋 Execution plan for [INF-7131] [cc-backend] Deploy v1.2.3 to prod
SAFETY: RISKY | EXECUTABILITY: READY
──────────────────────────────────────────────
Step 1  [SAFE]    Verify image exists in ECR
Step 2  [SAFE]    Check current ArgoCD app status
Step 3  [CAUTION] Update secret in AWS Secrets Manager
Step 4  [RISKY]   argocd app sync cc-backend-prod
Step 5  [SAFE]    Verify pods are Running/Ready
Step 6  [RISKY]   Rollback (only if needed)
──────────────────────────────────────────────
Total: 6 steps (2 SAFE · 1 CAUTION · 2 RISKY · 0 MANUAL)
```

Use `--dry-run` to see the full plan with all commands without executing anything.

### TBD Collection

Before executing, scans all step commands for `{TBD ...}` placeholders and asks for each value interactively. Substitutes provided values across all steps.

### Step Execution

| Tag | Behavior |
|---|---|
| `[SAFE]` | Runs automatically; shows output |
| `[CAUTION]` | Shows the command and asks: `[y] run  [s] skip  [a] abort` |
| `[RISKY]` | Shows warning + command; requires typing `yes` to proceed |
| `[MANUAL]` | Shows instructions; waits for `done` / `skip` / `abort` |

On any command failure, offers to run the rollback step, then asks: `[r] retry  [s] skip  [a] abort`.

### Post-completion

After all steps are done (or skipped):
1. Posts a completion comment on the Jira ticket
2. Transitions the ticket to `In Review`
3. Posts a Slack notification to `#sre-team`

---

## 10. The Local Repo Map (.local-repos)

The skills can read actual files from your local clones of the {YourCompany} repos (Helm values, Terraform configs, SQL scripts) instead of always fetching from GitHub. This is faster and works offline.

**Setup:**

```bash
cp .local-repos.example .local-repos
# Edit .local-repos — fill in the local path for each repo you have cloned
```

**Format** (one entry per line, `#` for comments):

```
k8s-manifest=~/DevOps/k8s-manifest
terraform=~/DevOps/terraform
```

If a repo is not in `.local-repos`, the skill attempts auto-discovery under `~/DevOps`. If still not found, references in step commands are marked `{TBD — add {repo-name} to .local-repos}`.

`.local-repos` is gitignored — never commit it (it contains paths specific to your machine).

---

## 11. Tips & Common Patterns

### Run triage for a specific ticket window

```
/sre-triage
```
Default is last 7 days. To override, say:  
*"Check INF tickets from the last 30 days"* — the skill adjusts the JQL window.

### Execute with a dry run first

```
/sre-execute INF-7131 --dry-run
```
Prints all steps and commands without running anything. Use this to review what will happen before committing.

### What to do when a ticket is BLOCKED

The assistant posts a comment on the Jira ticket with the exact missing fields. Reply on the ticket or update the description, then re-run `/sre-triage` for that ticket. The deduplication logic will update the existing page rather than create a duplicate.

### Confluence sub-folder map

Resolution guides are filed automatically based on ticket type:

| Ticket Type | Confluence Sub-folder |
|---|---|
| `DEPLOY`, | Deploy & Release |
| `SECRET` | Secrets & Credentials |
| `DEBUG` | Debug & Incidents |
| `NEW_RESOURCE` | New Resources & Onboarding |
| `DNS`, `DNS_ZT` | DNS & Zero Trust |
| `INFRA_CHANGE` | Infrastructure Changes |
| `ACCOUNT_MGMT`, `OFFBOARDING` | Ticket Resolutions (root) |
| `UNKNOWN` | No page created |

### Secret values and security

`/sre-execute` never logs secret values to the terminal. If a command contains a secret placeholder, the step is marked `[MANUAL]` and you are prompted to run it in a separate session.
