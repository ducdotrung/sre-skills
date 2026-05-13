#!/usr/bin/env bash
# PostToolUse hook — scans files written by Claude for accidentally committed secrets.
#
# Non-blocking (always exits 0), but prints a warning to stderr so Claude
# sees it and can self-correct or alert the user.
#
# Triggered by: settings.json → hooks.PostToolUse → matcher: Write|Edit

INPUT=$(cat)

# Extract the file path from the JSON input
FILE=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # tool_input may be at top level or nested
    ti = data.get('tool_input', data)
    path = ti.get('file_path') or ti.get('path', '')
    print(path)
except Exception:
    print('')
" 2>/dev/null || echo "")

# Nothing to scan
[[ -z "$FILE" ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

# Skip large files (> 500 KB) and binaries
[[ $(wc -c < "$FILE") -gt 512000 ]] && exit 0
file "$FILE" 2>/dev/null | grep -qE 'binary|ELF|executable' && exit 0

# Skip test fixtures and example files (expected to contain placeholder-looking strings)
case "$FILE" in
  *sre-config.example*|*.example*|*test*|*spec*|*fixture*) exit 0 ;;
esac

warn() {
  printf "⚠️  SECRET SCAN: %s\n   File: %s\n   Review before committing.\n" "$1" "$FILE" >&2
}

FOUND=0

check() {
  local label="$1"
  local pattern="$2"
  if grep -qE "$pattern" "$FILE" 2>/dev/null; then
    warn "$label"
    FOUND=1
  fi
}

# ── AWS ───────────────────────────────────────────────────────────────────────
check "AWS Access Key ID"         'AKIA[0-9A-Z]{16}'
check "AWS Secret Access Key"     '[Aa]ws.{0,20}[0-9a-zA-Z/+]{40}'
check "AWS Account ID (numeric)"  '\b[0-9]{12}\b'

# ── Anthropic / OpenAI ────────────────────────────────────────────────────────
check "Anthropic API key"  'sk-ant-[a-zA-Z0-9\-_]{32,}'
check "OpenAI API key"     'sk-[a-zA-Z0-9]{48}'

# ── GitHub ────────────────────────────────────────────────────────────────────
check "GitHub PAT (classic)"  'ghp_[a-zA-Z0-9]{36}'
check "GitHub PAT (fine-grained)" 'github_pat_[a-zA-Z0-9_]{82}'
check "GitHub App token"      'ghs_[a-zA-Z0-9]{36}'

# ── Slack ─────────────────────────────────────────────────────────────────────
check "Slack bot/user token"  'xox[bprs]-[0-9a-zA-Z\-]+'
check "Slack channel ID (real)" '\bC0[A-Z0-9]{8}\b'

# ── Atlassian ─────────────────────────────────────────────────────────────────
check "Jira cloud ID (UUID)" '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

# ── Stripe ───────────────────────────────────────────────────────────────────
check "Stripe secret key"  'sk_live_[a-zA-Z0-9]{24,}'

# ── Private keys ──────────────────────────────────────────────────────────────
check "Private key PEM block"  '\-\-\-\-\-BEGIN (RSA|EC|OPENSSH) PRIVATE KEY'

# ── JWT ───────────────────────────────────────────────────────────────────────
check "JWT token"  'eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'

# ── Internal IPs ─────────────────────────────────────────────────────────────
# Flag real private IPs that are not placeholders — warn if committed to non-config files
if ! echo "$FILE" | grep -qE '\.(example|sample|template)$'; then
  if grep -qE '\b(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3})\b' "$FILE" 2>/dev/null; then
    if ! grep -qE '\{[A-Z_]+\}|your-|fill in|placeholder|example' "$FILE" 2>/dev/null; then
      warn "Private IP address (may be infrastructure-specific)"
      FOUND=1
    fi
  fi
fi

if [[ $FOUND -eq 1 ]]; then
  printf "   Tip: sensitive values belong in sre-config.md (gitignored), not committed files.\n" >&2
fi

# Always exit 0 — non-blocking warning only
exit 0
