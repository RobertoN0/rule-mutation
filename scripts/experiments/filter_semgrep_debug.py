#!/usr/bin/env python3
"""Filter + audit ``semgrep_debug.jsonl`` from a finished run.

Each line of ``semgrep_debug.jsonl`` is one semgrep invocation record. Almost all
of the file is the raw ``semgrep_stdout`` blob (the full semgrep JSON —
``results``/``paths``/timing), which is redundant once the pipeline has reduced it
to the per-call ``findings`` field (the rule-mapped subset f1 is scored from).
The raw ``results`` list holds *every* security-audit match (hundreds per call),
not the mapped ones, so it is dead weight for analysis — but the semgrep-level
``errors`` (syntax/parse/timeout failures on the generated code) also live inside
that blob and ARE worth keeping.

This tool streams the file and rewrites each record WITHOUT ``semgrep_stdout``,
extracting only ``errors`` + a raw-results count into a compact ``semgrep_analysis``
field. Typical reduction ~1.5 GB -> ~20 MB, so the (now small) debug can be synced
and inspected locally. It also emits an error audit — how many calls hit semgrep
errors, by level/type, plus any non-zero return codes — the "did any analysis go
wrong" check.

Login-node safe: pure stdlib, streaming (never loads the whole file), no GPU.

Examples
--------
    # filter one finished run (writes semgrep_debug.filtered.jsonl beside the raw)
    python scripts/experiments/filter_semgrep_debug.py experiments/results/jobNNN_ea_python_s42_0718

    # filter every finished run in the batch and REPLACE the raw file (reclaim space)
    python scripts/experiments/filter_semgrep_debug.py --in-place experiments/results/job10462*

    # just audit errors, write/replace nothing
    python scripts/experiments/filter_semgrep_debug.py --audit-only <run_dir_or_jsonl>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

RAW_FIELD = "semgrep_stdout"


def resolve_jsonl(path: Path) -> tuple[Path | None, Path | None]:
    """Map an input path to (jsonl_file, run_dir).

    Accepts a run dir, a ``semgrep_debug`` dir, or the ``.jsonl`` file itself.
    ``run_dir`` is returned when known so we can check for a final summary.
    """
    if path.is_file() and path.suffix == ".jsonl":
        run_dir = path.parent.parent if path.parent.name == "semgrep_debug" else None
        return path, run_dir
    for cand, run_dir in (
        (path / "semgrep_debug" / "semgrep_debug.jsonl", path),
        (path / "semgrep_debug.jsonl", path.parent if path.name == "semgrep_debug" else None),
    ):
        if cand.is_file():
            return cand, run_dir
    return None, None


def _compact_error(e: dict) -> dict:
    """Trim a semgrep error to the audit-relevant fields.

    Drops the verbose ``spans`` (byte offsets) and flattens the ``type`` — which
    semgrep serialises as a ``["PartialParsing", [<spans>]]`` tuple — down to its
    name. This is what makes the errors cheap enough to keep inline."""
    if not isinstance(e, dict):
        return {"message": str(e)[:300]}
    t = e.get("type")
    if isinstance(t, list):
        t = t[0] if t else None
    return {
        "level": e.get("level"),
        "code": e.get("code"),
        "type": t,
        "path": e.get("path"),
        "message": str(e.get("message", "")).replace("\n", " ")[:300],
    }


def compact_stdout(raw: str | None) -> dict:
    """Keep only the useful parts of the raw semgrep stdout JSON."""
    if not raw:
        return {"stdout_parse_ok": True, "errors": [], "raw_results_count": 0}
    try:
        d = json.loads(raw)
    except Exception:
        # Unparseable stdout is itself an error signal — keep a short head for triage.
        return {"stdout_parse_ok": False, "errors": [], "raw_results_count": None,
                "stdout_head": raw[:500]}
    return {
        "stdout_parse_ok": True,
        "errors": [_compact_error(e) for e in (d.get("errors") or [])],
        "raw_results_count": len(d.get("results", []) or []),
        "skipped_rules": d.get("skipped_rules", []),
        "version": d.get("version"),
    }


def _error_signature(err: dict) -> str:
    """Coarse error category for the audit histogram (err already compacted)."""
    if err.get("type"):
        return str(err["type"])[:60]
    msg = str(err.get("message", ""))
    # drop the file/line-specific tail so like errors group together
    for sep in (" at line", " at ", ":"):
        if sep in msg:
            msg = msg.split(sep, 1)[0]
    return (msg.strip() or "unknown")[:60]


def process(jsonl: Path, *, in_place: bool, audit_only: bool) -> dict:
    """Stream one semgrep_debug.jsonl: write filtered copy (unless audit-only)
    and return an error/size audit dict."""
    size_before = jsonl.stat().st_size
    out_path = jsonl.with_name("semgrep_debug.filtered.jsonl")
    tmp_path = jsonl.with_name(jsonl.name + ".filtering.tmp")

    a = {
        "records": 0, "malformed_lines": 0, "records_with_findings": 0,
        "total_findings": 0, "records_with_errors": 0, "total_errors": 0,
        "nonzero_returncode": 0, "record_error_field": 0, "stdout_parse_failures": 0,
    }
    by_level: Counter = Counter()
    by_type: Counter = Counter()
    by_returncode: Counter = Counter()

    out = None if audit_only else open(tmp_path, "w")
    try:
        with open(jsonl, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    a["malformed_lines"] += 1
                    continue
                a["records"] += 1

                rc = rec.get("semgrep_returncode")
                by_returncode[rc] += 1
                if rc not in (0, 1, None):
                    a["nonzero_returncode"] += 1
                if rec.get("error"):
                    a["record_error_field"] += 1
                fc = rec.get("findings_count") or 0
                if fc:
                    a["records_with_findings"] += 1
                    a["total_findings"] += fc

                raw_stdout = rec.pop(RAW_FIELD, None)
                existing_analysis = rec.get("semgrep_analysis")
                analysis = (
                    existing_analysis
                    if raw_stdout is None and isinstance(existing_analysis, dict)
                    else compact_stdout(raw_stdout)
                )
                if not analysis["stdout_parse_ok"]:
                    a["stdout_parse_failures"] += 1
                errs = analysis["errors"]
                if errs:
                    a["records_with_errors"] += 1
                    a["total_errors"] += len(errs)
                    for e in errs:
                        by_level[e.get("level", "?")] += 1
                        by_type[_error_signature(e)] += 1

                if out is not None:
                    raw_code = rec.pop("code_raw", None)
                    if isinstance(raw_code, str):
                        rec["code_raw_sha256"] = hashlib.sha256(
                            raw_code.encode("utf-8")
                        ).hexdigest()
                    rec["semgrep_analysis"] = analysis
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    finally:
        if out is not None:
            out.close()

    if not audit_only:
        if in_place:
            os.replace(tmp_path, jsonl)          # atomically shrink the raw file
            written = jsonl
        else:
            os.replace(tmp_path, out_path)
            written = out_path
        a["size_after"] = written.stat().st_size
        a["output"] = str(written)
    else:
        if tmp_path.exists():
            tmp_path.unlink()
        a["size_after"] = None
        a["output"] = None

    a["size_before"] = size_before
    a["returncodes"] = dict(by_returncode)
    a["errors_by_level"] = dict(by_level)
    a["errors_by_type"] = dict(by_type.most_common(12))
    return a


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024


def print_report(name: str, a: dict) -> None:
    rec = a["records"]
    print(f"\n=== {name} ===")
    print(f"  records:            {rec:,}"
          + (f"  ({a['malformed_lines']} malformed lines skipped)" if a["malformed_lines"] else ""))
    print(f"  with findings:      {a['records_with_findings']:,}  "
          f"(total findings {a['total_findings']:,})")
    if a["size_after"] is not None:
        sb, sa = a["size_before"], a["size_after"]
        ratio = (sb / sa) if sa else 0
        print(f"  size:               {_fmt_bytes(sb)} -> {_fmt_bytes(sa)}  ({ratio:.0f}x smaller)")
        print(f"  wrote:              {a['output']}")
    else:
        print(f"  size (unchanged):   {_fmt_bytes(a['size_before'])}  (audit-only)")
    # --- error audit ---
    n_err = a["records_with_errors"]
    print(f"  semgrep errors:     {n_err:,} / {rec:,} records had >=1 error "
          f"({a['total_errors']:,} total)")
    if a["errors_by_level"]:
        print(f"    by level:         {a['errors_by_level']}")
    for sig, c in a["errors_by_type"].items():
        print(f"      {c:>7,}  {sig}")
    flags = []
    if a["nonzero_returncode"]:
        flags.append(f"{a['nonzero_returncode']} non-0/1 returncodes")
    if a["record_error_field"]:
        flags.append(f"{a['record_error_field']} wrapper errors")
    if a["stdout_parse_failures"]:
        flags.append(f"{a['stdout_parse_failures']} unparseable stdout")
    print(f"  {'⚠️  ' + '; '.join(flags) if flags else '✅ no return-code / wrapper / parse failures'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="+", type=Path,
                   help="run dir(s), semgrep_debug dir(s), or semgrep_debug.jsonl file(s)")
    p.add_argument("--in-place", action="store_true",
                   help="replace the raw semgrep_debug.jsonl with the filtered one (reclaim space)")
    p.add_argument("--audit-only", action="store_true",
                   help="only report errors; write nothing")
    p.add_argument("--force", action="store_true",
                   help="process even runs with no final summary (i.e. possibly unfinished)")
    p.add_argument("--audit-json", action="store_true",
                   help="also write semgrep_audit.json next to each processed file")
    args = p.parse_args(argv)

    processed = failed = skipped = 0
    for path in args.paths:
        jsonl, run_dir = resolve_jsonl(path)
        if jsonl is None:
            print(f"⚠️  no semgrep_debug.jsonl found under {path}", file=sys.stderr)
            failed += 1
            continue
        completed = run_dir is None or any(run_dir.glob("hillclimb_summary_*.json"))
        if not completed and not args.force:
            print(f"⏭️  {run_dir.name}: no final summary (run not finished?) — skipping "
                  f"(use --force to override)", file=sys.stderr)
            skipped += 1
            continue
        try:
            a = process(jsonl, in_place=args.in_place, audit_only=args.audit_only)
        except Exception as e:  # noqa: BLE001 — one bad file must not abort the batch
            print(f"❌ {jsonl}: {e}", file=sys.stderr)
            failed += 1
            continue
        print_report(run_dir.name if run_dir else jsonl.name, a)
        if args.audit_json:
            rep = jsonl.with_name("semgrep_audit.json")
            rep.write_text(json.dumps(a, indent=2))
            print(f"  audit:              {rep}")
        processed += 1

    print(f"\nDone: {processed} processed"
          + (f", {skipped} skipped" if skipped else "")
          + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
