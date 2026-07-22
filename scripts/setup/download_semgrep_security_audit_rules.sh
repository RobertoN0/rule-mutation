#!/bin/bash

set -euo pipefail

TARGET_DIR="${1:-/scratch/$USER/semgrep-rules/security-audit}"
RULES_REF="${2:-${SEMGREP_RULES_REF:-}}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/semgrep-rules.XXXXXX")"
REPO_DIR="$WORK_DIR/semgrep-rules"

if [ -z "$RULES_REF" ]; then
    echo "ERROR: supply an immutable semgrep-rules commit as argument 2 or SEMGREP_RULES_REF" >&2
    exit 2
fi

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "=== Downloading Semgrep security-audit rules ==="
echo "Target directory: $TARGET_DIR"
echo "Source ref: $RULES_REF"
echo

git init -q "$REPO_DIR"
git -C "$REPO_DIR" remote add origin https://github.com/semgrep/semgrep-rules
git -C "$REPO_DIR" fetch -q --depth 1 origin "$RULES_REF"
git -C "$REPO_DIR" checkout -q --detach FETCH_HEAD
SOURCE_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD)"

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"

while IFS= read -r rule_file; do
    rel_path="${rule_file#$REPO_DIR/}"
    dest_path="$TARGET_DIR/$rel_path"
    mkdir -p "$(dirname "$dest_path")"
    cp "$rule_file" "$dest_path"
done < <(find "$REPO_DIR" -path '*/security/*' \( -name '*.yml' -o -name '*.yaml' \) | sort)

find "$TARGET_DIR" \( -name '*.yml' -o -name '*.yaml' \) -printf '%P\n' | sort > "$TARGET_DIR/manifest.txt"
printf '%s\n' "$SOURCE_COMMIT" > "$TARGET_DIR/SOURCE_COMMIT"

RULE_COUNT="$(wc -l < "$TARGET_DIR/manifest.txt")"

echo
echo "✅ Download complete"
echo "   Rules copied: $RULE_COUNT"
echo "   Source commit: $SOURCE_COMMIT"
echo "   Manifest: $TARGET_DIR/manifest.txt"
echo
echo "Use this in jobs with:"
echo "   export SEMGREP_RULESET=$TARGET_DIR"
echo
echo "Quick smoke test:"
echo "   semgrep scan --config \"$TARGET_DIR\" --json --disable-version-check --metrics off test.py"
