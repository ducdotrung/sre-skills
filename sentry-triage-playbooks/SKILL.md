---
name: sentry-triage-playbooks
description: Classify recent Sentry issues and write concise remediation playbooks using a configured Sentry API or MCP connection. Use when asked to triage Sentry errors, review the last week or last few hours of issues, produce incident/debugging playbooks, compare issue volume after a mitigation, or prepare cron-scheduled Sentry issue reports without embedding credentials in files.
---

# Sentry Triage Playbooks

## Overview

Use this skill to pull recent issues from Sentry, classify them by operational failure mode, and generate Markdown playbooks for on-call or engineering follow-up. Keep Sentry credentials and host settings in environment variables so the same skill can be reused across Sentry organizations, projects, and deployments.

The scheduled path is analyze-before-send: collect Sentry issues, classify severity, write an agent-reviewed alert queue, and only push approved alert files later.

## Required Configuration

Set these environment variables before running bundled scripts or configuring MCP:

- `SENTRY_BASE_URL`: full Sentry URL, for example `https://sentry.example.com`
- `SENTRY_AUTH_TOKEN`: Sentry API auth token from an internal integration or user token; do not use a custom integration webhook secret/client secret
- `SENTRY_ORG`: organization slug; if omitted, scripts try to discover it

Optional filters:

- `SENTRY_PROJECTS`: comma-separated project IDs, or `-1` for all visible projects
- `SENTRY_ENVIRONMENT`: environment filter such as `production`
- `SENTRY_QUERY`: Sentry issue search query; default is `is:unresolved`
- `SENTRY_OUTPUT_DIR`: report directory; default is `./sentry-playbooks`
- `SENTRY_LIMIT`: maximum issues to fetch; default is `100`
- `SENTRY_IGNORE_FILE`: JSON file of issue ignore rules for accepted noise
- `SENTRY_IGNORE_IDS`: comma-separated issue IDs or short IDs to ignore
- `SENTRY_CRITICAL_PRIORITIES`: comma-separated priorities treated as critical; default is `P0`

For MCP setup details and cron examples, read `references/configuration.md`.

## Workflow

1. Start with a 7-day lookback to classify the current failure landscape:

   ```bash
   python3 sentry-triage-playbooks/scripts/sentry_issue_playbook.py --days 7
   ```

2. Review the generated Markdown and JSON snapshot. Use the Markdown for a human playbook; use the JSON to preserve raw issue fields for later comparison.

3. Send or page only the `Critical Issues` section first. Treat the full issue table as backlog/noise context.

4. Review the generated `alerts/pending/*.md` files. Each file includes what the alert is, danger assessment, suggested next steps, and a `send_status` front matter value.

5. Move only approved pending files into `alerts/approved/`. Use `scripts/run_send_teams_alerts.sh` to push only approved files, then move them to `alerts/sent/`.

6. Add accepted low-value alerts to the ignore file with a reason and optional expiry. Keep ignored issues visible in the `Ignored Issues` section so the team can audit what is being suppressed.

7. After mitigations or deployments, reduce the window to a few hours:

   ```bash
   python3 sentry-triage-playbooks/scripts/sentry_issue_playbook.py --hours 4 --compare-to latest
   ```

4. When an MCP Sentry server is available, use it to enrich high-priority issues with stack traces, event samples, suspect commits, and release context. Keep the script output as the reproducible baseline because it is deterministic and cron-friendly.

## Classification Rules

Classify every issue using observable issue fields first: title, metadata type/value, culprit, level, platform, project, count, user count, first seen, last seen, and permalink.

Use these classes:

- `availability`: service unavailable, fatal errors, 5xx, gateway errors, crashes, workers failing, outage symptoms
- `dependency`: upstream API, network, DNS, database, Redis, queue, storage, or third-party provider failures
- `auth-permission`: 401, 403, forbidden, unauthorized, token, signature, CSRF, role, or permission failures
- `data-integrity`: schema, migration, missing field, null constraint, serialization, parsing, corrupt data, invariant failures
- `input-validation`: bad request, validation, malformed payload, user input, type mismatch at boundary
- `client-disconnect`: broken pipe, client abort, premature close; usually not page-worthy without correlated backend latency or broad user impact
- `frontend-client`: browser, JavaScript, hydration, chunk loading, source map, extension noise, client-only rendering failures
- `performance-timeout`: timeout, slow query, deadline, lock wait, memory pressure, rate limit, overloaded queues
- `unknown`: insufficient signal; request more event detail through MCP or the Sentry UI

Prioritize:

- `P0`: broad outage or critical path unavailable
- `P1`: high-volume, recent, or user-visible production issue
- `P2`: moderate production issue with clear owner or workaround
- `P3`: low-volume, stale, noisy, or non-production issue

## Playbook Format

Write playbooks with these sections:

- `Situation`: issue count, affected projects, time window, dominant classes
- `Analyze Before Send`: how to review pending alert files before notification
- `Immediate Triage`: checks to confirm impact and current trend
- `Likely Causes`: class-specific hypotheses grounded in the issue evidence
- `Mitigation`: reversible short-term steps before code changes
- `Debugging Path`: logs, traces, releases, commits, owners, and reproduction steps to inspect
- `Follow-up Window`: a smaller `--hours` rerun to confirm issue reduction
- `Issue Table`: priority, class, project, issue, counts, last seen, link
- `Ignored Issues`: accepted noise, reason, and expiry when configured

Do not mark or mutate Sentry issues from scheduled runs unless the user explicitly asks for write behavior. Treat cron output as read-only reporting.

## Output Layout

Use `SENTRY_OUTPUT_DIR` as the root. The script creates these folders:

- `reports/`: full Markdown playbooks
- `snapshots/`: raw JSON snapshots for comparison and audit
- `alerts/pending/`: per-critical-issue analysis files waiting for review
- `alerts/approved/`: files approved for sender delivery
- `alerts/sent/`: files already pushed
- `alerts/ignored/`: files intentionally suppressed
- `runbooks/`: durable team runbooks and summaries
