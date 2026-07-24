#!/usr/bin/env python3
"""Audit and apply prospective task-population exclusions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.retrieval.consensus import (  # noqa: E402
    load_json_object,
    task_content_identity,
    write_json,
)
from src.retrieval.population import (  # noqa: E402
    audit_population,
    filter_population_map,
    validate_eligibility_manifest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser(
        "audit",
        help="Record population fingerprints and exact duplicate prompts.",
    )
    audit.add_argument("--carrier", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--overwrite", action="store_true")

    apply = subparsers.add_parser(
        "apply",
        help="Validate a reviewed manifest and physically filter maps.",
    )
    apply.add_argument("--carrier", type=Path, required=True)
    apply.add_argument("--manifest", type=Path, required=True)
    apply.add_argument("--map", type=Path, action="append", required=True)
    apply.add_argument("--output-dir", type=Path, required=True)
    apply.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def _assert_map_is_carrier_subset(
    payload: dict,
    *,
    carrier: dict,
    path: Path,
) -> None:
    carrier_by_id = {
        str(row["index"]): row for row in carrier.get("mappings", [])
    }
    for row in payload.get("mappings", []):
        task_id = str(row.get("index"))
        source = carrier_by_id.get(task_id)
        if source is None or task_content_identity(row) != task_content_identity(source):
            raise ValueError(
                f"{path}: task {task_id} is absent from or differs from the carrier"
            )


def _run(args: argparse.Namespace) -> int:
    if args.command == "audit":
        payload = audit_population(args.carrier)
        write_json(args.output, payload, overwrite=args.overwrite)
        print(
            f"Audited {payload['source_population']['tasks']} tasks; "
            f"duplicate prompt hashes={len(payload['duplicate_prompt_hashes'])}"
        )
        print(f"Population audit: {args.output}")
        return 0

    carrier = load_json_object(args.carrier)
    manifest = load_json_object(args.manifest)
    exclusions = validate_eligibility_manifest(
        manifest,
        carrier_path=args.carrier,
        carrier=carrier,
    )
    for path in args.map:
        payload = load_json_object(path)
        _assert_map_is_carrier_subset(payload, carrier=carrier, path=path)
        filtered = filter_population_map(
            payload,
            exclusions=exclusions,
            manifest_path=args.manifest,
            manifest=manifest,
        )
        output = args.output_dir / path.name
        write_json(output, filtered, overwrite=args.overwrite)
        print(
            f"{path.name}: {len(payload['mappings'])} -> "
            f"{len(filtered['mappings'])}"
        )
    print(f"Eligible maps written to {args.output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return _run(args)
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
