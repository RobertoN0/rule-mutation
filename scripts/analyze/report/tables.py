"""
Shared serialization helpers for the report layer: CSV writing, Markdown tables,
and percentage / confidence-interval formatting.

These were duplicated across the analysis CLIs; centralising them keeps every
report formatting numbers and CIs identically.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

import stats as S


def write_csv(path: Path, header: Sequence, rows: Iterable[Iterable]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(list(header))
        writer.writerows(rows)


def md_table(header: Sequence, rows: Sequence[Sequence]) -> str:
    out = [
        "| " + " | ".join(str(h) for h in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    out.extend("| " + " | ".join(str(c) for c in row) + " |" for row in rows)
    return "\n".join(out)


def fmt_pct(value: float) -> str:
    if value != value:  # NaN
        return "nan"
    return f"{100 * value:.1f}%"


def fmt_ci(successes: int, n: int) -> str:
    point, lo, hi = S.wilson_ci(successes, n)
    return f"{fmt_pct(point)} [{fmt_pct(lo)}, {fmt_pct(hi)}]"
