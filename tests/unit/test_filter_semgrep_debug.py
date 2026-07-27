from __future__ import annotations

import json

from scripts.experiments.filter_semgrep_debug import process


def test_filter_is_idempotent_and_keeps_exact_scanner_input(tmp_path) -> None:
    path = tmp_path / "semgrep_debug.jsonl"
    stdout = json.dumps(
        {
            "results": [{"check_id": "demo"}],
            "errors": [{"type": "PartialParsing", "message": "bad target"}],
            "skipped_rules": [],
            "version": "1.85.0",
        }
    )
    record = {
        "code_raw": "```python\nprint(1)\n```",
        "code_analyzed": "print(1)",
        "semgrep_stdout": stdout,
        "semgrep_returncode": 0,
        "findings_count": 1,
        "findings": [{"check_id": "demo"}],
        "error": None,
        "error_kind": None,
    }
    path.write_text(json.dumps(record) + "\n")

    process(path, in_place=True, audit_only=False)
    first = json.loads(path.read_text())
    assert "semgrep_stdout" not in first
    assert "code_raw" not in first
    assert len(first["code_raw_sha256"]) == 64
    assert first["code_analyzed"] == "print(1)"
    assert first["semgrep_analysis"]["raw_results_count"] == 1
    assert len(first["semgrep_analysis"]["errors"]) == 1

    process(path, in_place=True, audit_only=False)
    second = json.loads(path.read_text())
    assert second["semgrep_analysis"] == first["semgrep_analysis"]
    assert second["code_raw_sha256"] == first["code_raw_sha256"]
