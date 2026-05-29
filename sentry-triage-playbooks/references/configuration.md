# Sentry Triage Configuration

## Environment

Keep secrets out of skill files and cron commands. Put them in a private env file readable only by the scheduler user:

```bash
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=replace-with-org-slug
SENTRY_PROJECTS=backend,ai-service
SENTRY_ENVIRONMENT=production
SENTRY_QUERY=is:unresolved
SENTRY_OUTPUT_DIR=/var/tmp/sentry-playbooks
SENTRY_CRITICAL_PRIORITIES=P0
SENTRY_IGNORE_FILE=/path/to/private/sentry-ignore.json

# optional sender settings
TEAMS_WEBHOOK_URL=https://example.com/teams-webhook
TEAMS_TIMEOUT=15
# optional freshness guard: skip approved alerts whose Last Seen is older than this
TEAMS_MAX_LAST_SEEN_AGE_HOURS=24
```

The script accepts a Sentry API auth token as `SENTRY_AUTH_TOKEN`. Use an internal integration token or user auth token with at least `event:read`, `project:read`, and `org:read`. A custom integration webhook secret/client secret is not enough for `/api/0`; Sentry will reject it as an invalid API key. If only a legacy API key is available, set it as `SENTRY_AUTH_TOKEN`; the script automatically retries with Basic auth if Bearer auth returns unauthorized.

`SENTRY_PROJECTS` accepts project IDs or project slugs, for example `backend,ai-service`.

## Ignore List

Use the ignore list for issues the dev team has explicitly accepted as non-critical noise. Keep a reason on every rule and prefer an expiry for temporary suppressions:

```json
{
  "ignore": [
    {
      "shortId": "BACKEND-123",
      "reason": "Known noisy bot traffic; accepted by backend team",
      "until": "2026-06-30T00:00:00Z"
    },
    {
      "project": "ai-service",
      "class": "frontend-client",
      "titleContains": "ResizeObserver",
      "reason": "Browser-only noise; no user impact observed"
    }
  ]
}
```

Fast one-off suppression can use `SENTRY_IGNORE_IDS=BACKEND-123,987654321`.

## MCP

For self-hosted Sentry, the official Sentry MCP stdio mode supports an access token and `SENTRY_HOST` as the hostname only. Use the same host as `SENTRY_BASE_URL`, but remove the scheme:

```json
{
  "mcpServers": {
    "sentry": {
      "command": "npx",
      "args": ["@sentry/mcp-server@latest"],
      "env": {
        "SENTRY_ACCESS_TOKEN": "${SENTRY_AUTH_TOKEN}",
        "SENTRY_HOST": "sentry.example.com",
        "MCP_DISABLE_SKILLS": "seer"
      }
    }
  }
}
```

Use MCP for interactive enrichment: stack traces, sample events, suspect commits, releases, and owner context. Use `scripts/sentry_issue_playbook.py` for scheduled reporting because it avoids interactive OAuth and produces stable files.

## Manual Runs

Initial classification:

```bash
/path/to/sentry-triage-playbooks/scripts/run_sentry_triage.sh /path/to/private/sentry-triage.env --days 7
```

Post-mitigation reduction check:

```bash
/path/to/sentry-triage-playbooks/scripts/run_sentry_triage.sh /path/to/private/sentry-triage.env --hours 4 --compare-to latest
```

## Teams Sender

The alert sender is intentionally separate from triage. It only sends files in `alerts/approved/`, then moves sent files to `alerts/sent/`.

Dry run (no send, no move):

```bash
/path/to/sentry-triage-playbooks/scripts/run_send_teams_alerts.sh /path/to/private/sentry-triage.env --dry-run
```

Send approved alerts:

```bash
/path/to/sentry-triage-playbooks/scripts/run_send_teams_alerts.sh /path/to/private/sentry-triage.env
```

Optional limit per run:

```bash
/path/to/sentry-triage-playbooks/scripts/run_send_teams_alerts.sh /path/to/private/sentry-triage.env --limit 5
```

## Cron

Run a weekly 7-day classification:

```cron
15 9 * * 1 /path/to/sentry-triage-playbooks/scripts/run_sentry_triage.sh /path/to/private/sentry-triage.env --days 7 >> /var/log/sentry-triage.log 2>&1
```

Run a four-hour reduction report every four hours:

```cron
5 */4 * * * /path/to/sentry-triage-playbooks/scripts/run_sentry_triage.sh /path/to/private/sentry-triage.env --hours 4 --compare-to latest >> /var/log/sentry-triage.log 2>&1
```

Send approved alerts every 5 minutes:

```cron
*/5 * * * * /path/to/sentry-triage-playbooks/scripts/run_send_teams_alerts.sh /path/to/private/sentry-triage.env >> /var/log/sentry-send-alerts.log 2>&1
```

Prefer file permissions like `chmod 600 /path/to/private/sentry-triage.env` for token storage.

To prevent overlapping cron runs, wrap each command with `flock`, for example:

```cron
5 */4 * * * flock -n /tmp/sentry-triage.lock /path/to/sentry-triage-playbooks/scripts/run_sentry_triage.sh /path/to/private/sentry-triage.env --hours 4 --compare-to latest >> /var/log/sentry-triage.log 2>&1
*/5 * * * * flock -n /tmp/sentry-send.lock /path/to/sentry-triage-playbooks/scripts/run_send_teams_alerts.sh /path/to/private/sentry-triage.env >> /var/log/sentry-send-alerts.log 2>&1
```

## Analyze Before Send

The triage script does not send notifications. It creates an approval queue:

```text
$SENTRY_OUTPUT_DIR/
  reports/
  snapshots/
  alerts/
    pending/
    approved/
    sent/
    ignored/
  runbooks/
```

Review `alerts/pending/*.md` first. Each file includes:

- `send_status`: `send`, `review`, or `hold`
- `priority`
- `danger`
- issue summary
- danger assessment
- suggested next steps

The sender script only pushes files moved to `alerts/approved/`, then moves pushed files to `alerts/sent/`. This keeps alert analysis separate from notification delivery.
