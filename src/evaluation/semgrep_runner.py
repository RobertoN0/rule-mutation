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
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


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
REMOTE_DEFAULT_RULESET = "p/security-audit"
DEFAULT_RULESET = REMOTE_DEFAULT_RULESET

# Global Semgrep execution settings. These can be overridden either through
# environment variables or at runtime via configure_semgrep().
_semgrep_rule_config = os.environ.get("SEMGREP_RULESET", REMOTE_DEFAULT_RULESET)
_semgrep_subprocess_timeout_seconds = int(
    os.environ.get("SEMGREP_TIMEOUT_SECONDS", "180")
)
_semgrep_jobs = int(os.environ.get("SEMGREP_JOBS", "1"))

# Severity levels to include in findings
DEFAULT_SEVERITY_FILTER = {"ERROR", "WARNING"}

# ---------------------------------------------------------------------------
# Debug logging (optional – call configure_semgrep_debug() to enable)
# ---------------------------------------------------------------------------
_debug_dir: Path | None = None
_debug_counter: int = 0
_debug_lock = threading.Lock()


def configure_semgrep(
    rule_config: str | None = None,
    subprocess_timeout_seconds: int | None = None,
    jobs: int | None = None,
) -> None:
    """Configure global Semgrep execution defaults."""
    global _semgrep_rule_config, _semgrep_subprocess_timeout_seconds, _semgrep_jobs

    if rule_config is not None:
        if rule_config.startswith(("~", ".", "/")):
            _semgrep_rule_config = str(Path(rule_config).expanduser())
        else:
            _semgrep_rule_config = rule_config
    if subprocess_timeout_seconds is not None:
        _semgrep_subprocess_timeout_seconds = int(subprocess_timeout_seconds)
    if jobs is not None:
        _semgrep_jobs = int(jobs)


def get_semgrep_config() -> dict[str, int | str]:
    """Return the currently active Semgrep configuration."""
    return {
        "rule_config": _semgrep_rule_config,
        "subprocess_timeout_seconds": _semgrep_subprocess_timeout_seconds,
        "jobs": _semgrep_jobs,
    }


def _resolve_rule_config(rule_config: str | None) -> str:
    """Resolve a Semgrep config value, expanding local paths when appropriate."""
    config = rule_config if rule_config is not None else _semgrep_rule_config
    candidate = Path(config).expanduser()
    if candidate.exists():
        return str(candidate.resolve())
    if config.startswith(("~", ".", "/")):
        return str(candidate.resolve())
    return config


def configure_semgrep_debug(debug_dir: "Path | str | None") -> None:
    """Enable saving Semgrep inputs/outputs to a JSONL debug log.

    Call this once before running your experiment.  Every subsequent call to
    :func:`run_semgrep` will append a JSON record to
    ``<debug_dir>/semgrep_debug.jsonl`` containing:

    * the raw LLM output and the code actually fed to Semgrep (after fence
      stripping),
    * the Semgrep return code, stdout, and stderr,
    * the parsed findings.

    Args:
        debug_dir: Directory to write the debug file into, or ``None`` to
            disable debug logging.
    """
    global _debug_dir, _debug_counter
    if debug_dir is None:
        _debug_dir = None
    else:
        _debug_dir = Path(debug_dir)
        _debug_dir.mkdir(parents=True, exist_ok=True)
        _debug_counter = 0


