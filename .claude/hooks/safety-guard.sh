#!/usr/bin/env bash
# PreToolUse hook — blocks dangerous SRE commands before Claude runs them.
#
# Exit 2 = block the command (Claude Code shows stderr to the user and stops).
# Exit 0 = allow the command to proceed.
#
# Triggered by: settings.json → hooks.PreToolUse → matcher: Bash

INPUT=$(cat)

# Extract the command string from the JSON input Claude Code sends via stdin.
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # Handle both flat {command:...} and nested {tool_input:{command:...}} formats
    cmd = data.get('command') or data.get('tool_input', {}).get('command', '')
    print(cmd)
except Exception:
    print('')
" 2>/dev/null || echo "")

# Nothing to check
[[ -z "$COMMAND" ]] && exit 0

block() {
  local reason="$1"
  local hint="$2"
  printf "🚫 BLOCKED: %s\n   %s\n" "$reason" "$hint" >&2
  exit 2
}

# ── Kubernetes destructive ops ────────────────────────────────────────────────
if echo "$COMMAND" | grep -qE '\bkubectl (delete|drain|cordon)\b'; then
  block \
    "kubectl delete / drain / cordon is a destructive operation." \
    "Mark this step [MANUAL] in the resolution guide and run it yourself."
fi

# ── Terraform destroy ─────────────────────────────────────────────────────────
if echo "$COMMAND" | grep -qE '\bterraform destroy\b'; then
  block \
    "terraform destroy is not allowed via Claude." \
    "Review the plan first, then run manually after explicit confirmation."
fi

# ── ArgoCD app deletion ───────────────────────────────────────────────────────
if echo "$COMMAND" | grep -qE '\bargocd app (delete|rm)\b'; then
  block \
    "ArgoCD app deletion must be done manually." \
    "Mark this step [MANUAL] in the resolution guide."
fi

# ── SQL DROP / TRUNCATE ───────────────────────────────────────────────────────
# Catches both direct SQL and commands piping SQL into mysql / psql
if echo "$COMMAND" | grep -iqE '\b(DROP\s+(TABLE|DATABASE|SCHEMA|INDEX)|TRUNCATE\s+TABLE)\b'; then
  block \
    "Destructive SQL (DROP / TRUNCATE) detected." \
    "Review the statement carefully and run it manually in a DB client."
fi

# ── S3 delete operations without --dryrun ────────────────────────────────────
if echo "$COMMAND" | grep -qE '\baws s3 rm\b' && ! echo "$COMMAND" | grep -q '\-\-dryrun'; then
  block \
    "aws s3 rm detected without --dryrun." \
    "Re-run with --dryrun first to preview deletions, then confirm manually."
fi

if echo "$COMMAND" | grep -qE '\baws s3 sync\b.*--delete' && ! echo "$COMMAND" | grep -q '\-\-dryrun'; then
  block \
    "aws s3 sync --delete detected without --dryrun." \
    "Re-run with --dryrun to preview, then confirm manually."
fi

# ── git force push / hard reset ──────────────────────────────────────────────
if echo "$COMMAND" | grep -qE '\bgit push.*(--force|-f)\b|\bgit reset --hard\b'; then
  block \
    "Force push and hard reset are not allowed via Claude." \
    "Perform this operation manually after reviewing the repo state."
fi

# ── Fork bomb guard ───────────────────────────────────────────────────────────
if echo "$COMMAND" | grep -qF ':(){ :|:& };:'; then
  block "Fork bomb pattern detected." "This command is never safe."
fi

exit 0
