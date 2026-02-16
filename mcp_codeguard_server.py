"""
MCP Server for Project CodeGuard Security Rules.

This server exposes CodeGuard security rules to AI agents via the
Model Context Protocol (MCP). It provides two tools:
  1. search_security_guidelines — semantic keyword search over rules
  2. list_available_guidelines  — lists all rule IDs and descriptions

Usage (stdio transport — intended to be launched by the notebook):
    python mcp_codeguard_server.py

The server reads rules from:
    project-codeguard/skills/software-security/rules/*.md
"""

import os
import re
import sys
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP

# ── configuration ────────────────────────────────────────────────────────────
RULES_DIR = Path(__file__).parent / "project-codeguard" / "skills" / "software-security" / "rules"

# ── load rules once at import time ───────────────────────────────────────────
_RULES: dict[str, dict] = {}


def _load_rules() -> dict[str, dict]:
    """Read every .md rule file and return {rule_id: {filename, description, content}}."""
    library: dict[str, dict] = {}
    for rule_file in sorted(RULES_DIR.glob("*.md")):
        content = rule_file.read_text(encoding="utf-8")
        rule_id = rule_file.stem  # e.g. "codeguard-0-input-validation-injection"
        description = ""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1])
                    description = meta.get("description", "")
                except Exception:
                    pass
        library[rule_id] = {
            "filename": rule_file.name,
            "description": description,
            "content": content,
        }
    return library


_RULES = _load_rules()

# ── MCP server ───────────────────────────────────────────────────────────────
mcp = FastMCP(
    "codeguard-rules",
    instructions=(
        "Provides Project CodeGuard security rules. "
        "Use search_security_guidelines to find the rule that matches "
        "a security concern, and list_available_guidelines to browse all rules."
    ),
)


@mcp.tool()
def search_security_guidelines(query: str) -> str:
    """Search the CodeGuard security-rule library for a relevant rule.

    The search uses simple keyword matching against rule descriptions
    and content.  Returns the full text of the best-matching rule.

    Args:
        query: Natural-language description of the security concern
               (e.g. "SQL injection prevention", "password hashing").

    Returns:
        The full Markdown content of the best-matching rule, prefixed
        with its rule ID.
    """
    query_lower = query.lower()
    query_tokens = set(re.findall(r"\w+", query_lower))

    best_id: str | None = None
    best_score = -1

    for rule_id, data in _RULES.items():
        # Build a corpus from description + first 2 000 chars of content
        corpus = (data["description"] + " " + data["content"][:2000]).lower()
        corpus_tokens = set(re.findall(r"\w+", corpus))
        score = len(query_tokens & corpus_tokens)
        if score > best_score:
            best_score = score
            best_id = rule_id

    if best_id is None:
        return "No security guidelines found."

    rule = _RULES[best_id]
    return f"# Retrieved Rule: {best_id}\n\n{rule['content']}"


@mcp.tool()
def list_available_guidelines() -> str:
    """List all available CodeGuard security guidelines.

    Returns:
        A bulleted list of rule IDs and their one-line descriptions.
    """
    lines: list[str] = ["Available Security Guidelines:\n"]
    for rule_id, data in _RULES.items():
        lines.append(f"- {rule_id}: {data['description']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Default: stdio transport (launched as a subprocess by the notebook)
    mcp.run(transport="stdio")
