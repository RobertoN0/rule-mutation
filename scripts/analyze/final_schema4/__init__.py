"""Strict schema-4 final-results analysis.

This package is deliberately separate from the historical schema-2 toolkit.
The public entry point is ``scripts/analyze/analyze_final_schema4.py``.
"""

from .core import (
    PENDING,
    AnalysisBundle,
    ManifestEntry,
    RunAnalysis,
    RunHealth,
    analyze_manifest,
    expected_manifest_entries,
    inspect_manifest,
    load_manifest,
    parse_seed_spec,
)

__all__ = [
    "PENDING",
    "AnalysisBundle",
    "ManifestEntry",
    "RunAnalysis",
    "RunHealth",
    "analyze_manifest",
    "expected_manifest_entries",
    "inspect_manifest",
    "load_manifest",
    "parse_seed_spec",
]
