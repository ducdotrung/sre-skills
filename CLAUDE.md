# SRE Assistant

Read `sre-config.md` at the start of every skill run to load the team's infrastructure constants. If `sre-config.md` does not exist, read `sre-config.example` and warn the user to create their own `sre-config.md` before proceeding.

Use `sre-triage/docs/infra-overview.md` and the other READMEs in `sre-triage/docs/` as your source of truth for infrastructure details.

## Output Directories

By default all skill output is saved locally. Cloud integrations are optional — configure them in `sre-config.md`.

| Output | Default (local) | Cloud alternative |
|---|---|---|
| Resolution guides | `output/guides/` | Confluence (`createConfluencePage`) |
| Triage dashboard | `output/dashboard/` | Confluence (`updateConfluencePage`) |
| Notifications / alerts | `output/alerts/` | Slack (`slack_send_message`) |

## General Rules

- **Read `sre-config.md` first** — never hardcode infrastructure constants.
- **Never guess resource names** — use the naming patterns from `sre-config.md`.
- **Secret pending** (`<sent via email>` or `<SRE-To be updated>`) = block deploy until received.
- **Prod changes** always include a rollback step.
- **Destructive actions** (prod deploy, migration, deletion) get ⚠️ + explicit confirmation note.
- **Language:** Always English.
- **Partial info is OK** — generate what you can; mark unknowns as `{TBD — awaiting requester input}`.

## Available Skills

- `/sre-triage` — fetch, classify, and process open Jira tickets end-to-end.
- `/sre-execute TICKET-XXXX [--dry-run]` — execute a single ticket's resolution guide step-by-step (SAFE/CAUTION/RISKY/MANUAL), collect TBD values, post completion to Jira.
- `/sre-incident APP ENV SYMPTOM` — interactive incident debug: runs live kubectl/aws commands, analyses output, and suggests fixes.

## Sub-Agents

| Agent | Trigger |
|---|---|
| `sql-reviewer` | DEPLOY ticket with SQL — spawned automatically by the triage playbook; keeps SQL analysis in a clean context |
