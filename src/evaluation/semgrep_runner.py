"""
Semgrep runner for evaluating security vulnerabilities in generated code.

Extracted from batch_experiment.py for reuse in the SBST hill climbing framework.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# Resolve the `semgrep` executable once. Prefer PATH (covers an activated venv
# or a system install), then fall back to the bin dir of the running Python
# interpreter — so the pipeline still finds Semgrep when launched via
# `.venv/bin/python` WITHOUT `source .venv/bin/activate` (which would otherwise
# leave `.venv/bin` off PATH and make every scan fail with "not installed").
_semgrep_exe: str | None = None


def _resolve_semgrep_executable() -> str:
    global _semgrep_exe
    if _semgrep_exe is not None:
        return _semgrep_exe
    found = shutil.which("semgrep")
    if not found:
        candidate = Path(sys.executable).parent / "semgrep"
        found = str(candidate) if candidate.exists() else "semgrep"
    _semgrep_exe = found
    return found


# Language → file extension mapping for Semgrep temp-file naming
LANG_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "java": ".java",
    "c": ".c",
    "cpp": ".cpp",
    "php": ".php",
    "rust": ".rs",
    "csharp": ".cs",
    "go": ".go",
    "ruby": ".rb",
    "kotlin": ".kt",
    "scala": ".scala",
}

# Language → subdirectory name inside a local Semgrep rules directory.
# When the configured ruleset is a local directory that contains per-language
# subdirectories (e.g. security-audit/python/, security-audit/javascript/),
# we pass only the relevant subdirs via separate --config flags.  This avoids
# loading thousands of YAML files for unrelated languages, dramatically
# reducing cold-start I/O on network filesystems like Lustre.
_LANG_SUBDIR: dict[str, str] = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "php": "php",
    "rust": "rust",
    "csharp": "csharp",
    "go": "go",
    "ruby": "ruby",
    "kotlin": "kotlin",
    "scala": "scala",
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


def _resolve_lang_aware_config_args(
    rule_config: str | None,
    languages: set[str],
) -> list[str]:
    """Return the list of ``--config <value>`` argument *values* for a batch.

    When *rule_config* resolves to a local directory and every language in
    *languages* has a corresponding subdirectory inside that directory, we
    return one path per language-specific subdir.  This dramatically reduces
    the number of YAML files Semgrep must parse (e.g. python + javascript ≈
    410 files instead of 1382 for the full security-audit tree) and avoids
    cold-start I/O timeouts on Lustre / network filesystems.

    Falls back to ``[resolved_config]`` (the full directory) whenever:
    - the config is a remote ruleset (e.g. ``p/security-audit``)
    - the resolved path is not a directory
    - any language in *languages* lacks a matching subdir
    """
    resolved = _resolve_rule_config(rule_config)
    base = Path(resolved)

    if not base.is_dir():
        return [resolved]  # Remote ruleset or single YAML file — pass as-is.

    lang_paths: list[str] = []
    for lang in sorted(languages):
        subdir_name = _LANG_SUBDIR.get(lang)
        if subdir_name is None:
            continue  # Unknown language — no subdir exists, skip it.
        subdir = base / subdir_name
        if not subdir.is_dir():
            continue  # Subdir missing (e.g. cpp) — skip rather than load all rules.
        lang_paths.append(str(subdir))

    return lang_paths if lang_paths else [resolved]


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

    config_args = _resolve_lang_aware_config_args(rule_config, {language})
    resolved_rule_config = config_args[0]  # used for debug logging / error messages

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

    base_config = _resolve_rule_config(rule_config)
    if base_config.startswith(("/", ".", "~")) and not Path(base_config).exists():
        sem_result = SemgrepResult(
            error=f"Local Semgrep config not found: {base_config}"
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

        config_flags: list[str] = []
        for c in config_args:
            config_flags.extend(["--config", c])
        semgrep_command = [
            _resolve_semgrep_executable(),
            "scan",
            *config_flags,
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


def run_semgrep_batch_dir(
    code_samples: list[tuple[str, str]],
    rule_config: str | None = None,
    strip_fences: bool = True,
) -> list[SemgrepResult]:
    """Run Semgrep on multiple code samples using a single subprocess.

    Writes all samples to a temporary directory and invokes Semgrep once,
    eliminating per-sample process startup overhead.  The subprocess timeout
    is scaled proportionally: ``len(code_samples) × _semgrep_subprocess_timeout_seconds``.

    Args:
        code_samples: List of ``(code, language)`` tuples to analyze.
        rule_config: Semgrep ruleset to use. Falls back to global default.
        strip_fences: Strip markdown code fences before analysis.

    Returns:
        List of :class:`SemgrepResult` in the same order as *code_samples*.
    """
    if not code_samples:
        return []

    languages = {lang for _, lang in code_samples}
    config_args = _resolve_lang_aware_config_args(rule_config, languages)
    resolved_rule_config = config_args[0]  # used for debug logging / error messages
    timeout = _semgrep_subprocess_timeout_seconds * len(code_samples)

    # Pre-process: strip fences, mark empty samples as None
    codes_cleaned: list[str | None] = []
    for code, _ in code_samples:
        if strip_fences:
            code = strip_markdown_fences(code)
        codes_cleaned.append(code if code.strip() else None)

    # proc/cmd are filled in once the subprocess runs; they stay None on the
    # error paths that never reach it (config missing, semgrep not installed).
    proc: "subprocess.CompletedProcess | None" = None
    cmd: list[str] | None = None

    def _debug_all(results: list["SemgrepResult"]) -> None:
        """Write one debug record per sample — covers the success path AND every
        error path, so a failed/aborted scan always leaves a trace (a record
        with a non-null ``error``) that is distinguishable from a clean scan
        with zero findings (``error`` null, ``findings_count`` 0)."""
        for i, sem_result in enumerate(results):
            code_raw, lang = code_samples[i]
            cleaned = codes_cleaned[i] if i < len(codes_cleaned) else None
            _write_semgrep_debug(
                code_raw, cleaned or "", lang, resolved_rule_config,
                cleaned != code_raw, proc, sem_result, cmd,
            )

    tmpdir = tempfile.mkdtemp()
    try:
        # Write non-empty samples to named temp files
        idx_to_path: dict[int, str] = {}
        for idx, code in enumerate(codes_cleaned):
            if code is None:
                continue
            _, lang = code_samples[idx]
            suffix = LANG_EXTENSIONS.get(lang, ".py")
            filepath = os.path.join(tmpdir, f"sample_{idx:04d}{suffix}")
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(code)
            idx_to_path[idx] = filepath

        if not idx_to_path:
            results = [SemgrepResult(error="Empty code content") for _ in code_samples]
            _debug_all(results)
            return results

        base_config = _resolve_rule_config(rule_config)
        if (
            base_config.startswith(("/", ".", "~"))
            and not Path(base_config).exists()
        ):
            err = SemgrepResult(error=f"Local Semgrep config not found: {base_config}")
            results = [err] * len(code_samples)
            _debug_all(results)
            return results

        config_flags: list[str] = []
        for c in config_args:
            config_flags.extend(["--config", c])
        cmd = [
            _resolve_semgrep_executable(), "scan",
            *config_flags,
            "--json",
            "--disable-version-check",
            "--metrics", "off",
            "--quiet",
            "--jobs", str(_semgrep_jobs),
            tmpdir,
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        if not proc.stdout.strip():
            err = SemgrepResult(error=proc.stderr or "Semgrep returned no output")
            results = [
                err if i in idx_to_path else SemgrepResult(error="Empty code content")
                for i in range(len(code_samples))
            ]
            _debug_all(results)
            return results

        data = json.loads(proc.stdout)

        # Group findings by sample index extracted from filename "sample_NNNN.ext"
        findings_by_idx: dict[int, list[SemgrepFinding]] = {
            i: [] for i in range(len(code_samples))
        }
        for r in data.get("results", []):
            basename = os.path.basename(r["path"])
            try:
                idx = int(basename.split("_")[1].split(".")[0])
            except (IndexError, ValueError):
                continue
            sev = r["extra"]["severity"].upper()
            if sev not in DEFAULT_SEVERITY_FILTER:
                continue
            findings_by_idx[idx].append(SemgrepFinding(
                check_id=r["check_id"],
                message=r["extra"]["message"],
                severity=sev,
                line=r["start"]["line"],
            ))

        results = [
            SemgrepResult(findings=findings_by_idx.get(i, []))
            if i in idx_to_path
            else SemgrepResult(error="Empty code content")
            for i in range(len(code_samples))
        ]

        _debug_all(results)
        return results

    except subprocess.TimeoutExpired:
        err = SemgrepResult(error=f"Semgrep batch timed out ({timeout}s)")
        results = [err] * len(code_samples)
        _debug_all(results)
        return results
    except json.JSONDecodeError as e:
        err = SemgrepResult(error=f"Failed to parse Semgrep output: {e}")
        results = [err] * len(code_samples)
        _debug_all(results)
        return results
    except FileNotFoundError:
        err = SemgrepResult(error="Semgrep not installed or not in PATH")
        results = [err] * len(code_samples)
        _debug_all(results)
        return results
    except Exception as e:
        err = SemgrepResult(error=f"Unexpected error: {e}")
        results = [err] * len(code_samples)
        _debug_all(results)
        return results
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
