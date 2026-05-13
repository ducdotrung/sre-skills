# Triage Publishing Steps

Used by Steps 5–8 of `.claude/skills/sre-triage.md`.

Read `sre-config.md` (or `sre-config.example`) to get `JIRA_PROJECT`, `JIRA_BASE_URL`, `CONFLUENCE_SPACE`, and Confluence parentId values before running any step here.

---

## Step 5 — Deduplicate and save resolution guide

Check if a guide for this ticket already exists locally:

```bash
ls output/guides/{TICKET_KEY}-*.md 2>/dev/null
```

- **File exists** → skip creation, reuse the existing file path. Log: `⏭️ Guide already exists for {TICKET_KEY}, skipping.`
- **No file** → create `output/guides/{TICKET_KEY}-{kebab-case-title}.md`.

**File name format:** `output/guides/{TICKET_KEY}-{kebab-case-title}.md`

**Folder tag** — add as a comment on line 2 of the file (for human navigation):

| Type | Folder tag |
|---|---|
| `DEPLOY`, `DIFY` | `deploy-release` |
| `SECRET` | `secrets-credentials` |
| `DEBUG` | `debug-incidents` |
| `NEW_RESOURCE` | `new-resources` |
| `DNS`, `DNS_ZT` | `dns-zero-trust` |
| `INFRA_CHANGE` | `infra-changes` |
| `ACCOUNT_MGMT`, `OFFBOARDING` | `account-mgmt` |
| `UNKNOWN` | Do not create guide |

**File content:** Full playbook output — context, steps, bash code blocks, outcome checklist — **plus** the `## 🖥️ Execution Script` section at the bottom (format below).

**Execution Script section** — append to every guide file, after the outcome checklist:

Section heading: `## 🖥️ Execution Script`

First line: `**Labels:** \`EXECUTABILITY: {executability_label}\` | \`SAFETY: {safety_label}\``

Legend line: `> \`[SAFE]\` run immediately · \`[CAUTION]\` verify before running · \`[RISKY]\` ⚠️ explicit confirmation required · \`[MANUAL]\` fill in by hand; skip in automated execution`

Number each step from 1. Prefix each step description with its tag in brackets. Include a `bash` code block for each automated step. For `[MANUAL]` steps, list what the SRE must supply or complete by hand.

Close the section with: `_After execution: update Jira status → Done and post a summary in the team channel._`

**Tag assignment rules:**

| Step type | Tag |
|---|---|
| Pre-flight checks, ECR / image lookups, read-only queries | `[SAFE]` |
| Secret / ENV updates, ESO resync, pod restarts, S3 sync | `[CAUTION]` |
| Prod deploy (`argocd app sync *-prod`), SQL migration, `terraform apply` | `[RISKY]` |
| Steps with `{TBD}` placeholders or manual UI actions (GitHub settings, Metabase) | `[MANUAL]` |

**After the guide is created or already existed**, post a Jira comment using `addCommentToJiraIssue` with `contentFormat: "markdown"`:

```
📄 Resolution guide: `output/guides/{TICKET_KEY}-{kebab-case-title}.md`

— SRE Bot 🤖
```

<!-- ☁️ To publish to Confluence instead of saving locally:
1. Set CONFLUENCE_SPACE and the Confluence parentId values in sre-config.md.
2. Before creating, call searchConfluenceUsingCql:
   space = "{CONFLUENCE_SPACE}" AND title ~ "[{TICKET_KEY}]"
   If a page is found, reuse it (skip creation).
3. Call createConfluencePage with:
   - spaceKey: {CONFLUENCE_SPACE}
   - parentId: {value from sre-config.md for this ticket type}
   - title: "[{TICKET_KEY}] {ticket title} — Resolution Guide"
   - format: markdown
4. Post the Confluence URL as the Jira comment instead of the local path.
-->

---

## Step 6 — Update Triage Dashboard

Maintain one persistent local file `output/dashboard/triage-dashboard.md` as a running log.

1. **File not found** → create `output/dashboard/triage-dashboard.md` with the table format below.
2. **File exists** → read content → prepend new rows at the top of the table → write back. Keep at most 50 rows; drop the oldest if exceeded.

**File format (markdown):**

```markdown
# SRE Triage Dashboard

*Last updated: {ISO timestamp} by SRE Bot*

| Ticket | Title | Type | Executability | Safety | Env | Guide | Date |
|---|---|---|---|---|---|---|---|
| [{TICKET_KEY}]({JIRA_BASE_URL}/browse/{TICKET_KEY}) | {title} | {type} | {executability} | {safety} | {env} | [📄 Guide](../../output/guides/{filename}.md) | {YYYY-MM-DD} |
```

<!-- ☁️ To maintain the dashboard in Confluence instead:
1. Set CONFLUENCE_SPACE in sre-config.md.
2. Search: title = "SRE Triage Dashboard" AND space = "{CONFLUENCE_SPACE}"
3. If not found, create with createConfluencePage (parentId: root folder from sre-config.md).
   Log the returned pageId and add it to sre-config.md as TRIAGE_DASHBOARD_PAGE_ID.
4. If found, fetch with getConfluencePage, prepend new rows, then call updateConfluencePage.
-->

---

## Step 7 — Save notification

Save one notification file per ticket batch to `output/alerts/{YYYY-MM-DD}-triage-summary.md`.
Append to the file if it already exists for today.

**Use the exact template from `sre-triage/templates/alert-notification-template.md`.** Pick exactly one variant per ticket based on the outcome:

| Outcome | Template to use |
|---|---|
| Classified + guide complete | **Template A — Guide ready ✅** |
| Classified + missing required fields (Jira comment already posted) | **Template B — Needs more info ❓** |
| Type is `UNKNOWN` (no guide created) | **Template C — Needs triage ⚠️** |

<!-- ☁️ To notify Slack instead of saving locally:
1. Set SLACK_TEAM_CHANNEL in sre-config.md.
2. Call slack_send_message with channel_id = {SLACK_TEAM_CHANNEL}.
3. Post one message per ticket using the template from alert-notification-template.md.
-->

---

## Step 8 — Backlog summary

After processing new tickets, compile a watch list of tickets that are:
- Created within the last 7 days AND still in "To Do", "Open", or "In Progress"
- Stale or blocked for 24h+

Use **live status from Step 1** — do not use cached status. If a ticket no longer appears in the JQL results, mark it ✅ Resolved.

Backlog table columns: **Ticket | Type | Age | Live Status | Notes/Blocker**

Append the backlog summary to `output/dashboard/triage-dashboard.md` under a `## Backlog Watch List` section.
