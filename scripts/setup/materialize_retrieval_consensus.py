#!/usr/bin/env python3
"""Validate retrieval sweeps and materialize canonical majority-rule maps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.retrieval.consensus import (  # noqa: E402
    build_norules_map,
    build_population_carrier,
    materialize_consensus_map,
    merge_consensus_parts,
    paths_for_accepted_seeds,
    validate_retrieval_sweep,
    write_json,
)


DEFAULT_RULES_DIR = (
    PROJECT_ROOT
    / "project-codeguard"
    / "skills"
    / "software-security"
    / "rules"
)


def parse_seed_list(value: str) -> tuple[int, ...]:
    seeds: list[int] = []
    for component in value.split(","):
        component = component.strip()
        if not component:
            continue
        if "-" in component:
            start_text, end_text = component.split("-", 1)
            start, end = int(start_text), int(end_text)
            if end < start:
                raise argparse.ArgumentTypeError(
                    f"invalid descending seed range {component!r}"
                )
            seeds.extend(range(start, end + 1))
        else:
            seeds.append(int(component))
    if not seeds:
        raise argparse.ArgumentTypeError("seed list is empty")
    if len(seeds) != len(set(seeds)):
        raise argparse.ArgumentTypeError("seed list contains duplicates")
    return tuple(seeds)


def _add_sweep_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--maps-dir", type=Path, required=True)
    parser.add_argument("--carrier", type=Path, required=True)
    parser.add_argument("--model", choices=("qwen", "llama"), required=True)
    parser.add_argument("--language", choices=("python", "java"), required=True)
    parser.add_argument("--accepted-seeds", type=parse_seed_list, required=True)
    parser.add_argument("--rules-dir", type=Path, default=DEFAULT_RULES_DIR)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate",
        help="Validate exactly twenty accepted retrieval maps.",
    )
    _add_sweep_arguments(validate)
    validate.add_argument("--report", type=Path, required=True)
    validate.add_argument("--overwrite", action="store_true")

    consensus = subparsers.add_parser(
        "consensus",
        help="Validate a sweep and materialize one canonical consensus part.",
    )
    _add_sweep_arguments(consensus)
    consensus.add_argument("--canonical-carrier", type=Path, required=True)
    consensus.add_argument("--output", type=Path, required=True)
    consensus.add_argument("--validation-report", type=Path, required=True)
    consensus.add_argument("--overwrite", action="store_true")

    merge = subparsers.add_parser(
        "merge",
        help="Merge disjoint canonical consensus parts in full-carrier order.",
    )
    merge.add_argument("--part", type=Path, action="append", required=True)
    merge.add_argument("--canonical-carrier", type=Path, required=True)
    merge.add_argument("--model", choices=("qwen", "llama"), required=True)
    merge.add_argument("--language", choices=("python", "java"), required=True)
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--overwrite", action="store_true")

    norules = subparsers.add_parser(
        "norules",
        help="Materialize an empty-rule map over a canonical carrier.",
    )
    norules.add_argument("--canonical-carrier", type=Path, required=True)
    norules.add_argument("--output", type=Path, required=True)
    norules.add_argument("--overwrite", action="store_true")

    carrier = subparsers.add_parser(
        "carrier",
        help="Create a clean canonical task carrier from a source mapping.",
    )
    carrier.add_argument("--source", type=Path, required=True)
    carrier.add_argument("--output", type=Path, required=True)
    carrier.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def _validated_sweep(args: argparse.Namespace):
    paths = paths_for_accepted_seeds(args.maps_dir, args.accepted_seeds)
    return validate_retrieval_sweep(
        paths,
        carrier_path=args.carrier,
        model=args.model,
        language=args.language,
        accepted_seeds=args.accepted_seeds,
        rules_dir=args.rules_dir,
    )


def _run(args: argparse.Namespace) -> int:
    if args.command == "validate":
        sweep = _validated_sweep(args)
        write_json(
            args.report,
            sweep.validation_report,
            overwrite=args.overwrite,
        )
        print(
            f"VALID retrieval sweep: {args.model}/{args.language}, "
            f"seeds={list(args.accepted_seeds)}"
        )
        print(f"Validation report: {args.report}")
        return 0
    if args.command == "consensus":
        sweep = _validated_sweep(args)
        payload = materialize_consensus_map(
            sweep,
            canonical_carrier_path=args.canonical_carrier,
        )
        write_json(
            args.validation_report,
            sweep.validation_report,
            overwrite=args.overwrite,
        )
        write_json(args.output, payload, overwrite=args.overwrite)
        print(
            f"Materialized {len(payload['mappings'])} tasks for "
            f"{args.model}/{args.language}; "
            f"empty consensus={payload['metadata']['empty_prompts']}"
        )
        print(f"Consensus map: {args.output}")
        print(f"Validation report: {args.validation_report}")
        return 0
    if args.command == "merge":
        payload = merge_consensus_parts(
            args.part,
            canonical_carrier_path=args.canonical_carrier,
            model=args.model,
            language=args.language,
        )
        write_json(args.output, payload, overwrite=args.overwrite)
        print(
            f"Merged {len(payload['mappings'])} tasks for "
            f"{args.model}/{args.language}; "
            f"empty consensus={payload['metadata']['empty_prompts']}"
        )
        print(f"Full consensus map: {args.output}")
        return 0
    if args.command == "norules":
        payload = build_norules_map(args.canonical_carrier)
        write_json(args.output, payload, overwrite=args.overwrite)
        print(f"Materialized no-rules map with {len(payload['mappings'])} tasks")
        print(f"No-rules map: {args.output}")
        return 0
    if args.command == "carrier":
        payload = build_population_carrier(args.source)
        write_json(args.output, payload, overwrite=args.overwrite)
        print(
            f"Materialized canonical carrier with {len(payload['mappings'])} tasks "
            f"({payload['metadata']['languages']})"
        )
        print(f"Population carrier: {args.output}")
        return 0
    raise AssertionError(f"unhandled command {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return _run(args)
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
