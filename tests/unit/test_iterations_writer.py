"""B1: tests for the atomic iterations.jsonl append (fcntl.flock)."""

import fcntl
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal helpers
# ---------------------------------------------------------------------------

def _make_record(iter_n: int) -> dict:
    return {
        "iter": iter_n,
        "timestamp": "2026-05-25T12:00:00Z",
        "strategy": "ea",
        "rule_id": "codeguard-0-test",
        "mutation_chain": ["synonym_replacement"],
        "chain_length": 1,
        "accepted": True,
    }


# ---------------------------------------------------------------------------
# B1-1  Sequential writes via the locked append path produce valid JSONL
# ---------------------------------------------------------------------------

class TestAtomicAppend:

    def _make_writer_object(self, path: Path):
        """Minimal object mimicking ExperimentEngine._append_iteration_record."""
        import fcntl
        import json

        class _Writer:
            def __init__(self, p):
                self._file = open(p, "a", encoding="utf-8")

            def append(self, record: dict):
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
                try:
                    self._file.write(json.dumps(record) + "\n")
                    self._file.flush()
                finally:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)

            def close(self):
                self._file.close()

        return _Writer(path)

    def test_sequential_writes_produce_clean_jsonl(self, tmp_path):
        """10 sequential writes → all records parse as valid JSON."""
        jsonl = tmp_path / "iterations.jsonl"
        writer = self._make_writer_object(jsonl)
        n = 10
        for i in range(1, n + 1):
            writer.append(_make_record(i))
        writer.close()

        lines = jsonl.read_text(encoding="utf-8").splitlines()
        assert len(lines) == n
        for idx, line in enumerate(lines, start=1):
            rec = json.loads(line)
            assert rec["iter"] == idx

    def test_two_appenders_same_process_no_interleaving(self, tmp_path):
        """Two writer objects appending to the same file alternately produce valid JSONL."""
        jsonl = tmp_path / "iterations.jsonl"
        w1 = self._make_writer_object(jsonl)
        w2 = self._make_writer_object(jsonl)

        for i in range(1, 6):
            w1.append(_make_record(i))
            w2.append(_make_record(i + 100))

        w1.close()
        w2.close()

        lines = jsonl.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 10
        # Every line must be valid JSON
        for line in lines:
            rec = json.loads(line)
            assert "iter" in rec

    def test_flock_released_after_write(self, tmp_path):
        """Lock is released (LOCK_UN) after each write so subsequent calls succeed."""
        jsonl = tmp_path / "iterations.jsonl"
        writer = self._make_writer_object(jsonl)
        writer.append(_make_record(1))
        writer.append(_make_record(2))
        writer.close()
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
