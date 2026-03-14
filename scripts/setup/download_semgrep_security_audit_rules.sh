#!/bin/bash

set -euo pipefail

TARGET_DIR="${1:-/scratch/$USER/semgrep-rules/security-audit}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/semgrep-rules.XXXXXX")"
REPO_DIR="$WORK_DIR/semgrep-rules"

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "=== Downloading Semgrep security-audit rules ==="
echo "Target directory: $TARGET_DIR"
echo

git clone --depth 1 https://github.com/semgrep/semgrep-rules "$REPO_DIR"

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"

while IFS= read -r rule_file; do
    rel_path="${rule_file#$REPO_DIR/}"
    dest_path="$TARGET_DIR/$rel_path"
    mkdir -p "$(dirname "$dest_path")"
    cp "$rule_file" "$dest_path"
done < <(find "$REPO_DIR" -path '*/security/audit/*' \( -name '*.yml' -o -name '*.yaml' \) | sort)

find "$TARGET_DIR" \( -name '*.yml' -o -name '*.yaml' \) | sort > "$TARGET_DIR/manifest.txt"

RULE_COUNT="$(wc -l < "$TARGET_DIR/manifest.txt")"

echo
echo "✅ Download complete"
echo "   Rules copied: $RULE_COUNT"
echo "   Manifest: $TARGET_DIR/manifest.txt"
echo
echo "Use this in jobs with:"
echo "   export SEMGREP_RULESET=$TARGET_DIR"
echo
echo "Quick smoke test:"
echo "   semgrep scan --config \"$TARGET_DIR\" --json --disable-version-check --metrics off test.py"
