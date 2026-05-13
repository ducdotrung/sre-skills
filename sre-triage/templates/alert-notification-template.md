# Notification Templates — SRE Triage

Used by Step 7 of the triage publishing flow. Output is saved to `output/alerts/`.

Use **exactly one** of the three templates below based on the ticket outcome.
Do NOT mix or combine templates. Replace every `{placeholder}` before writing.

Read `sre-config.md` to get `JIRA_PROJECT` and `JIRA_BASE_URL` for ticket links.

---

## Template A — Guide ready ✅

Use when: ticket is fully classified AND a resolution guide was created (or already existed) with complete information.

```
🎯 [{TICKET_KEY}] {ticket title}
Type: `{type}` | Env: `{env}` | Priority: {priority}
Labels: `EXECUTABILITY: {executability_label}` | `SAFETY: {safety_label}`
Status: Guide ready ✅

> {1-line summary of what needs to be done}

📄 Guide: output/guides/{guide_filename}.md
🎫 Jira: {JIRA_BASE_URL}/browse/{TICKET_KEY}
```

---

## Template B — Needs more info ❓

Use when: ticket is classified but one or more required fields are missing. A comment must have been posted on Jira before writing this.

```
🎯 [{TICKET_KEY}] {ticket title}
Type: `{type}` | Env: `{env}` | Priority: {priority}
Labels: `EXECUTABILITY: {executability_label}` | `SAFETY: {safety_label}`
Status: Needs more info ❓

> {1-line summary of what is missing}

💬 Comment posted on Jira requesting missing info.
📄 Guide: output/guides/{guide_filename}.md _(partial — TBD fields marked)_
🎫 Jira: {JIRA_BASE_URL}/browse/{TICKET_KEY}
```

> Note: If there is zero actionable info (cannot even create a partial guide), omit the Guide line entirely.

---

## Template C — Needs triage ⚠️

Use when: ticket type is `UNKNOWN` and cannot be classified without more context. Do NOT create a guide for these.

```
🎯 [{TICKET_KEY}] {ticket title}
Type: `UNKNOWN` | Priority: {priority}
Labels: `EXECUTABILITY: BLOCKED` | `SAFETY: {TBD}`
Status: Needs triage ⚠️

> {1-line description of what was understood so far}

❓ {clarifying question 1}
❓ {clarifying question 2}
❓ {clarifying question 3 — optional}

🎫 Jira: {JIRA_BASE_URL}/browse/{TICKET_KEY}
```

---

## Placeholder reference

| Placeholder | Where to get it |
|---|---|
| `{TICKET_KEY}` | Jira ticket key, e.g. `INF-4815` |
| `{ticket title}` | Jira summary field, verbatim |
| `{type}` | Classification from Step 2, e.g. `DEPLOY`, `SECRET` |
| `{env}` | Target environment from ticket: `prod`, `staging`, `uat`, `dev`, or `N/A` |
| `{priority}` | Jira priority field, e.g. `High`, `Medium`, `Low` |
| `{guide_filename}` | File name of the saved guide in `output/guides/` |
| `{JIRA_BASE_URL}` | From sre-config.md, e.g. `https://your-org.atlassian.net` |
| `{executability_label}` | Computed in Step 3: `READY`, `PARTIAL`, or `BLOCKED` |
| `{safety_label}` | Computed in Steps 2–3: `SAFE`, `CAUTION`, or `RISKY` (base + env modifier) |

<!-- ☁️ To send via Slack instead of saving to a file:
1. Set SLACK_TEAM_CHANNEL in sre-config.md.
2. Replace the Guide line with a Confluence URL if publishing there.
3. Call slack_send_message with channel_id = {SLACK_TEAM_CHANNEL} and the rendered template.
-->
