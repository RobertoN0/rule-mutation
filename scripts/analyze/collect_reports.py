#!/usr/bin/env python3
"""
Build a single ``REPORT.md`` from the per-analysis Markdown under a directory.

Default = a **curated** quick-read; each inlined section starts with one
``Source:`` link to its full report for the detail. ``--full`` inlines every
report verbatim instead.

It adapts to how many runs the directory holds:
  - **single run** -> the per-run reports (summary, outcomes, security, mutators,
    trajectories, search, cost), curated, in reading order.
  - **multiple runs** -> the cross-run highlights (outcome comparison, pooled
    mutators, efficiency comparison, cost), curated, followed by a per-run index
    linking each run's detail reports (not inlined, to keep it short).

Image links are rewritten so the PNGs (left in place) still render.

Usage:
    python scripts/analyze/collect_reports.py [root] [--out PATH] [--full]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Inline reading order for the single-run case.
_ORDER = {
    "summary.md": 0,
    "outcome_distribution.md": 1,
    "security.md": 2,
    "mutators.md": 3,
    "trajectories.md": 4,
    "search.md": 5,
    "cost.md": 6,
}
# Highlight order for the multi-run case (cross-run files).
_CROSS_ORDER = {
    "outcome_comparison.md": 0,
    "mutators_pooled.md": 1,
    "efficiency_comparison.md": 2,
    "comparison.md": 3,
    "cost.md": 4,
}

_CROSS_RUN_ONLY = {"outcome_comparison.md", "mutators_pooled.md", "efficiency_comparison.md", "comparison.md"}
_PER_RUN_FILES = {"summary.md", "outcome_distribution.md", "security.md", "mutators.md", "trajectories.md", "search.md"}
_SPECIAL_DIRS = {"run", "_pooled", "_comparison", "cost"}
_SKIP_PATH_SUBSTR = ("trajectories_archive",)

# Curated mode: "## " section headings (substring, lowercase) to drop per file.
_DROP_SECTIONS = {
    "summary.md": ["per-rule findings (table)", "convergence"],
    "outcome_distribution.md": ["the three counting scopes", "distribution figure", "per-rule applicable rates"],
    "mutators.md": ["recurring high-fitness combinations", "per-rule best path", "per-rule safest path"],
    "security.md": ["severity shifts", "check flips"],
}
# Curated mode: image-filename substrings to drop within kept sections.
_DROP_IMAGES = {
    "search.md": ("restart_reasons",),
    "trajectories.md": ("grid_iterations_f2", "grid_iterations_f3"),
}

_IMG = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")


def _rewrite_links(text: str, md_dir: Path, out_dir: Path) -> str:
    def repl(m: re.Match) -> str:
        target = m.group(2)
        if target.startswith(("http://", "https://", "/")):
            return m.group(0)
        return f"{m.group(1)}{os.path.relpath((md_dir / target).resolve(), out_dir.resolve())}{m.group(3)}"

    return _IMG.sub(repl, text)


def _split_sections(text: str) -> tuple[list[str], list[list[str]]]:
    header: list[str] = []
    sections: list[list[str]] = []
    cur: list[str] | None = None
    for ln in text.split("\n"):
        if ln.startswith("## "):
            if cur is not None:
                sections.append(cur)
            cur = [ln]
        elif cur is None:
            header.append(ln)
        else:
            cur.append(ln)
    if cur is not None:
        sections.append(cur)
    return header, sections


def _curate(text: str, basename: str) -> str:
    drop_sections = _DROP_SECTIONS.get(basename, [])
    drop_images = _DROP_IMAGES.get(basename, ())
    header, sections = _split_sections(text)
    kept = list(header)
    for sec in sections:
        heading = sec[0][3:].strip().lower()
        if any(d in heading for d in drop_sections):
            continue
        for ln in sec:
            if drop_images and "![" in ln and any(d in ln for d in drop_images):
                continue
            kept.append(ln)
    return "\n".join(kept)


def _block(md: Path, anchor: str, root: Path, out_dir: Path, curate: bool) -> tuple[str, str]:
    """Return (toc_entry, body) for one inlined report, with a single Source link."""
    rel = md.relative_to(root)
    link = os.path.relpath(md.resolve(), out_dir.resolve())
    text = md.read_text(encoding="utf-8")
    if curate:
        text = _curate(text, md.name)
    text = _rewrite_links(text, md.parent, out_dir)
    body = f'\n\n<a id="{anchor}"></a>\n\n---\n\n> **Source:** [`{rel}`]({link})\n\n{text}'
    return f"[{rel}](#{anchor})", body


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge analysis Markdown reports into one file")
    parser.add_argument("root", nargs="?", type=Path, default=Path("analysis_output"))
    parser.add_argument("--out", type=Path, default=None, help="default: <root>/REPORT.md")
    parser.add_argument("--full", action="store_true", help="inline every report verbatim (no curation)")
    args = parser.parse_args()

    root: Path = args.root
    out: Path = args.out or (root / "REPORT.md")
    out_dir = out.parent
    if not root.is_dir():
        print(f"No such directory: {root}", file=sys.stderr)
        return 1

    mds = [
        p for p in root.rglob("*.md")
        if p.resolve() != out.resolve() and not p.name.startswith("REPORT")
        and not any(s in str(p.relative_to(root)) for s in _SKIP_PATH_SUBSTR)
    ]
    if not mds:
        print(f"No .md reports under {root}", file=sys.stderr)
        return 1

    per_run = [p for p in mds if p.name in _PER_RUN_FILES]
    cross = [p for p in mds if p.name in _CROSS_RUN_ONLY]
    cost = [p for p in mds if p.name == "cost.md"]
    run_names = sorted({p.parent.name for p in per_run if p.parent.name not in _SPECIAL_DIRS})
    multi = len(run_names) >= 2

    toc: list[str] = ["# Analysis report", ""]
    bodies: list[str] = []

    if args.full:
        inline = sorted(mds, key=lambda p: (_ORDER.get(p.name, 50), str(p)))
        toc += [f"full report of `{root}` — every analysis inlined verbatim.", "", "## Contents", ""]
        for i, md in enumerate(inline, 1):
            entry, body = _block(md, f"report-{i}", root, out_dir, curate=False)
            toc.append(f"{i}. {entry}")
            bodies.append(body)
    elif not multi:
        inline = sorted(per_run + cost, key=lambda p: (_ORDER.get(p.name, 50), str(p)))
        toc += [f"curated quick-read of `{root}` — each section's Source link opens the full report.", "", "## Contents", ""]
        for i, md in enumerate(inline, 1):
            entry, body = _block(md, f"report-{i}", root, out_dir, curate=True)
            toc.append(f"{i}. {entry}")
            bodies.append(body)
    else:
        highlights = sorted(cross + cost, key=lambda p: (_CROSS_ORDER.get(p.name, 50), str(p)))
        toc += [f"curated cross-run quick-read of {len(run_names)} runs — highlights below, per-run detail linked at the end.",
                "", "## Contents", ""]
        i = 1
        for md in highlights:
            entry, body = _block(md, f"report-{i}", root, out_dir, curate=True)
            toc.append(f"{i}. {entry}")
            bodies.append(body)
            i += 1
        toc.append(f"{i}. [Per-run details](#per-run)")
        idx = ['\n\n<a id="per-run"></a>\n\n---\n\n## Per-run details',
               "\nFull per-run reports (not inlined; open the links):"]
        by_run = {rn: {p.name: p for p in per_run if p.parent.name == rn} for rn in run_names}
        for rn in run_names:
            idx.append(f"\n### {rn}")
            for fam in ("outcome_distribution.md", "security.md", "mutators.md", "trajectories.md", "search.md"):
                p = by_run[rn].get(fam)
                if p is not None:
                    link = os.path.relpath(p.resolve(), out_dir.resolve())
                    idx.append(f"- [{fam[:-3]}]({link})")
        bodies.append("\n".join(idx))

    out.write_text("\n".join(toc) + "\n" + "".join(bodies) + "\n", encoding="utf-8")
    kind = "full" if args.full else ("curated multi-run" if multi else "curated single-run")
    print(f"wrote {kind} REPORT ({len(run_names) or 1} run(s)) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
