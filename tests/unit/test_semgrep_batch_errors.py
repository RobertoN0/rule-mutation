from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from src.evaluation.semgrep_runner import (
    SemgrepSample,
    configure_semgrep,
    get_semgrep_config,
    run_semgrep_batch_dir,
)
from src.evaluation.semgrep_runner import _resolve_lang_aware_config_args


def _completed(payload: dict, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["semgrep"], returncode=returncode, stdout=json.dumps(payload), stderr=""
    )


def test_batch_maps_target_parse_error_to_only_its_sample() -> None:
    payload = {
        "results": [
            {
                "path": "/tmp/x/sample_0000.py",
                "check_id": "demo.rule",
                "extra": {"severity": "WARNING", "message": "demo"},
                "start": {"line": 1},
            }
        ],
        "errors": [
            {
                "path": "/tmp/x/sample_0001.py",
                "type": "Syntax error",
                "level": "warn",
                "message": "invalid syntax",
            }
        ],
        "skipped_rules": [],
    }
    with patch("src.evaluation.semgrep_runner.subprocess.run", return_value=_completed(payload)):
        results = run_semgrep_batch_dir([("print(1)", "python"), ("def x(", "python")])

    assert results[0].count == 1
    assert results[0].error is None
    assert results[1].error_kind == "target_parse"
    assert results[1].is_prompt_error


def test_global_rule_error_fails_every_active_sample() -> None:
    payload = {
        "results": [],
        "errors": [{"type": "InvalidRuleSchemaError", "message": "bad rule"}],
        "skipped_rules": [],
    }
    with patch("src.evaluation.semgrep_runner.subprocess.run", return_value=_completed(payload, 2)):
        results = run_semgrep_batch_dir([("print(1)", "python"), ("print(2)", "python")])

    assert all(result.is_system_error for result in results)
    assert all(result.error_kind == "semgrep_system" for result in results)


def test_precheck_failure_is_not_written_or_scored_as_clean() -> None:
    payload = {"results": [], "errors": [], "skipped_rules": []}
    samples = [
        SemgrepSample("def broken(", "def broken(", "python", "Python AST failed"),
        SemgrepSample("print(1)", "print(1)", "python"),
    ]
    with patch("src.evaluation.semgrep_runner.subprocess.run", return_value=_completed(payload)):
        results = run_semgrep_batch_dir(samples)

    assert results[0].error_kind == "input_validation"
    assert results[0].is_prompt_error
    assert results[1].error is None


def test_skipped_rules_are_a_system_failure() -> None:
    payload = {"results": [], "errors": [], "skipped_rules": [{"rule_id": "broken"}]}
    with patch("src.evaluation.semgrep_runner.subprocess.run", return_value=_completed(payload)):
        results = run_semgrep_batch_dir([("print(1)", "python")])
    assert results[0].is_system_error
    assert "skipped 1" in (results[0].error or "").lower()


def test_target_timeout_is_prompt_local_not_a_clean_zero() -> None:
    payload = {
        "results": [],
        "errors": [
            {
                "path": "/tmp/x/sample_0000.py",
                "type": "Timeout",
                "message": "target analysis timeout",
            }
        ],
        "skipped_rules": [],
    }
    with patch("src.evaluation.semgrep_runner.subprocess.run", return_value=_completed(payload)):
        result = run_semgrep_batch_dir([("print(1)", "python")])[0]
    assert result.error_kind == "target_analysis"
    assert result.is_prompt_error


def test_local_rules_config_has_content_fingerprint(tmp_path) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "one.yml").write_text("rules: []\n")
    (rules / "SOURCE_COMMIT").write_text("a" * 40 + "\n")
    (rules / "manifest.txt").write_text("machine-specific metadata\n")
    configure_semgrep(rule_config=str(rules), jobs=2)
    try:
        config = get_semgrep_config()
        assert config["rule_config_kind"] == "local"
        assert config["rule_file_count"] == 1
        assert len(config["rule_config_sha256"]) == 64
        assert config["rule_source_commit"] == "a" * 40
    finally:
        configure_semgrep(rule_config="p/security-audit", jobs=1)


def test_local_rules_fall_back_to_full_tree_if_any_language_subdir_is_missing(
    tmp_path,
) -> None:
    rules = tmp_path / "security-audit"
    (rules / "python").mkdir(parents=True)
    assert _resolve_lang_aware_config_args(str(rules), {"python"}) == [
        str((rules / "python").resolve())
    ]
    assert _resolve_lang_aware_config_args(str(rules), {"python", "java"}) == [
        str(rules.resolve())
    ]
