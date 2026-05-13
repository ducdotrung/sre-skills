---
description: Execute a resolved Jira ticket step-by-step using its resolution guide. Walks through SAFE/CAUTION/RISKY/MANUAL steps with appropriate confirmations, collects TBD values before running, and posts completion to Jira.
---

# SRE Execute

Execute a single ticket's resolution guide end-to-end.

**Usage:** `/sre-execute TICKET-XXXX [--dry-run]`

- `TICKET-XXXX` — Jira ticket key to execute (required), e.g. `INF-1234`
- `--dry-run` — list all steps with tags and commands; run nothing

---

## Step 1 — Parse input

**Before anything else:** Read `sre-config.md` (or `sre-config.example` if missing) to load:
- `JIRA_PROJECT` — ticket key prefix (e.g. `INF`)
- `JIRA_CLOUD_ID`
- `JIRA_BASE_URL`
- `CONFLUENCE_SPACE` (optional — only if Confluence is configured)

Extract from the argument string:
- **Ticket key:** match pattern `{JIRA_PROJECT}-\d+` (case-insensitive)
- **Dry-run flag:** check for `--dry-run`

If no ticket key is found, ask: *"Which ticket should I execute? (e.g. INF-1234)"*

---

## Step 2 — Pre-flight checks

Run all checks before touching any system.

### 2a — Fetch Jira ticket

Call `getJiraIssue` for the ticket. Read: `summary`, `status`, `labels`, `priority`.

Display:
```
🎯 [{TICKET_KEY}] {summary}
Priority: {priority} | Status: {status}
```

If Jira status is already `Done`, warn:
```
⚠️ This ticket is already marked Done. Re-execute? (y/n)
```
Stop unless the SRE confirms.

### 2b — Find the resolution guide

Look for the guide in this priority order:

**1. Jira comment (preferred):** Look for a `📄 Resolution guide:` comment on the Jira ticket (added by a previous `/sre-triage` run).
- If the comment references a local file path (`output/guides/...`) → read that local file.
- If the comment contains a Confluence URL → use Option C below.

**2. Local file (fallback):** Check for a matching guide file:
```bash
ls output/guides/{TICKET_KEY}-*.md 2>/dev/null
```
If found, use the most recently modified file.

**3. Confluence (optional fallback):** Only if `CONFLUENCE_SPACE` is set in `sre-config.md`:
```
title = "[{TICKET_KEY}]" AND space = "{CONFLUENCE_SPACE}" AND type = page
```
Take the first result. Call `getConfluencePage` with `responseContentFormat: "markdown"`.

If no guide found anywhere:
```
❌ No resolution guide found for {TICKET_KEY}.
   Run /sre-triage first to generate one, or provide the guide path.
```
Stop.

### 2c — Read the Execution Script section

If the guide is a **local file**: read the file content directly using the Read tool.
If the guide is a **Confluence page**: call `getConfluencePage`.

Find the `## 🖥️ Execution Script` section. Extract:
- The `**Labels:** ...` line → read `EXECUTABILITY` and `SAFETY` values
- All numbered steps (pattern: `{n}. [{tag}] ...` with optional bash block)

**EXECUTABILITY gate:**

| Value | Action |
|---|---|
| `READY` | Proceed |
| `PARTIAL` | Warn: "Some steps are MANUAL — you will be prompted to fill in TBD values." Proceed. |
| `BLOCKED` | Stop: "⛔ EXECUTABILITY is BLOCKED — resolve missing information before executing. See Jira comments for what is needed." |

If the guide has **no Execution Script section**, warn:
```
⚠️ This guide was created before the Execution Script feature was added.
   Re-run /sre-triage to regenerate it, or paste the steps manually.
```
Stop.

### 2d — Assign ticket to current user

Call `atlassianUserInfo` to get the current user's `accountId`.
Call `editJiraIssue` to set `assignee: { accountId: "{current_user_account_id}" }` on the ticket.

This marks the ticket as in-progress by the SRE who is executing it. If the assignment fails (permissions or already assigned), log a warning and continue — do not abort.

### 2e — Load local repo map

Read `.local-repos` and build `{repo-name → local-path}` map. Used to resolve file paths in step commands (e.g. replace `helm/apps/{app}/values-prod.yaml` with the full local path).

> **Tip:** Some repos may be cloned under different folder names. Check `.local-repos` for the actual local path, and note any renames in the file's comments.

---

## Step 3 — Display the execution plan

Print the full step list before running anything:

```
📋 Execution plan for [{TICKET_KEY}] {summary}
SAFETY: {safety_label} | EXECUTABILITY: {executability_label}
──────────────────────────────────────────────
Step 1  [SAFE]    {description}
Step 2  [CAUTION] {description}
Step 3  [RISKY]   {description}
Step 4  [MANUAL]  {description}
──────────────────────────────────────────────
Total: {n} steps ({n_safe} SAFE · {n_caution} CAUTION · {n_risky} RISKY · {n_manual} MANUAL)
```

