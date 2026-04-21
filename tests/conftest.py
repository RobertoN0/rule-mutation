"""Shared fixtures for the SBST pipeline test suite."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `src.*` imports work.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---------------------------------------------------------------------------
# Realistic CodeGuard-style rule text used across Topics B, C, and D tests.
# ~400 words, frontmatter + ## sections + bullets + inline `code` + security
# keywords (validate, sanitize, escape, injection, MUST, NEVER, Ensure).
# ---------------------------------------------------------------------------

SAMPLE_RULE_TEXT = """\
---
description: Input validation and injection defense
languages:
- python
- java
- javascript
tags:
- web
alwaysApply: false
---

## Input Validation & Injection Defense

Ensure untrusted input is validated and never interpreted as code. Prevent injection across SQL, LDAP, OS commands, and JavaScript runtime object graphs.

### Core Strategy
- Validate early at trust boundaries with positive (allow-list) validation.
- Treat all untrusted input as data, NEVER as code.
- MUST use safe APIs that separate code from data.
- Parameterize queries; escape only as last resort.

### SQL Injection Prevention
- Use `PreparedStatement` and parameterized queries for 100% of data access.
- NEVER concatenate user input into SQL strings.
- Use bind variables for any dynamic SQL construction.
- Ensure least-privilege DB users; Block admin grants to app accounts.

### XSS Defense
- Sanitize all output rendered in HTML context using `DOMPurify` or equivalent.
- Validate input on the server side; Reject requests containing `<script>` tags.
- Prevent DOM-based XSS by avoiding `innerHTML` assignments with untrusted data.

### OS Command Injection
- MUST use parameterized APIs (e.g., `subprocess.run` with list args) instead of shell=True.
- Validate command arguments against an allow-list of safe values.
- NEVER pass unsanitized user input to `os.system()` or `eval()`.
"""


@pytest.fixture
def sample_rule_text() -> str:
    """A realistic CodeGuard rule text for mutator testing."""
    return SAMPLE_RULE_TEXT
