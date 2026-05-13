#!/usr/bin/env bash
# Pack skill files for upload to claude.ai co-work project.
#
# Output: sre-skill-YYYYMMDD.zip
# Structure inside zip: all files under a single top-level sre-skill/ folder.
#
# Excluded: personal notes (command-for-sre/), local reference files (sg.tf),
#           this script, README.md, and macOS junk files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTFILE="$SCRIPT_DIR/sre-skill-$(date +%Y%m%d).zip"
TMPDIR="$(mktemp -d)"
STAGEDIR="$TMPDIR/sre-skill"

cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT

mkdir -p "$STAGEDIR"

# Copy everything that should go into the zip
cp "$SCRIPT_DIR/SKILL.md"  "$STAGEDIR/"
cp "$SCRIPT_DIR/CLAUDE.md" "$STAGEDIR/"
cp -r "$SCRIPT_DIR/.claude"    "$STAGEDIR/"
cp -r "$SCRIPT_DIR/sre-triage" "$STAGEDIR/"

# Remove any macOS junk that snuck in
find "$STAGEDIR" -name ".DS_Store" -delete
find "$STAGEDIR" -name "__MACOSX" -type d -exec rm -rf {} + 2>/dev/null || true

# Build zip from inside TMPDIR so the top-level entry is sre-skill/
rm -f "$OUTFILE"
cd "$TMPDIR"
zip -r "$OUTFILE" sre-skill/

echo ""
echo "Created: $OUTFILE"
echo ""
echo "Contents:"
zip -sf "$OUTFILE"
