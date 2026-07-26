"""
Semgrep runner for evaluating security vulnerabilities in generated code.

Used by the SBST rule-set search to score generated code.
"""

from __future__ import annotations

import json
import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
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
    "bash": ".sh",
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
    "bash": "bash",
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


@lru_cache(maxsize=8)
def _rules_fingerprint(path_value: str) -> tuple[str, int]:
    path = Path(path_value)
    # Hash only rule definitions.  Operational metadata such as an absolute-path
    # manifest must not make an otherwise identical ruleset hash differently on
    # two machines.
    files = sorted(
        file
        for pattern in ("*.yml", "*.yaml")
        for file in path.rglob(pattern)
        if file.is_file()
    )
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def get_semgrep_config() -> dict[str, int | str | None]:
    """Return the currently active Semgrep configuration."""
    resolved = _resolve_rule_config(_semgrep_rule_config)
    path = Path(resolved)
    fingerprint: str | None = None
    file_count: int | None = None
    source_commit: str | None = None
    if path.is_dir():
        fingerprint, file_count = _rules_fingerprint(str(path))
        source_commit_path = path / "SOURCE_COMMIT"
        if source_commit_path.is_file():
            source_commit = source_commit_path.read_text(encoding="utf-8").strip() or None
    try:
        semgrep_version = importlib.metadata.version("semgrep")
    except importlib.metadata.PackageNotFoundError:
        semgrep_version = "unknown"
    return {
        "rule_config": resolved,
        "rule_config_kind": "local" if path.exists() else "remote",
        "rule_config_sha256": fingerprint,
        "rule_file_count": file_count,
        "rule_source_commit": source_commit,
        "semgrep_version": semgrep_version,
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
            return [resolved]
        subdir = base / subdir_name
        if not subdir.is_dir():
            return [resolved]
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
    *,
    include_process_payload: bool = True,
    batch_sample_index: int | None = None,
    batch_size: int | None = None,
    normalization: str = "none",
    analysis_line_map: tuple[int | None, ...] = (),
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
            "batch_sample_index": batch_sample_index,
            "batch_size": batch_size,
            "fences_stripped": fences_stripped,
            "normalization": normalization,
            "analysis_line_map": list(analysis_line_map),
            "code_raw": code_original,
            "code_analyzed": code_analyzed,
            "semgrep_returncode": proc_result.returncode if proc_result is not None else None,
            "semgrep_stdout": (
                proc_result.stdout
                if proc_result is not None and include_process_payload else None
            ),
            "semgrep_stderr": (
                proc_result.stderr
                if proc_result is not None and include_process_payload else None
            ),
            "findings_count": sem_result.count,
            "synthetic_findings_filtered": sem_result.synthetic_findings_filtered,
            "error": sem_result.error,
            "error_kind": sem_result.error_kind,
            "findings": [
                {
                    "check_id": f.check_id,
                    "severity": f.severity,
                    "line": f.line,
                    "analyzed_line": f.analyzed_line,
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
    analyzed_line: int | None = None
    
    def __hash__(self) -> int:
        return hash((self.check_id, self.line))


@dataclass
class SemgrepResult:
    """Result of running Semgrep on a code snippet."""
    
    findings: list[SemgrepFinding] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None
    synthetic_findings_filtered: int = 0
    """Machine-readable failure class. Task-specific failures are distinguished
    from evaluator/infrastructure failures so callers cannot silently score a
    failed scan as zero findings."""
    
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

    @property
    def is_prompt_error(self) -> bool:
        return self.error_kind in {
            "input_validation",
            "target_parse",
            "target_analysis",
            "empty_code",
            "empty_output",
            "generation_incomplete",
            "malformed_output",
            "language_drift",
            "multiple_target_blocks",
            "syntax_invalid",
            "vacuous_output",
        }

    @property
    def is_system_error(self) -> bool:
        return self.error is not None and not self.is_prompt_error


@dataclass(frozen=True)
class SemgrepSample:
    """One batch sample with raw and already-selected code kept separate."""

    code_raw: str
    code_analyzed: str
    language: str
    precheck_error: str | None = None
    precheck_error_kind: str = "input_validation"
    normalization: str = "none"
    analysis_line_map: tuple[int | None, ...] = ()

    def __iter__(self):
        """Keep simple test doubles that unpack ``(code, language)`` working."""
        yield self.code_raw
        yield self.language


def _map_finding_span(
    sample: SemgrepSample,
    analyzed_start_line: int,
    analyzed_end_line: int,
) -> int | None:
    """Map a finding to source, dropping matches confined to synthetic wrappers."""
    if sample.normalization == "none":
        return analyzed_start_line
    start = max(analyzed_start_line, 1)
    end = min(max(analyzed_end_line, start), len(sample.analysis_line_map))
    for analyzed_line in range(start, end + 1):
        source_line = sample.analysis_line_map[analyzed_line - 1]
        if source_line is not None:
            return source_line
    return None


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
        sem_result = SemgrepResult(error="Empty code content", error_kind="empty_code")
        if write_debug:
            _write_semgrep_debug(
                code_original, code_content, language, resolved_rule_config, fences_stripped,
                None, sem_result, None,
            )
        return sem_result

    base_config = _resolve_rule_config(rule_config)
    if base_config.startswith(("/", ".", "~")) and not Path(base_config).exists():
        sem_result = SemgrepResult(
            error=f"Local Semgrep config not found: {base_config}",
            error_kind="invalid_config",
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
                error=proc_result.stderr or "Semgrep returned no output",
                error_kind="process",
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

            errors = data.get("errors") or []
            skipped_rules = data.get("skipped_rules") or []
            if skipped_rules:
                sem_result = SemgrepResult(
                    findings=findings,
                    error=f"Semgrep skipped {len(skipped_rules)} configured rule(s)",
                    error_kind="semgrep_system",
                )
            elif errors:
                is_target = all(_is_target_parse_error(error) for error in errors)
                target_kinds = {_target_error_kind(error) for error in errors}
                sem_result = SemgrepResult(
                    findings=findings,
                    error="; ".join(_semgrep_error_text(error) for error in errors),
                    error_kind=(
                        "target_analysis"
                        if is_target and "target_analysis" in target_kinds
                        else "target_parse" if is_target else "semgrep_system"
                    ),
                )
            elif proc_result.returncode != 0:
                sem_result = SemgrepResult(
                    findings=findings,
                    error=(
                        f"Semgrep exited with status {proc_result.returncode}: "
                        f"{proc_result.stderr.strip()}"
                    ),
                    error_kind="process",
                )
            else:
                sem_result = SemgrepResult(findings=findings)

    except subprocess.TimeoutExpired:
        sem_result = SemgrepResult(error="Semgrep timed out", error_kind="timeout")
    except json.JSONDecodeError as e:
        sem_result = SemgrepResult(error=f"Failed to parse Semgrep output: {e}", error_kind="json")
    except FileNotFoundError:
        sem_result = SemgrepResult(error="Semgrep not installed or not in PATH", error_kind="not_installed")
    except Exception as e:
        sem_result = SemgrepResult(error=f"Unexpected error: {e}", error_kind="unexpected")
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if write_debug:
        _write_semgrep_debug(
            code_original, code_content, language, resolved_rule_config, fences_stripped,
            proc_result, sem_result, semgrep_command,
        )
    return sem_result


def _sample_index_from_path(path: str | None) -> int | None:
    if not path:
        return None
    match = re.search(r"sample_(\d+)", os.path.basename(path))
    return int(match.group(1)) if match else None


def _semgrep_error_text(error: object) -> str:
    if not isinstance(error, dict):
        return str(error)
    parts = [str(error.get(key, "")).strip() for key in ("type", "level", "message")]
    return ": ".join(part for part in parts if part) or json.dumps(error, sort_keys=True)


def _semgrep_error_path(error: object) -> str | None:
    if not isinstance(error, dict):
        return None
    path = error.get("path")
    if isinstance(path, str):
        return path
    spans = error.get("spans")
    if isinstance(spans, list):
        for span in spans:
            if isinstance(span, dict) and isinstance(span.get("file"), str):
                return span["file"]
    return None


def _is_target_parse_error(error: object) -> bool:
    text = _semgrep_error_text(error).lower()
    return any(
        term in text
        for term in ("parse", "syntax", "partially parsed", "lexical", "timeout")
    )


def _target_error_kind(error: object) -> str:
    return "target_analysis" if "timeout" in _semgrep_error_text(error).lower() else "target_parse"


def run_semgrep_batch_dir(
    code_samples: list[tuple[str, str] | SemgrepSample],
    rule_config: str | None = None,
    strip_fences: bool = True,
) -> list[SemgrepResult]:
    """Analyze a batch and preserve task-level versus systemic failures.

    ``SemgrepSample`` inputs carry the raw model output, selected code, and any
    pre-analysis validation failure. ``(code, language)`` tuples provide a
    compact low-level interface when that metadata is not required.
    """
    if not code_samples:
        return []

    samples: list[SemgrepSample] = []
    for sample in code_samples:
        if isinstance(sample, SemgrepSample):
            samples.append(sample)
        else:
            code, language = sample
            analyzed = strip_markdown_fences(code) if strip_fences else code
            samples.append(SemgrepSample(code, analyzed, language))

    active_languages = {
        sample.language
        for sample in samples
        if sample.precheck_error is None and sample.code_analyzed.strip()
    }
    config_args = _resolve_lang_aware_config_args(rule_config, active_languages)
    resolved_rule_config = config_args[0]
    timeout = _semgrep_subprocess_timeout_seconds * len(samples)
    codes_cleaned: list[str | None] = [
        sample.code_analyzed if sample.code_analyzed.strip() else None
        for sample in samples
    ]

    proc: "subprocess.CompletedProcess | None" = None
    cmd: list[str] | None = None

    def _debug_all(results: list[SemgrepResult]) -> None:
        for idx, sem_result in enumerate(results):
            sample = samples[idx]
            cleaned = codes_cleaned[idx]
            _write_semgrep_debug(
                sample.code_raw,
                cleaned or "",
                sample.language,
                resolved_rule_config,
                cleaned != sample.code_raw,
                proc,
                sem_result,
                cmd,
                include_process_payload=(idx == 0),
                batch_sample_index=idx,
                batch_size=len(results),
                normalization=sample.normalization,
                analysis_line_map=sample.analysis_line_map,
            )

    def _system_results(message: str, kind: str) -> list[SemgrepResult]:
        return [
            SemgrepResult(
                error=sample.precheck_error or message,
                error_kind=sample.precheck_error_kind if sample.precheck_error else kind,
            )
            for sample in samples
        ]

    tmpdir = tempfile.mkdtemp()
    try:
        idx_to_path: dict[int, str] = {}
        for idx, code in enumerate(codes_cleaned):
            if code is None or samples[idx].precheck_error is not None:
                continue
            suffix = LANG_EXTENSIONS.get(samples[idx].language, ".py")
            filepath = os.path.join(tmpdir, f"sample_{idx:04d}{suffix}")
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(code)
            idx_to_path[idx] = filepath

        if not idx_to_path:
            results = [
                SemgrepResult(
                    error=sample.precheck_error or "Empty code content",
                    error_kind=sample.precheck_error_kind if sample.precheck_error else "empty_code",
                )
                for sample in samples
            ]
            _debug_all(results)
            return results

        base_config = _resolve_rule_config(rule_config)
        if base_config.startswith(("/", ".", "~")) and not Path(base_config).exists():
            results = _system_results(
                f"Local Semgrep config not found: {base_config}", "invalid_config"
            )
            _debug_all(results)
            return results

        config_flags: list[str] = []
        for config in config_args:
            config_flags.extend(["--config", config])
        cmd = [
            _resolve_semgrep_executable(),
            "scan",
            *config_flags,
            "--json",
            "--disable-version-check",
            "--metrics",
            "off",
            "--quiet",
            "--jobs",
            str(_semgrep_jobs),
            tmpdir,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        if not proc.stdout.strip():
            results = _system_results(proc.stderr or "Semgrep returned no output", "process")
            _debug_all(results)
            return results

        data = json.loads(proc.stdout)
        findings_by_idx: dict[int, list[SemgrepFinding]] = {
            idx: [] for idx in range(len(samples))
        }
        synthetic_findings_filtered = {idx: 0 for idx in range(len(samples))}
        unmapped_result_paths: list[str] = []
        for result in data.get("results", []):
            idx = _sample_index_from_path(result.get("path"))
            if idx is None or idx not in idx_to_path:
                unmapped_result_paths.append(str(result.get("path")))
                continue
            severity = result["extra"]["severity"].upper()
            if severity not in DEFAULT_SEVERITY_FILTER:
                continue
            analyzed_line = result["start"]["line"]
            analyzed_end_line = result.get("end", {}).get("line", analyzed_line)
            source_line = _map_finding_span(
                samples[idx], analyzed_line, analyzed_end_line
            )
            if source_line is None:
                synthetic_findings_filtered[idx] += 1
                continue
            findings_by_idx[idx].append(
                SemgrepFinding(
                    check_id=result["check_id"],
                    message=result["extra"]["message"],
                    severity=severity,
                    line=source_line,
                    analyzed_line=(
                        analyzed_line
                        if samples[idx].normalization != "none"
                        else None
                    ),
                )
            )

        prompt_errors: dict[int, list[str]] = {}
        prompt_error_kinds: dict[int, str] = {}
        global_errors: list[str] = []
        for error in data.get("errors", []):
            idx = _sample_index_from_path(_semgrep_error_path(error))
            message = _semgrep_error_text(error)
            if idx in idx_to_path and _is_target_parse_error(error):
                prompt_errors.setdefault(idx, []).append(message)
                prompt_error_kinds[idx] = _target_error_kind(error)
            else:
                global_errors.append(message)

        skipped_rules = data.get("skipped_rules") or []
        if skipped_rules:
            global_errors.append(f"Semgrep skipped {len(skipped_rules)} configured rule(s)")
        if unmapped_result_paths:
            global_errors.append(
                "Semgrep returned findings for unmapped targets: "
                + ", ".join(unmapped_result_paths[:3])
            )
        if proc.returncode != 0 and not global_errors and not prompt_errors:
            global_errors.append(
                f"Semgrep exited with status {proc.returncode}: {proc.stderr.strip()}"
            )

        if global_errors:
            results = _system_results("; ".join(global_errors), "semgrep_system")
            _debug_all(results)
            return results

        results: list[SemgrepResult] = []
        for idx, sample in enumerate(samples):
            if sample.precheck_error is not None:
                results.append(
                    SemgrepResult(error=sample.precheck_error, error_kind=sample.precheck_error_kind)
                )
            elif idx not in idx_to_path:
                results.append(SemgrepResult(error="Empty code content", error_kind="empty_code"))
            elif idx in prompt_errors:
                results.append(
                    SemgrepResult(
                        findings=findings_by_idx[idx],
                        error="; ".join(prompt_errors[idx]),
                        error_kind=prompt_error_kinds[idx],
                        synthetic_findings_filtered=synthetic_findings_filtered[idx],
                    )
                )
            else:
                results.append(
                    SemgrepResult(
                        findings=findings_by_idx[idx],
                        synthetic_findings_filtered=synthetic_findings_filtered[idx],
                    )
                )

        _debug_all(results)
        return results

    except subprocess.TimeoutExpired:
        results = _system_results(f"Semgrep batch timed out ({timeout}s)", "timeout")
        _debug_all(results)
        return results
    except json.JSONDecodeError as exc:
        results = _system_results(f"Failed to parse Semgrep output: {exc}", "json")
        _debug_all(results)
        return results
    except FileNotFoundError:
        results = _system_results("Semgrep not installed or not in PATH", "not_installed")
        _debug_all(results)
        return results
    except Exception as exc:
        results = _system_results(f"Unexpected error: {exc}", "unexpected")
        _debug_all(results)
        return results
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