def _write_semgrep_debug(
    code_original: str,
    code_analyzed: str,
    language: str,
    rule_config: str,
    fences_stripped: bool,
    proc_result: "subprocess.CompletedProcess | None",
    sem_result: "SemgrepResult",
    semgrep_command: list[str] | None = None,
) -> None:
    """Append one debug record to ``semgrep_debug.jsonl`` (no-op if not configured)."""
    global _debug_counter
    if _debug_dir is None:
        return
    try:
        with _debug_lock:
            _debug_counter += 1
            call_id = _debug_counter

        entry = {
            "call_id": call_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "language": language,
            "rule_config": rule_config,
            "semgrep_command": semgrep_command,
            "fences_stripped": fences_stripped,
            "code_raw": code_original,
            "code_analyzed": code_analyzed,
            "semgrep_returncode": proc_result.returncode if proc_result is not None else None,
            "semgrep_stdout": proc_result.stdout if proc_result is not None else None,
            "semgrep_stderr": proc_result.stderr if proc_result is not None else None,
            "findings_count": sem_result.count,
            "error": sem_result.error,
            "findings": [
                {
                    "check_id": f.check_id,
                    "severity": f.severity,
                    "line": f.line,
                    "message": f.message,
                }
                for f in sem_result.findings
            ],
        }

        debug_file = _debug_dir / "semgrep_debug.jsonl"
        with _debug_lock:
            with open(debug_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never let debug logging crash the main analysis flow


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
    rule_config: str | None = None,
    severity_filter: set[str] | None = None,
    strip_fences: bool = True,
    write_debug: bool = True,
) -> SemgrepResult:
    """Run Semgrep on a code string and return security findings.
    
    Args:
        code_content: The code to analyze.
        language: Programming language (determines file extension).
        rule_config: Semgrep ruleset to use (e.g., "p/security-audit") or a
            local rule file / directory. If omitted, the configured default is used.
        severity_filter: Set of severity levels to include. Defaults to
            {"ERROR", "WARNING"}.
        strip_fences: If True, strip markdown code fences before analysis.
        
    Returns:
        SemgrepResult containing findings or error information.
    """
    if severity_filter is None:
        severity_filter = DEFAULT_SEVERITY_FILTER

    resolved_rule_config = _resolve_rule_config(rule_config)

    # Preserve the raw LLM output for debug logging, then optionally strip fences.
    code_original = code_content
    fences_stripped = False
    if strip_fences:
        stripped = strip_markdown_fences(code_content)
        fences_stripped = stripped != code_content
        code_content = stripped

    proc_result: "subprocess.CompletedProcess | None" = None
    sem_result: SemgrepResult
    semgrep_command: list[str] | None = None

    # Handle empty code
    if not code_content.strip():
        sem_result = SemgrepResult(error="Empty code content")
        if write_debug:
            _write_semgrep_debug(
                code_original, code_content, language, resolved_rule_config, fences_stripped,
                None, sem_result, None,
            )
        return sem_result

    if resolved_rule_config.startswith(("/", ".", "~")) and not Path(resolved_rule_config).exists():
        sem_result = SemgrepResult(
            error=f"Local Semgrep config not found: {resolved_rule_config}"
        )
        if write_debug:
            _write_semgrep_debug(
                code_original, code_content, language, resolved_rule_config, fences_stripped,
                None, sem_result, None,
            )
        return sem_result

    suffix = LANG_EXTENSIONS.get(language, ".py")
    tmp_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code_content)
            tmp_path = tmp.name

        semgrep_command = [
            "semgrep",
            "scan",
            "--config", resolved_rule_config,
            "--json",
            "--disable-version-check",
            "--metrics", "off",
            "--quiet",
            "--jobs", str(_semgrep_jobs),
            tmp_path,
        ]

        proc_result = subprocess.run(
            semgrep_command,
            capture_output=True,
            text=True,
            timeout=_semgrep_subprocess_timeout_seconds,
        )

        # Proceed if stdout has content (even on non-zero exit, e.g. parse warnings).
        if not proc_result.stdout.strip():
            sem_result = SemgrepResult(
                error=proc_result.stderr or "Semgrep returned no output"
            )
        else:
            data = json.loads(proc_result.stdout)
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

            sem_result = SemgrepResult(findings=findings)

    except subprocess.TimeoutExpired:
        sem_result = SemgrepResult(error="Semgrep timed out")
    except json.JSONDecodeError as e:
        sem_result = SemgrepResult(error=f"Failed to parse Semgrep output: {e}")
    except FileNotFoundError:
        sem_result = SemgrepResult(error="Semgrep not installed or not in PATH")
    except Exception as e:
        sem_result = SemgrepResult(error=f"Unexpected error: {e}")
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if write_debug:
        _write_semgrep_debug(
            code_original, code_content, language, resolved_rule_config, fences_stripped,
            proc_result, sem_result, semgrep_command,
        )
    return sem_result


def warmup_semgrep(rule_config: str | None = None) -> tuple[float, SemgrepResult]:
    """Warm up Semgrep once so the first real scan does not pay the cold-start cost."""
    start_time = datetime.now(timezone.utc)
    result = run_semgrep(
        "def _semgrep_warmup():\n    return 1\n",
        language="python",
        rule_config=rule_config,
        strip_fences=False,
        write_debug=False,
    )
    elapsed_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
    return elapsed_seconds, result


def run_semgrep_batch(
    code_samples: list[tuple[str, str]],
    rule_config: str | None = None,
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
