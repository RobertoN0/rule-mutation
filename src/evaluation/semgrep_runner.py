"""
Semgrep runner for evaluating security vulnerabilities in generated code.

Extracted from batch_experiment.py for reuse in the SBST hill climbing framework.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field


# Language → file extension mapping for Semgrep temp-file naming
LANG_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "java": ".java",
    "c": ".c",
    "cpp": ".cpp",
    "php": ".php",
    "rust": ".rs",
    "csharp": ".cs",
}

# Default Semgrep ruleset for security analysis
DEFAULT_RULESET = "p/security-audit"

# Severity levels to include in findings
DEFAULT_SEVERITY_FILTER = {"ERROR", "WARNING"}


@dataclass
class SemgrepFinding:
    """A single Semgrep security finding."""
    
    check_id: str
    message: str
    severity: str
    line: int
    
    def __hash__(self) -> int:
        return hash((self.check_id, self.line))


@dataclass
class SemgrepResult:
    """Result of running Semgrep on a code snippet."""
    
    findings: list[SemgrepFinding] = field(default_factory=list)
    error: str | None = None
    
    @property
    def count(self) -> int:
        """Total number of findings."""
        return len(self.findings)
    
    @property
    def error_count(self) -> int:
        """Number of ERROR severity findings."""
        return sum(1 for f in self.findings if f.severity == "ERROR")
    
    @property
    def warning_count(self) -> int:
        """Number of WARNING severity findings."""
        return sum(1 for f in self.findings if f.severity == "WARNING")
    
    @property
    def check_ids(self) -> list[str]:
        """List of check IDs (rule names) that triggered."""
        return [f.check_id for f in self.findings]
    
    @property
    def severities(self) -> list[str]:
        """List of severities for all findings."""
        return [f.severity for f in self.findings]


def strip_markdown_fences(code: str) -> str:
    """Remove markdown code fences (```lang ... ```) from LLM output.
    
    Args:
        code: Raw LLM output that may contain markdown fences.
        
    Returns:
        Clean code string without markdown formatting.
    """
    stripped = re.sub(r"^```[\w]*\n?", "", code.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


def run_semgrep(
    code_content: str,
    language: str = "python",
    rule_config: str = DEFAULT_RULESET,
    severity_filter: set[str] | None = None,
    strip_fences: bool = True,
) -> SemgrepResult:
    """Run Semgrep on a code string and return security findings.
    
    Args:
        code_content: The code to analyze.
        language: Programming language (determines file extension).
        rule_config: Semgrep ruleset to use (e.g., "p/security-audit").
        severity_filter: Set of severity levels to include. Defaults to
            {"ERROR", "WARNING"}.
        strip_fences: If True, strip markdown code fences before analysis.
        
    Returns:
        SemgrepResult containing findings or error information.
    """
    if severity_filter is None:
        severity_filter = DEFAULT_SEVERITY_FILTER
    
    # Clean up the code if needed
    if strip_fences:
        code_content = strip_markdown_fences(code_content)
    
    # Handle empty code
    if not code_content.strip():
        return SemgrepResult(error="Empty code content")
    
    suffix = LANG_EXTENSIONS.get(language, ".py")
    
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code_content)
        tmp_path = tmp.name
    
    try:
        result = subprocess.run(
            ["semgrep", "--config", rule_config, "--json", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,  # 60 second timeout
        )
        
        if result.returncode != 0 or not result.stdout.strip():
            # Semgrep may return non-zero for parse errors but still produce output
            if result.stdout.strip():
                pass  # Continue to parse results
            else:
                return SemgrepResult(error=result.stderr or "Semgrep returned no output")
        
        data = json.loads(result.stdout)
        findings: list[SemgrepFinding] = []
        
        for r in data.get("results", []):
            sev = r["extra"]["severity"].upper()
            if sev not in severity_filter:
                continue
            findings.append(SemgrepFinding(
                check_id=r["check_id"],
                message=r["extra"]["message"],
                severity=sev,
                line=r["start"]["line"],
            ))
        
        return SemgrepResult(findings=findings)
        
    except subprocess.TimeoutExpired:
        return SemgrepResult(error="Semgrep timed out")
    except json.JSONDecodeError as e:
        return SemgrepResult(error=f"Failed to parse Semgrep output: {e}")
    except FileNotFoundError:
        return SemgrepResult(error="Semgrep not installed or not in PATH")
    except Exception as e:
        return SemgrepResult(error=f"Unexpected error: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def run_semgrep_batch(
    code_samples: list[tuple[str, str]],
    rule_config: str = DEFAULT_RULESET,
) -> list[SemgrepResult]:
    """Run Semgrep on multiple code samples.
    
    Args:
        code_samples: List of (code, language) tuples.
        rule_config: Semgrep ruleset to use.
        
    Returns:
        List of SemgrepResult objects, one per input sample.
    """
    return [
        run_semgrep(code, language=lang, rule_config=rule_config)
        for code, lang in code_samples
    ]
