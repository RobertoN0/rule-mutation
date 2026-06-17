"""
Security-effect (G1) report assembly: per-CWE, check-flip, and severity-shift
CSV + Markdown + plots. The only security layer that writes files.
"""

from __future__ import annotations

from pathlib import Path

import loaders as L
from metrics import outcomes as OC
from metrics import security as SEC
from report.tables import md_table, write_csv
from viz import security as VS


def write_run_report(run: L.RunData, out_dir: Path, code_divergence_threshold: float = 0.0) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    outcome = OC.build_run_outcome(run, code_divergence_threshold)

    cwe = SEC.cwe_rows(outcome)
    severity = SEC.severity_rows(outcome)
    flips = SEC.check_flip_rows(run)

    write_csv(out_dir / "cwe_table.csv", SEC.CWE_HEADER, cwe)
    write_csv(out_dir / "severity_shift.csv", SEC.SEVERITY_HEADER, severity)
    write_csv(out_dir / "check_flips.csv", SEC.CHECK_FLIP_HEADER, flips)

    if flips:
        VS.check_flip_bar(flips, out_dir / "check_flips.png", f"Check flips - {run.run_dir.name}")
    if any(r[1] > 0 for r in cwe):
        VS.cwe_outcome_bar(cwe, out_dir / "cwe_outcomes.png", f"Per-CWE outcomes - {run.run_dir.name}")

    lines = [f"# Security effect - {run.run_dir.name}\n"]
    lines.append(f"- language: {OC.lang_key(run)} | seed: {run.seed} | prompts: {len(outcome.prompt_states)}")
    lines.append("_Translates the abstract f1 deltas into concrete vulnerabilities: which CWE classes "
                 "and which exact Semgrep checks a rephrasing made appear (degraded) or disappear (safer)._\n")
    lines.append("## Per-CWE outcomes")
    lines.append(md_table(SEC.CWE_HEADER, cwe))
    if any(r[1] > 0 for r in cwe):
        lines.append("\n![cwe outcomes](cwe_outcomes.png)\n")
    lines.append("\n## Severity shifts (prompt-level)")
    lines.append("_Share of prompts whose error/warning count rose or fell under some rephrasing; "
                 "`rate_ci` is a 95% Wilson interval on that share._")
    lines.append(md_table(SEC.SEVERITY_HEADER, severity))
    lines.append("\n## Check flips (specific Semgrep checks added / removed by a rephrasing)")
    lines.append(md_table(SEC.CHECK_FLIP_HEADER, flips) if flips else "(no check changes observed)")
    if flips:
        lines.append("\n![check flips](check_flips.png)\n")
    (out_dir / "security.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
