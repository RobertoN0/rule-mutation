# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Auto-syncs to JSONL for version control
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update bd-42 --status in_progress --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task**: `bd update <id> --status in_progress`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Request review**: When you believe work is complete, report to the user (see below)
6. **Complete**: ONLY close the issue when the user explicitly confirms

### Issue Completion Protocol

**CRITICAL: Agents must NEVER close issues autonomously.**

When you believe an issue is solved:

1. **Stop and report** - Do NOT run `bd close`. Instead, provide a detailed summary to the user:
   - What was the original problem/task?
   - What changes were made? (files modified, code added/removed)
   - How does the solution address the issue?
   - What testing or validation was performed?
   - Are there any caveats, limitations, or follow-up items?

2. **Wait for user confirmation** - The user will review your work and explicitly tell you to close the issue.

3. **Only then close** - Run `bd close <id>` ONLY after the user says something like "close it", "looks good, close the issue", or similar explicit confirmation.

**Example workflow:**
```
Agent: "I believe issue bd-42 is complete. Here's what I did:
- Problem: Login form was not validating email format
- Changes: Added regex validation in src/auth/login.py (lines 45-52)
- Testing: Verified with valid/invalid emails, all edge cases pass
- Note: This doesn't affect the registration form (separate issue)

Please review and let me know if I should close this issue."

User: "Looks good, close it."

Agent: *now runs* `bd close bd-42 --reason "Added email validation"`
```

### Auto-Sync

bd automatically syncs with git:

- Exports to `.beads/issues.jsonl` after changes (5s debounce)
- Imports from JSONL when newer (e.g., after `git pull`)
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ✅ **Always explain in detail why you think an issue is solved before closing**
- ✅ **Wait for explicit user confirmation before closing any issue**
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems
- ❌ **NEVER close an issue without user's explicit permission**

For more details, see README.md and EXPERIMENT_GUIDE.md.

<!-- END BEADS INTEGRATION -->

## Project Documentation

For technical details and experiment framework documentation:
- **[README.md](README.md)** - Project overview, architecture, current status
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - How to run experiments, components, configuration
- Use `bd list` to see all tracked tasks and issues

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
