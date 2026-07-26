from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.analyze.validate_qualified_maps import validate_qualified_maps


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_committed_final_maps_and_supporting_artifacts_validate() -> None:
    result = validate_qualified_maps(PROJECT_ROOT / "rule_maps" / "qualified")

    assert result["status"] == "VALID", result["issues"]
    assert result["counts"] == {"python": 203, "java": 126}


def test_validator_detects_map_changed_after_materialization(
    tmp_path: Path,
) -> None:
    source = PROJECT_ROOT / "rule_maps" / "qualified"
    copied = tmp_path / "qualified"
    shutil.copytree(source, copied)
    map_path = copied / "final_search_map_qwen_python.json"
    payload = json.loads(map_path.read_text())
    payload["mappings"].pop()
    map_path.write_text(json.dumps(payload))

    result = validate_qualified_maps(copied)

    assert result["status"] == "INVALID"
    assert any("SHA-256 differs" in issue for issue in result["issues"])
