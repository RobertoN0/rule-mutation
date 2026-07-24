#!/usr/bin/env python3
"""Validate two-stage population screening and materialize screened maps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.population_screening import (  # noqa: E402
    SCREENING_CONDITIONS,
    SCREENING_MODELS,
    analyze_screening_round,
    combine_screened_language_maps,
    filter_screened_map,
    filter_second_round_candidates,
    finalize_screening,
    load_screening_run,
)
from src.retrieval.consensus import (  # noqa: E402
    load_json_object,
    write_json,
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


def _add_run_and_map_arguments(parser: argparse.ArgumentParser) -> None:
    for model in SCREENING_MODELS:
        for condition in SCREENING_CONDITIONS:
            prefix = f"--{model}-{condition}"
            parser.add_argument(
                f"{prefix}-run",
                type=Path,
                required=True,
            )
            parser.add_argument(
                f"{prefix}-map",
                type=Path,
                required=True,
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    round_parser = subparsers.add_parser(
        "round",
        help="Validate four runs and classify one screening seed block.",
    )
    round_parser.add_argument(
        "--stage",
        choices=("first", "second"),
        required=True,
    )
    round_parser.add_argument(
        "--language",
        choices=("python", "java"),
        required=True,
    )
    round_parser.add_argument("--seeds", type=parse_seed_list, required=True)
    round_parser.add_argument(
        "--prompt-contract-sha256",
        help="Expected prompt contract; defaults to the active fixed contract.",
    )
    _add_run_and_map_arguments(round_parser)
    round_parser.add_argument("--output", type=Path, required=True)
    round_parser.add_argument("--overwrite", action="store_true")

    candidates = subparsers.add_parser(
        "candidates",
        help="Create second-round maps from a first-round report.",
    )
    candidates.add_argument("--first-round-report", type=Path, required=True)
    candidates.add_argument("--map", type=Path, action="append", required=True)
    candidates.add_argument("--output-dir", type=Path, required=True)
    candidates.add_argument("--overwrite", action="store_true")

    finalize = subparsers.add_parser(
        "finalize",
        help="Finalize both rounds and create retained-population maps.",
    )
    finalize.add_argument("--first-round-report", type=Path, required=True)
    finalize.add_argument("--second-round-report", type=Path, required=True)
    finalize.add_argument("--manifest", type=Path, required=True)
    finalize.add_argument("--map", type=Path, action="append", required=True)
    finalize.add_argument("--output-dir", type=Path, required=True)
    finalize.add_argument("--overwrite", action="store_true")

    combine = subparsers.add_parser(
        "combine",
        help="Combine final Python and Java maps for one model or no-rules.",
    )
    combine.add_argument("--python-map", type=Path, required=True)
    combine.add_argument("--java-map", type=Path, required=True)
    combine.add_argument(
        "--model",
        choices=(*SCREENING_MODELS, "norules"),
        required=True,
    )
    combine.add_argument("--output", type=Path, required=True)
    combine.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def _round(args: argparse.Namespace) -> int:
    runs = {}
    for model in SCREENING_MODELS:
        for condition in SCREENING_CONDITIONS:
            stem = f"{model}_{condition}"
            runs[(model, condition)] = load_screening_run(
                getattr(args, f"{stem}_run"),
                source_map_path=getattr(args, f"{stem}_map"),
                model=model,
                language=args.language,
                condition=condition,
                expected_seeds=args.seeds,
                expected_prompt_contract=args.prompt_contract_sha256,
            )
    report = analyze_screening_round(runs, stage=args.stage)
    write_json(args.output, report, overwrite=args.overwrite)
    print(
        f"VALID {args.stage} screening round: {args.language}, "
        f"tasks={report['tasks']}, seeds={list(args.seeds)}"
    )
    for name, count in report["classification_counts"].items():
        print(f"  {name}: {count}")
    print(f"Screening report: {args.output}")
    return 0


def _candidates(args: argparse.Namespace) -> int:
    report = load_json_object(args.first_round_report)
    for path in args.map:
        payload = load_json_object(path)
        selected = filter_second_round_candidates(
            payload,
            first_round=report,
            report_path=args.first_round_report,
        )
        output = args.output_dir / path.name
        write_json(output, selected, overwrite=args.overwrite)
        print(
            f"{path.name}: {len(payload['mappings'])} -> "
            f"{len(selected['mappings'])} second-round tasks"
        )
    print(f"Second-round maps: {args.output_dir}")
    return 0


def _finalize(args: argparse.Namespace) -> int:
    first = load_json_object(args.first_round_report)
    second = load_json_object(args.second_round_report)
    manifest = finalize_screening(first, second)
    write_json(args.manifest, manifest, overwrite=args.overwrite)
    for path in args.map:
        payload = load_json_object(path)
        screened = filter_screened_map(
            payload,
            screening_manifest=manifest,
            manifest_path=args.manifest,
        )
        output = args.output_dir / path.name
        write_json(output, screened, overwrite=args.overwrite)
        print(
            f"{path.name}: {len(payload['mappings'])} -> "
            f"{len(screened['mappings'])} retained tasks"
        )
    print(
        f"Excluded never-vulnerable tasks: "
        f"{manifest['excluded_never_vulnerable_total']}"
    )
    print(f"Screening manifest: {args.manifest}")
    print(f"Screened maps: {args.output_dir}")
    return 0


def _combine(args: argparse.Namespace) -> int:
    payload = combine_screened_language_maps(
        load_json_object(args.python_map),
        load_json_object(args.java_map),
        model=args.model,
    )
    write_json(args.output, payload, overwrite=args.overwrite)
    print(
        f"Combined {payload['metadata']['languages']['python']} Python and "
        f"{payload['metadata']['languages']['java']} Java tasks"
    )
    print(f"Combined map: {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "round":
            return _round(args)
        if args.command == "candidates":
            return _candidates(args)
        if args.command == "finalize":
            return _finalize(args)
        if args.command == "combine":
            return _combine(args)
        raise AssertionError(f"unhandled command {args.command}")
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
