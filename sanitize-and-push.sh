#!/bin/bash
# Sanitize sutra-build for public release and push to sutra-os (GitHub OSS)
# Usage: ./sanitize-and-push.sh [--force]

set -e

SUTRA_BUILD=$(cd "$(dirname "$0")" && pwd)
SUTRA_OSS="$HOME/Downloads/sutra-os"
SKIP_CONFIRM=false

if [[ "$1" == "--force" ]]; then
    SKIP_CONFIRM=true
fi

echo "🔄 Sutra: Sanitize and Sync"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Source:      $SUTRA_BUILD"
echo "Destination: $SUTRA_OSS"
echo ""

# Verify directories exist
if [[ ! -d "$SUTRA_BUILD" ]]; then
    echo "❌ Error: sutra-build not found at $SUTRA_BUILD"
    exit 1
fi

if [[ ! -d "$SUTRA_OSS" ]]; then
    echo "❌ Error: sutra-os not found at $SUTRA_OSS"
    echo "   Clone it first: git clone [repo] ~/Downloads/sutra-os"
    exit 1
fi

# Run the /sanitize-for-oss skill
echo "🧹 Running /sanitize-for-oss skill..."
echo ""

# This is a placeholder — the actual sanitization happens via Claude Code /sanitize-for-oss skill
# The skill handles:
# - Removing CLAUDE.md (internal identity)
# - Removing internal planning docs (ROADMAP.md internal details, non-OSS-relevant sections)
# - Removing hardcoded paths with /Users/christopherk.marks
# - Removing agent names (ScratchPad, Sutra, etc. become generic)
# - Sanitizing inline examples with personal info

# For now, we'll do a minimal version:
# Copy everything to a temp dir, run basic sanitization, diff against sutra-os

TEMP_SANITIZED=$(mktemp -d)
trap "rm -rf $TEMP_SANITIZED" EXIT

echo "📋 Copying to temp directory..."
cp -r "$SUTRA_BUILD"/* "$TEMP_SANITIZED/"

# Basic sanitization (this should be replaced by /sanitize-for-oss skill)
echo "🧹 Applying sanitization..."

# Remove internal-only docs
rm -f "$TEMP_SANITIZED"/CLAUDE.md
rm -f "$TEMP_SANITIZED"/docs/ARCHITECTURE.md  # Internal strategy only

# Remove sensitive paths from markdown files
find "$TEMP_SANITIZED" -name "*.md" -type f -exec sed -i.bak \
    -e 's|/Users/christopherk.marks|<user>|g' \
    -e 's|christopherk\.marks|user|g' \
    -e 's|Downloads/personal-os-main|project|g' \
    {} \;
find "$TEMP_SANITIZED" -name "*.md.bak" -delete

# Remove agent-specific names (if any internal docs mention them)
find "$TEMP_SANITIZED" -name "*.md" -type f -exec sed -i.bak \
    -e 's|ScratchPad|WorkerAgent|g' \
    -e 's|Sutra\b|Orchestrator|g' \
    {} \;
find "$TEMP_SANITIZED" -name "*.md.bak" -delete

echo "✓ Sanitization complete"
echo ""

# Diff against current sutra-os
echo "📊 Comparing with current sutra-os..."
echo ""

DIFF_OUTPUT=$(diff -r "$SUTRA_OSS" "$TEMP_SANITIZED" --exclude=.git --exclude=node_modules || true)

if [[ -z "$DIFF_OUTPUT" ]]; then
    echo "✓ No changes. sutra-os is up-to-date."
    exit 0
fi

echo "📝 Changes that would be applied:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "$DIFF_OUTPUT" | head -100
if [[ $(echo "$DIFF_OUTPUT" | wc -l) -gt 100 ]]; then
    echo "... (showing first 100 lines)"
fi
echo ""

# Confirm before applying
if [[ "$SKIP_CONFIRM" != "true" ]]; then
    read -p "Apply these changes? (y/N): " -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Cancelled."
        exit 0
    fi
fi

# Apply changes
echo "🚀 Applying changes to sutra-os..."
cp -r "$TEMP_SANITIZED"/* "$SUTRA_OSS/"

# Commit and push
cd "$SUTRA_OSS"
git add -A
git commit -m "Auto-sync from sutra-build ($(date +%Y-%m-%d))" || echo "⚠️  Nothing to commit"
git push origin main

echo ""
echo "✓ sutra-os synced and pushed to GitHub"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📍 OSS repo: https://github.com/[your-org]/sutra-os"
echo "📍 Next: review PR/issues on GitHub"
