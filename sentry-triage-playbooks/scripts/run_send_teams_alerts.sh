#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s ENV_FILE [send_teams_alerts.py args...]\n' "$0" >&2
  printf '   or: SENTRY_TRIAGE_ENV=ENV_FILE %s [send_teams_alerts.py args...]\n' "$0" >&2
}

env_file="${SENTRY_TRIAGE_ENV:-}"
if [[ $# -gt 0 && -f "$1" ]]; then
  env_file="$1"
  shift
fi

if [[ -z "$env_file" || ! -f "$env_file" ]]; then
  usage
  exit 2
fi

set -a
# shellcheck source=/dev/null
. "$env_file"
set +a

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$script_dir/send_teams_alerts.py" "$@"