If `--dry-run`: print each step's bash block in full, then stop:
```
🔍 Dry run complete — no commands were executed.
```

---

## Step 4 — Collect TBD values

Before executing any command, scan **all** step commands for `{TBD ...}` placeholders.

For each unique placeholder found:
```
📝 Step {n} needs input:
   Placeholder: {TBD — description}
   Enter value (or press Enter to leave as MANUAL):
```

Substitute the provided value everywhere it appears across all steps. If left blank, the step becomes `[MANUAL]`.

---

## Step 5 — Execute steps in order

For each step from 1 to N:

Print a divider:
```
── Step {n}/{total} [{TAG}] ──────────────────────────────
{description}
```

Then handle by tag:

### [SAFE]

Run the bash block immediately using the Bash tool. Show the command and its output.

If the command fails (non-zero exit):
→ go to **Error handler** (Step 5e).

### [CAUTION]

Show the command, then ask:
```
⚠️  CAUTION — review before running.

> {command}

Proceed? [y] run  [s] skip  [a] abort all
```
- `y` → run with Bash tool
- `s` → log "Skipped" and move to next step
- `a` → go to **Abort handler** (Step 5f)

### [RISKY]

Show the command with a full warning:
```
🔴 RISKY step — this may be irreversible or affect production.

> {command}

SAFETY label: {safety_label}
Type "yes" to confirm, anything else to skip:
```
Only on exact input `yes` → run with Bash tool. Anything else → log "Skipped by SRE" and continue.

### [MANUAL]

```
📋 MANUAL step — complete this by hand:

{instructions}

Type "done" when complete, "skip" to skip, or "abort" to abort all:
```
- `done` → log "Completed manually" and continue
- `skip` → log "Skipped" and continue
- `abort` → go to **Abort handler** (Step 5f)

---

### Error handler (Step 5e)

When a command exits with a non-zero code:

```
❌ Step {n} failed.
   Exit code: {code}
   {stderr output}
```

Check if the guide includes a rollback step. If so, offer:
```
↩️  A rollback step is available. Run it now? (y/n)
```

Then ask:
```
How to proceed?  [r] retry  [s] skip this step  [a] abort
```

On `a`: post a failure comment on Jira and stop.

---

### Abort handler (Step 5f)

```
⛔ Execution aborted at step {n}.
   Steps completed: {n_completed}
   Steps remaining: {n_remaining}
```

Post a Jira comment:
```
⛔ Execution aborted at step {n} of {total} — {date}

Completed: steps {list}
Aborted at: step {n} — {description}
Reason: SRE aborted / step failure

— SRE Bot 🤖
```

---

## Step 6 — Post-completion

After all steps complete (or are skipped without aborting):

### 6a — Jira comment

Post with `addCommentToJiraIssue`:
```
✅ Execution completed — {YYYY-MM-DD HH:MM UTC}

Steps run:     {n_run}/{n_total}
Steps skipped: {n_skipped}
Manual steps:  {n_manual}

— SRE Bot 🤖
```

### 6b — Transition ticket to In Review

Call `getTransitionsForJiraIssue` to find the transition named `To review`.
Call `transitionJiraIssue` to apply it.

If the transition is not available (ticket may already be in that state), skip silently.

### 6c — Save completion notification

Save a notification to `output/alerts/{YYYY-MM-DD}-execution-summary.md` (append if the file already exists for today):

```
✅ [{TICKET_KEY}] {summary}
Executed — {YYYY-MM-DD}
Steps: {n_run} run · {n_skipped} skipped · {n_manual} manual
🎫 {JIRA_BASE_URL}/browse/{TICKET_KEY}
```

<!-- ☁️ To notify Slack instead:
1. Set SLACK_TEAM_CHANNEL in sre-config.md.
2. Call slack_send_message with channel_id = {SLACK_TEAM_CHANNEL}.
3. Use the same message format above.
-->

---

## Notes

- **Local repo paths:** When a command references a relative file path (e.g. `helm/apps/{app}/values-prod.yaml`), resolve it against the matching entry in `.local-repos`. If no match, mark as `[MANUAL]` and prompt the SRE.
- **Secret values:** Never log secret values to the terminal. If a command contains a secret placeholder, mark the step `[MANUAL]` and ask the SRE to run it in a separate session.
- **Rollback steps:** The guide's rollback commands (usually the last numbered step) are tagged `[RISKY]`. They are shown in the plan but only run if explicitly triggered (either as a normal step or from the error handler).
- **New secret keys vs. value updates:** When a SECRET ticket adds brand-new keys (not just updating existing values), the ExternalSecret `data` section in `helm/apps/{app}/values-{env}.yaml` must be updated with the new entries and committed to k8s-manifest. ArgoCD auto-sync + ESO will pull the new keys automatically — no kubectl ESO resync or pod restart step is needed.
- **Secret name per env:** Always read the existing `additionalManifests[0].spec.data[0].remoteRef.key` from the values file to get the exact AWS secret name — do not guess from the naming convention. Different environments may use different secret name suffixes.
