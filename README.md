# sre-skill

A reusable Claude Code skill set for SRE / DevOps teams. Automates Jira ticket triage, generates resolution guides as local Markdown files, and saves notifications locally. Optionally publishes to Confluence and notifies Slack when those MCP integrations are configured.

## Quick start (Claude Code CLI / IDE)

1. Clone this repo and open the root folder as a Claude Code project.
2. **Configure your infrastructure** (one-time):
   ```bash
   cp sre-config.example sre-config.md
   # Edit sre-config.md — fill in your Jira project, AWS account, cluster names, etc.
   # sre-config.md is gitignored; never commit it.
   ```
3. **Set up your local repo map** (one-time):
   ```bash
   cp .local-repos.example .local-repos
   # Edit .local-repos — set each path to where you've cloned the repo on your machine.
   # .local-repos is gitignored; never commit it.
   ```
   The skills use this map to read Helm values, Terraform files, and SQL scripts directly from your local clones.
4. Make sure the **Atlassian (Jira/Confluence) MCP** is enabled in Claude Code (required for Jira; Confluence is optional).
5. Optionally enable the **Slack MCP** if you want Slack notifications (otherwise notifications go to `output/alerts/`).
6. Run a skill with its slash command (see table below).

## Quick start (claude.ai co-work)

1. Run the pack script to generate a dated zip:
   ```bash
   bash pack.sh
   # → creates sre-skill-YYYYMMDD.zip
   ```
2. Go to [claude.ai](https://claude.ai) → open your **SRE co-work project** → **Project knowledge** → upload the zip.
3. Claude will load `SKILL.md` as instructions and all files under `sre-triage/` as reference context.
4. Add your `sre-config.md` content to the project knowledge or paste it into the chat.
5. Trigger a skill by typing its slash command in chat, e.g. `/sre-triage`.

> **Re-uploading after changes:** run `bash pack.sh` again, delete the old zip from Project knowledge, and upload the new one.

## Skills

| Skill | Command | What it does |
|---|---|---|
| SRE Triage | `/sre-triage` | Fetch open tickets → classify → generate resolution guides (`output/guides/`) → update dashboard (`output/dashboard/`) → save notifications (`output/alerts/`) → backlog summary |
| SRE Execute | `/sre-execute TICKET-XXXX [--dry-run]` | Execute a single ticket's resolution guide step-by-step with SAFE/CAUTION/RISKY/MANUAL confirmations → post completion to Jira |

## Output directories

All output is saved locally by default. Cloud integrations are optional.

| Directory | Contents | Cloud alternative |
|---|---|---|
| `output/guides/` | Resolution guides per ticket | Confluence |
| `output/dashboard/` | Running triage dashboard | Confluence |
| `output/alerts/` | Triage and execution notifications | Slack |

> `output/` is gitignored — it's runtime state, not source code. Share guides with your team by committing them to a separate docs repo or publishing to Confluence via the MCP.

## Adapting to your team

Everything company-specific lives in two gitignored files:

| File | Purpose |
|---|---|
| `sre-config.md` (copy from `sre-config.example`) | AWS account, cluster names, Jira/Confluence IDs, server IPs, observability URLs |
| `.local-repos` (copy from `.local-repos.example`) | Local paths to your cloned infrastructure repos |

The playbooks and skill logic are fully generic — they reference `{placeholder}` values that get resolved from `sre-config.md` at runtime.

## Repository layout

```
CLAUDE.md                            shared context and rules (for Claude Code CLI)
SKILL.md                             co-work entry point (required for claude.ai upload)
sre-config.example                   template — copy to sre-config.md and fill in your values
pack.sh                              builds sre-skill-YYYYMMDD.zip for co-work upload
.local-repos.example                 template — copy to .local-repos and fill in your paths
.local-repos                         (gitignored) your machine's repo paths, read by skills
sre-config.md                        (gitignored) your team's infrastructure constants
output/                              (gitignored) runtime output — guides, dashboard, alerts
.claude/skills/
  sre-triage.md                      /sre-triage skill definition
  sre-execute.md                     /sre-execute skill — step-by-step ticket execution
sre-triage/
  docs/                              infra overviews (terraform, k8s, DNS, etc.)
    infra-overview.md                main infra architecture overview — customize for your team
  references/                        playbooks loaded on demand by the skills
    triage-playbook-deploy.md        deploy-specific guide generation
    triage-playbook-infra.md         infra, secret, and DNS guide generation
    triage-playbook-ops.md           account, resource, Dify, debug, and unknown triage
    triage-publishing.md             local file output steps (with cloud alternatives commented)
  cmd-samples/                       ready-to-use command reference
    mysql-db-ops.md                  MySQL: create DB/user, dump, restore, admin
    postgresql-db-ops.md             PostgreSQL: create DB/role, dump, restore, admin
    redis-ops.md                     Redis: provision new instance, SG ports, debug
    eks-kubectl.md                   EKS: kubeconfig, pod ops, ArgoCD, node drain
    aws-ops.md                       AWS: Secrets Manager, ECR, S3, SES, IAM
  templates/
    alert-notification-template.md   Notification templates (A/B/C variants)
    github-workflows/                CI/CD workflow templates grouped by app type
  configs/
    systemd/                         systemd unit files for DevOps servers
    compose/                         Docker Compose files (redis, grafana, etc.)
```

## Adding a new skill

1. Create `.claude/skills/{skill-name}.md` with a `description:` frontmatter field.
2. Create `{skill-name}/` at the repo root for supporting docs, templates, or configs.
3. Update `CLAUDE.md` if the skill needs shared constants or rules.
4. Add a row to the Skills table above.
5. Run `bash pack.sh` and re-upload to the co-work project.
