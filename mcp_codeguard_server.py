"""
MCP Server for Project CodeGuard Security Rules.

This server exposes CodeGuard security rules to AI agents via the
Model Context Protocol (MCP). It provides two tools:
  1. list_available_guidelines  — lists all rule IDs and descriptions
  2. search_security_guidelines — search over rules by ID

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
        "First call list_available_guidelines to see all available rules, "
        "then use get_guideline_by_id to retrieve specific rules by their ID. "
    ),
)

@mcp.tool()
def list_available_guidelines() -> str:
    """List all available CodeGuard guidelines.

    Returns:
        A bulleted list of rule IDs and their one-line descriptions.
    """
    lines: list[str] = ["Available Guidelines:\n"]
    for rule_id, data in _RULES.items():
        lines.append(f"- {rule_id}: {data['description']}")
    return "\n".join(lines)


@mcp.tool()
def get_guideline_by_id(rule_id: str) -> str:
    """Retrieve a specific CodeGuard guideline by its ID.

    Args:
        rule_id: The rule ID to retrieve (e.g., "codeguard-0-input-validation-injection").

    Returns:
        The full Markdown content of the requested rule, or an error message if not found.
    """
    if rule_id not in _RULES:
        available = ", ".join(sorted(_RULES.keys()))
        return f"Error: Rule ID '{rule_id}' not found.\n\nAvailable rule IDs: {available}"
    
    rule = _RULES[rule_id]
    return f"# Retrieved Rule: {rule_id}\n\n{rule['content']}"


if __name__ == "__main__":
    # Default: stdio transport (launched as a subprocess by the notebook)
    mcp.run(transport="stdio")
