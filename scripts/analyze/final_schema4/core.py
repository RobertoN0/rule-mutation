"""Data loading, health validation, and metrics for schema-4 repair runs.

Design constraints:

* A user-confirmed CSV manifest is the only source of final-run membership.
* Schema 2/3 data are never upgraded or mixed into this analysis.
* ``iterations.jsonl`` contains proposals; only rows with
  ``budget_consumed is True`` and a numeric ``f1`` are evaluated candidates.
* Headline best-f1 is best-ever evaluated, with the origin (f1=0) as a floor.
  The final archive is reported separately because a stagnation restart can
  wipe an earlier best candidate from the surviving front.
* Prompt-level repair is read directly from every evaluated
  ``intermediate/{ea,rand}_iterNNNN.jsonl`` file. It does not depend on the
  schema-2 single-rule ``rule_id`` applicability model.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Iterator, Sequence

import labels
import stats as stats_helpers

PENDING = "[PENDING: final runs]"
_EXPECTED_SCHEMA = 4
_VALID_OPTIMIZERS = {"ea", "random_search"}
_VALID_LANGUAGES = {"python", "java"}
_VALID_MODEL_FAMILIES = {"qwen", "llama"}
_MODEL_ID_BY_FAMILY = {
    "qwen": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "llama": "meta-llama/Llama-3.3-70B-Instruct",
}
_MODEL_FAMILY_BY_ID = {model_id: family for family, model_id in _MODEL_ID_BY_FAMILY.items()}
_CRASH_RE = re.compile(
    r"(traceback \(most recent call last\)|rate.?limit|\b429\b|\b413\b|"
    r"identity retry limit exceeded|killed|out of memory|cuda out of memory|exception:)",
    re.IGNORECASE,
)
_GRACEFUL_RE = re.compile(
    r"(graceful stop|pre-timeout|finalizing from|run complete|results saved)",
    re.IGNORECASE,
)
_INFLIGHT_DISCARD_RE = re.compile(
    r"(?:pre-timeout during iteration \d+.*discarding in-flight|"
    r"pre-timeout mid-eval.*stopping after \d+ iterations)",
    re.IGNORECASE,
)


def _normalise_optimizer(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"random", "rand", "random_baseline"}:
        return "random_search"
    return raw


def _normalise_language(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return {"py": "python", "ja": "java"}.get(raw, raw)


def _normalise_model_family(value: Any) -> str:
    """Normalize a manifest family or one of the two exact final model IDs.

    Model IDs deliberately use exact matching. Substring matching would let an
    unintended checkpoint (or an ablation with a similar name) enter a final
    model stratum silently.
    """
    raw = str(value or "").strip()
    family = raw.lower().replace("_", "-")
    if family in _VALID_MODEL_FAMILIES:
        return family
    return _MODEL_FAMILY_BY_ID.get(raw, family)


def _model_family_from_config(value: Any) -> str:
    """Return the family only for an exact supported run-config model ID."""
    return _MODEL_FAMILY_BY_ID.get(str(value or "").strip(), "")


def _normalise_seed(value: Any) -> str:
    raw = str(value if value is not None else "").strip()
    try:
        numeric = float(raw)
    except ValueError:
        return raw
    if numeric.is_integer():
        return str(int(numeric))
    return raw


def _seed_sort_key(value: str) -> tuple[int, int | str]:
    seed = _normalise_seed(value)
    return (0, int(seed)) if seed.isdigit() else (1, seed)


def parse_seed_spec(raw: str) -> list[str]:
    """Parse an explicit comma/range seed specification.

    Examples: ``"1-10"`` and ``"1,3,7-9"``.  Seed order is retained and
    duplicates are removed so the generated manifest has exactly one row per
    matrix cell.
    """
    tokens = [token.strip() for token in str(raw).split(",") if token.strip()]
    if not tokens:
        raise ValueError("expected seed list/range, for example 1-10")

    seeds: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if range_match:
            start, stop = (int(value) for value in range_match.groups())
            if start > stop:
                raise ValueError(f"descending seed range is not supported: {token!r}")
            values = range(start, stop + 1)
        elif re.fullmatch(r"\d+", token):
            values = (int(token),)
        else:
            raise ValueError(f"invalid seed token: {token!r}")
        for value in values:
            seed = str(value)
            if seed not in seen:
                seen.add(seed)
                seeds.append(seed)
    return seeds


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _quantile(values: Sequence[float], q: float) -> float:
    """Linear quantile without requiring pandas/numpy in the loader layer."""
    xs = sorted(float(x) for x in values)
    if not xs:
        return math.nan
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _median_iqr(values: Sequence[float]) -> tuple[float, float, float]:
    if not values:
        return (math.nan, math.nan, math.nan)
    return (median(values), _quantile(values, 0.25), _quantile(values, 0.75))


def _seed_bootstrap_ci(values: Sequence[float]) -> tuple[float, float, float]:
    """Mean plus a seed-cluster bootstrap CI; one seed cannot identify precision."""
    point, low, high = stats_helpers.bootstrap_ci(values, seed=0)
    if len(values) < 2:
        return (point, math.nan, math.nan)
    return (point, low, high)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


@dataclass
class JsonlRead:
    records: list[dict[str, Any]]
    errors: list[str]


@dataclass
class SemgrepJsonlSummary:
    record_count: int = 0
    missing_error_key: int = 0
    nonnull_error: int = 0
    null_error: int = 0
    errors: list[str] = field(default_factory=list)


def _read_jsonl(path: Path) -> JsonlRead:
    """Read JSONL and retain parse errors for health reporting.

    Analysis never silently discards a truncated final line. A malformed line
    is returned as an explicit error and makes a required artifact unhealthy.
    """
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{path.name}:{line_number}: {exc.msg}")
                    continue
                if not isinstance(value, dict):
                    errors.append(f"{path.name}:{line_number}: expected JSON object")
                    continue
                records.append(value)
    except OSError as exc:
        errors.append(f"{path}: {exc}")
    return JsonlRead(records, errors)


def _summarise_semgrep_jsonl(path: Path) -> SemgrepJsonlSummary:
    """Audit a potentially multi-gigabyte ledger without retaining its records."""
    summary = SemgrepJsonlSummary()
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    summary.errors.append(f"{path.name}:{line_number}: {exc.msg}")
                    continue
                if not isinstance(value, dict):
                    summary.errors.append(
                        f"{path.name}:{line_number}: expected JSON object"
                    )
                    continue
                summary.record_count += 1
                if "error" not in value:
                    summary.missing_error_key += 1
                elif value.get("error") is None:
                    summary.null_error += 1
                else:
                    summary.nonnull_error += 1
    except OSError as exc:
        summary.errors.append(f"{path}: {exc}")
    return summary


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Strict streaming JSONL reader used after a run passes health checks."""
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            yield value


def _resolve_path(raw: str, *, manifest_dir: Path, repo_root: Path) -> Path | None:
    if not raw.strip():
        return None
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    repo_candidate = repo_root / candidate
    manifest_candidate = manifest_dir / candidate
    if repo_candidate.exists() or not manifest_candidate.exists():
        return repo_candidate
    return manifest_candidate


@dataclass
class ManifestEntry:
    language: str
    optimizer: str
    seed: str
    job_id: str = ""
    run_dir: Path | None = None
    log_path: Path | None = None
    model: str = ""
    resolution_issue: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            _normalise_model_family(self.model),
            self.language,
            self.optimizer,
            self.seed,
        )


def expected_manifest_entries(
    run_root: Path,
    *,
    models: Sequence[str] = ("qwen", "llama"),
    languages: Sequence[str] = ("python", "java"),
    optimizers: Sequence[str] = ("ea", "random_search"),
    seeds: Sequence[str] = tuple(str(seed) for seed in range(1, 11)),
) -> list[ManifestEntry]:
    """Build the explicit model × language × optimizer × seed matrix.

    ``run_root`` may be absolute or repository-relative.  Each manifest path is
    a seed container:

    ``<root>/<model>/<language>/<optimizer>/seed<seed>``

    A container may itself be the run directory, or may contain exactly one
    generated ``job<ID>_*`` child.  The latter matches the current SLURM
    launcher's naming policy when ``OUTPUT_BASE`` is set to the seed container.
    """
    normalised_models = [_normalise_model_family(value) for value in models]
    normalised_languages = [_normalise_language(value) for value in languages]
    normalised_optimizers = [_normalise_optimizer(value) for value in optimizers]
    normalised_seeds = [_normalise_seed(value) for value in seeds]

    invalid_models = sorted(set(normalised_models) - _VALID_MODEL_FAMILIES)
    invalid_languages = sorted(set(normalised_languages) - _VALID_LANGUAGES)
    invalid_optimizers = sorted(set(normalised_optimizers) - _VALID_OPTIMIZERS)
    if not normalised_models:
        raise ValueError("expected models cannot be empty")
    if invalid_models:
        raise ValueError(f"unsupported expected models: {invalid_models}")
    if invalid_languages:
        raise ValueError(f"unsupported expected languages: {invalid_languages}")
    if invalid_optimizers:
        raise ValueError(f"unsupported expected optimizers: {invalid_optimizers}")
    if any(not seed for seed in normalised_seeds):
        raise ValueError("expected seeds cannot be blank")
    if len(set(normalised_models)) != len(normalised_models):
        raise ValueError("expected models contain duplicates")
    if len(set(normalised_languages)) != len(normalised_languages):
        raise ValueError("expected languages contain duplicates")
    if len(set(normalised_optimizers)) != len(normalised_optimizers):
        raise ValueError("expected optimizers contain duplicates")
    if len(set(normalised_seeds)) != len(normalised_seeds):
        raise ValueError("expected seeds contain duplicates")

    root = Path(run_root)
    return [
        ManifestEntry(
            language=language,
            optimizer=optimizer,
            seed=seed,
            run_dir=root / model / language / optimizer / f"seed{seed}",
            model=model,
        )
        for model in normalised_models
        for language in normalised_languages
        for optimizer in normalised_optimizers
        for seed in normalised_seeds
    ]


def _resolve_seed_container(run_dir: Path) -> tuple[Path, str]:
    """Resolve a canonical seed container to its single completed run leaf."""
    if not run_dir.is_dir() or (run_dir / "run_config.json").is_file():
        return run_dir, ""
    matches = sorted({path.parent for path in run_dir.glob("*/run_config.json")})
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return (
            run_dir,
            "seed container resolved to multiple run dirs: "
            + ", ".join(str(path) for path in matches),
        )
    return run_dir, ""


def load_manifest(
    path: Path,
    *,
    repo_root: Path,
    results_roots: Sequence[Path] = (),
    logs_root: Path | None = None,
) -> list[ManifestEntry]:
    """Load and resolve the user-confirmed final-run manifest.

    Required CSV columns are ``model,language,optimizer,seed``. A row must
    provide either ``run_dir`` or ``job_id``. Optional ``log_path`` overrides
    log discovery. Job IDs are resolved only inside the supplied results roots.
    """
    path = Path(path)
    entries: list[ManifestEntry] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"model", "language", "optimizer", "seed"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"manifest missing columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, 2):
            model = _normalise_model_family(row.get("model"))
            language = _normalise_language(row.get("language"))
            optimizer = _normalise_optimizer(row.get("optimizer"))
            seed = _normalise_seed(row.get("seed"))
            job_id = str(row.get("job_id") or "").strip().removeprefix("job")
            run_dir = _resolve_path(
                str(row.get("run_dir") or ""),
                manifest_dir=path.parent,
                repo_root=repo_root,
            )
            log_path = _resolve_path(
                str(row.get("log_path") or ""),
                manifest_dir=path.parent,
                repo_root=repo_root,
            )
            resolution_issue = ""
            if run_dir is None and job_id:
                matches: list[Path] = []
                for root in results_roots:
                    if root.exists():
                        for config_path in root.rglob("run_config.json"):
                            recorded_job = ""
                            try:
                                recorded_job = (
                                    str(_read_json(config_path).get("slurm_job_id") or "")
                                    .strip()
                                    .removeprefix("job")
                                )
                            except (OSError, ValueError, json.JSONDecodeError):
                                pass
                            if (
                                config_path.parent.name.startswith(f"job{job_id}_")
                                or recorded_job == job_id
                            ):
                                matches.append(config_path.parent)
                matches = sorted(set(matches))
                if len(matches) == 1:
                    run_dir = matches[0]
                elif not matches:
                    resolution_issue = f"job{job_id} not found under configured results roots"
                else:
                    resolution_issue = f"job{job_id} resolved to multiple run dirs: " + ", ".join(
                        str(p) for p in matches
                    )
            elif run_dir is not None:
                run_dir, container_issue = _resolve_seed_container(run_dir)
                if container_issue:
                    resolution_issue = container_issue
            if log_path is None and job_id and logs_root and logs_root.exists():
                log_matches = sorted(logs_root.glob(f"{job_id}_*.out"))
                if len(log_matches) == 1:
                    log_path = log_matches[0]
                elif len(log_matches) > 1:
                    resolution_issue = (
                        (resolution_issue + "; ") if resolution_issue else ""
                    ) + f"multiple SLURM logs for job{job_id}"
            if run_dir is None and not job_id:
                resolution_issue = (
                    (resolution_issue + "; ") if resolution_issue else ""
                ) + f"manifest line {line_number} has neither run_dir nor job_id"
            entries.append(
                ManifestEntry(
                    language=language,
                    optimizer=optimizer,
                    seed=seed,
                    job_id=job_id,
                    run_dir=run_dir,
                    log_path=log_path,
                    model=model,
                    resolution_issue=resolution_issue,
                )
            )
    if not entries:
        raise ValueError("manifest contains no data rows")
    return entries


@dataclass
class RunHealth:
    entry: ManifestEntry
    status: str = "unhealthy"
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: Any = None
    git_sha: str = ""
    slurm_job_id: str = ""
    actual_model_family: str = ""
    actual_language: str = ""
    actual_optimizer: str = ""
    actual_seed: str = ""
    backend: str = ""
    model: str = ""
    temperature: float | None = None
    rules_map: str = ""
    n_cases: int | None = None
    max_iterations: int | None = None
    n_proposals: int = 0
    n_evaluated: int = 0
    n_identity: int = 0
    n_semgrep_clean: int = 0
    n_semgrep_error: int = 0
    n_baseline_records: int = 0
    n_archive_snapshots: int = 0
    stop_class: str = ""
    summary_path: Path | None = None
    final_snapshot_path: Path | None = None
    config: dict[str, Any] = field(default_factory=dict, repr=False)
    summary: dict[str, Any] = field(default_factory=dict, repr=False)
    iterations: list[dict[str, Any]] = field(default_factory=list, repr=False)
    baseline_ids: frozenset[str] = field(default_factory=frozenset, repr=False)
    baseline_weighted_by_id: dict[str, float] = field(default_factory=dict, repr=False)
    baseline_signature_by_id: dict[str, tuple[int, float, tuple[str, ...], str]] = field(
        default_factory=dict, repr=False
    )

    @property
    def path(self) -> Path | None:
        return self.entry.run_dir

    @property
    def key(self) -> tuple[str, str, str, str]:
        manifest_model = _normalise_model_family(self.entry.model)
        return (
            (
                manifest_model
                if manifest_model in _VALID_MODEL_FAMILIES
                else self.actual_model_family
            ),
            self.actual_language or self.entry.language,
            self.actual_optimizer or self.entry.optimizer,
            self.actual_seed or self.entry.seed,
        )

    @property
    def label(self) -> str:
        """Stable run label independent of directory naming."""
        model, language, optimizer, seed = self.key
        return f"{model}/{language}/{optimizer}/seed{seed}"

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"

    def add_issue(self, issue: str) -> None:
        if issue and issue not in self.issues:
            self.issues.append(issue)
        if self.status != "missing":
            self.status = "unhealthy"

    def finalise(self) -> None:
        if self.status != "missing":
            self.status = "healthy" if not self.issues else "unhealthy"


def _config_language(args: dict[str, Any]) -> tuple[str, str]:
    languages = args.get("languages")
    if isinstance(languages, str):
        values = [languages]
    elif isinstance(languages, list):
        values = languages
    else:
        return ("", "args.languages must be a one-element list")
    values = [_normalise_language(v) for v in values]
    if len(values) != 1:
        return ("", f"args.languages must contain exactly one language, got {values}")
    return (values[0], "")


def _expected_intermediate(run: RunHealth, iteration: int) -> Path:
    assert run.path is not None
    prefix = "ea" if run.actual_optimizer == "ea" else "rand"
    return run.path / "intermediate" / f"{prefix}_iter{iteration:04d}.jsonl"


def _inspect_single(
    entry: ManifestEntry,
    *,
    allow_missing_semgrep_debug: bool = False,
    rules_map_roots: Sequence[Path] = (),
) -> RunHealth:
    health = RunHealth(entry=entry)
    if entry.resolution_issue:
        health.add_issue(entry.resolution_issue)
    manifest_model = _normalise_model_family(entry.model)
    if entry.model and manifest_model not in _VALID_MODEL_FAMILIES:
        health.add_issue(f"manifest model is not supported: {entry.model!r}")
    if entry.language not in _VALID_LANGUAGES:
        health.add_issue(f"manifest language is not supported: {entry.language!r}")
    if entry.optimizer not in _VALID_OPTIMIZERS:
        health.add_issue(f"manifest optimizer is not supported: {entry.optimizer!r}")
    if not entry.seed:
        health.add_issue("manifest seed is blank")
    if entry.run_dir is None or not entry.run_dir.is_dir():
        health.status = "missing"
        health.add_issue(f"run directory missing: {entry.run_dir or '[unresolved]'}")
        return health

    config_path = entry.run_dir / "run_config.json"
    try:
        health.config = _read_json(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        health.add_issue(f"run_config.json unreadable: {exc}")
        health.finalise()
        return health

    config = health.config
    if config.get("_reconstructed") or str(config.get("timestamp") or "").startswith(
        "RECONSTRUCTED"
    ):
        health.add_issue(
            "run_config.json is reconstructed pre-completion provenance, not the "
            "writer-emitted final config"
        )
    args = config.get("args")
    if not isinstance(args, dict):
        health.add_issue("run_config.args missing or not an object")
        args = {}
    health.schema_version = config.get("schema_version")
    health.git_sha = str(config.get("git_sha") or "")
    health.slurm_job_id = str(config.get("slurm_job_id") or "")
    health.actual_optimizer = _normalise_optimizer(args.get("optimizer"))
    health.actual_seed = _normalise_seed(args.get("seed"))
    health.backend = str(args.get("backend") or "")
    health.model = str(args.get("model") or "")
    health.actual_model_family = _model_family_from_config(health.model)
    health.temperature = _number(args.get("temperature"))
    health.rules_map = str(args.get("rules_map") or "")
    health.actual_language, language_issue = _config_language(args)
    if language_issue:
        health.add_issue(language_issue)
    n_cases = args.get("n_cases")
    max_iterations = args.get("iterations")
    health.n_cases = (
        int(n_cases) if isinstance(n_cases, int) and not isinstance(n_cases, bool) else None
    )
    health.max_iterations = (
        int(max_iterations)
        if isinstance(max_iterations, int) and not isinstance(max_iterations, bool)
        else None
    )

    if health.schema_version != _EXPECTED_SCHEMA:
        health.add_issue(f"schema_version={health.schema_version!r}, expected 4")
    if args.get("objective_direction") != "minimize":
        health.add_issue(
            f"objective_direction={args.get('objective_direction')!r}, expected 'minimize'"
        )
    if health.actual_optimizer not in _VALID_OPTIMIZERS:
        health.add_issue(f"invalid args.optimizer={health.actual_optimizer!r}")
    if health.actual_language not in _VALID_LANGUAGES:
        health.add_issue(f"invalid args.languages={args.get('languages')!r}")
    if health.n_cases is None or health.n_cases <= 0:
        health.add_issue(f"invalid args.n_cases={n_cases!r}")
    if health.max_iterations is None or health.max_iterations <= 0:
        health.add_issue(f"invalid args.iterations={max_iterations!r}")
    if not health.git_sha:
        health.add_issue("git_sha missing")
    if not health.slurm_job_id:
        health.add_issue("slurm_job_id missing")
    if not health.backend:
        health.add_issue("args.backend missing")
    if not health.model:
        health.add_issue("args.model missing")
    elif not health.actual_model_family:
        supported_ids = ", ".join(
            repr(_MODEL_ID_BY_FAMILY[family]) for family in sorted(_MODEL_ID_BY_FAMILY)
        )
        health.add_issue(
            f"unsupported args.model={health.model!r}; expected exact model ID "
            f"in {{{supported_ids}}}"
        )
    if health.temperature is None:
        health.add_issue(f"invalid args.temperature={args.get('temperature')!r}")
    if not health.rules_map:
        health.add_issue("args.rules_map missing")
    if args.get("selection") not in {"first", "random"}:
        health.add_issue(f"invalid args.selection={args.get('selection')!r}")
    if health.actual_optimizer == "ea" and args.get("ea_move") not in {
        "local",
        "random_builder",
    }:
        health.add_issue(f"invalid args.ea_move={args.get('ea_move')!r}")
    if not isinstance(args.get("mutators"), list) or not args.get("mutators"):
        health.add_issue("args.mutators missing or empty")
    if args.get("enable_validation") is not True:
        health.add_issue("args.enable_validation must be true for real schema-4 runs")
    if not isinstance(args.get("enable_eval_cache"), bool):
        health.add_issue("args.enable_eval_cache must be boolean")
    elif args.get("enable_eval_cache") is True and health.temperature != 0.0:
        health.add_issue(
            "args.enable_eval_cache=true requires temperature=0 for deterministic reuse"
        )
    if health.actual_language and health.actual_language != entry.language:
        health.add_issue(
            f"manifest/config language mismatch: {entry.language} != {health.actual_language}"
        )
    if (
        manifest_model
        and health.actual_model_family
        and manifest_model != health.actual_model_family
    ):
        health.add_issue(
            f"manifest/config model mismatch: {manifest_model} != {health.actual_model_family}"
        )
    if health.actual_optimizer and health.actual_optimizer != entry.optimizer:
        health.add_issue(
            f"manifest/config optimizer mismatch: {entry.optimizer} != {health.actual_optimizer}"
        )
    if health.actual_seed and health.actual_seed != entry.seed:
        health.add_issue(f"manifest/config seed mismatch: {entry.seed} != {health.actual_seed}")
    if entry.job_id and health.slurm_job_id and entry.job_id != health.slurm_job_id:
        health.add_issue(f"manifest/config job mismatch: {entry.job_id} != {health.slurm_job_id}")

    rules_map_ids: set[str] | None = None
    if health.rules_map:
        recorded_map = Path(health.rules_map)
        map_candidates = (
            [recorded_map] if recorded_map.is_absolute() else [entry.run_dir / recorded_map]
        )
        for ancestor in entry.run_dir.parents:
            map_candidates.append(ancestor / "rule_maps" / recorded_map.name)
        map_candidates.extend(Path(root) / recorded_map.name for root in rules_map_roots)
        local_map = next((candidate for candidate in map_candidates if candidate.is_file()), None)
        if local_map is None:
            health.warnings.append(
                f"could not verify rules-map content locally: {health.rules_map}"
            )
        else:
            try:
                map_payload = _read_json(local_map)
                mappings = map_payload.get("mappings")
                if not isinstance(mappings, list):
                    health.add_issue(f"rules map has no mappings list: {local_map}")
                else:
                    malformed = sum(not isinstance(value, dict) for value in mappings)
                    if malformed:
                        health.add_issue(
                            f"rules-map mappings contains {malformed} non-object entries"
                        )
                    language_mappings = [
                        value
                        for value in mappings
                        if isinstance(value, dict)
                        and _normalise_language(value.get("language")) == health.actual_language
                    ]
                    if health.n_cases is not None and len(language_mappings) != health.n_cases:
                        health.add_issue(
                            f"rules-map {health.actual_language} mappings="
                            f"{len(language_mappings)} != n_cases={health.n_cases}; "
                            "final full-population runs must evaluate the entire language map"
                        )
                    if not language_mappings:
                        health.add_issue(
                            f"rules map has no entries for run language={health.actual_language}"
                        )
                    mapped_ids = [
                        str(value["index"])
                        for value in language_mappings
                        if value.get("index") is not None
                    ]
                    if len(mapped_ids) != len(language_mappings):
                        health.add_issue("rules-map language entries have missing index values")
                    elif len(set(mapped_ids)) != len(mapped_ids):
                        health.add_issue("rules-map language entries have duplicate index values")
                    else:
                        rules_map_ids = set(mapped_ids)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                health.add_issue(f"rules map unreadable: {exc}")

    summaries = sorted(entry.run_dir.glob("hillclimb_summary_*.json"))
    if len(summaries) != 1:
        health.add_issue(f"expected exactly one hillclimb summary, found {len(summaries)}")
    if summaries:
        health.summary_path = summaries[-1]
        try:
            health.summary = _read_json(health.summary_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            health.add_issue(f"summary unreadable: {exc}")

    log_path = entry.log_path
    if log_path is None:
        local_log = entry.run_dir / "run.log"
        if local_log.is_file():
            log_path = local_log
    log_text = ""
    if log_path and log_path.is_file():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")[-200_000:]
        except OSError as exc:
            health.add_issue(f"run log unreadable: {exc}")
    graceful_inflight_discard = bool(_INFLIGHT_DISCARD_RE.search(log_text))

    iterations_path = entry.run_dir / "iterations.jsonl"
    if not iterations_path.is_file() or iterations_path.stat().st_size == 0:
        health.add_issue("iterations.jsonl missing or empty")
    else:
        parsed = _read_jsonl(iterations_path)
        health.iterations = parsed.records
        for error in parsed.errors:
            health.add_issue(f"iterations parse error: {error}")
    health.n_proposals = len(health.iterations)
    expected_phases = (
        {"init", "injection", "ea", "restart"} if health.actual_optimizer == "ea" else {"random"}
    )
    proposal_attempts: list[int] = []
    attempt_slots: dict[int, list[int]] = defaultdict(list)
    for row_number, row in enumerate(health.iterations, 1):
        prefix = f"iterations row {row_number}"
        iteration = row.get("iter")
        attempt = row.get("attempt")
        attempt_in_iter = row.get("attempt_in_iter")
        budget_consumed = row.get("budget_consumed")
        identity = row.get("mutation_identity")
        if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration <= 0:
            health.add_issue(f"{prefix}: invalid iter={iteration!r}")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
            health.add_issue(f"{prefix}: invalid attempt={attempt!r}")
        else:
            proposal_attempts.append(attempt)
        if (
            not isinstance(attempt_in_iter, int)
            or isinstance(attempt_in_iter, bool)
            or attempt_in_iter <= 0
        ):
            health.add_issue(f"{prefix}: invalid attempt_in_iter={attempt_in_iter!r}")
        elif isinstance(iteration, int) and not isinstance(iteration, bool):
            attempt_slots[iteration].append(attempt_in_iter)
        if not isinstance(budget_consumed, bool):
            health.add_issue(f"{prefix}: budget_consumed must be boolean")
        if not isinstance(identity, bool):
            health.add_issue(f"{prefix}: mutation_identity must be boolean")
        if not isinstance(row.get("chromosome_id"), str) or not row.get("chromosome_id"):
            health.add_issue(f"{prefix}: chromosome_id missing")
        if row.get("strategy") != health.actual_optimizer:
            health.add_issue(
                f"{prefix}: strategy={row.get('strategy')!r} "
                f"!= optimizer={health.actual_optimizer!r}"
            )
        if row.get("phase") not in expected_phases:
            health.add_issue(
                f"{prefix}: phase={row.get('phase')!r} not in {sorted(expected_phases)}"
            )
        requested = row.get("n_requested_changes")
        attempted = row.get("n_attempted_changes")
        effective = row.get("n_effective_changes")
        counts = (requested, attempted, effective)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts
        ):
            health.add_issue(f"{prefix}: invalid requested/attempted/effective counts={counts!r}")
        elif not requested >= attempted >= effective:
            health.add_issue(
                f"{prefix}: requested/attempted/effective ordering violated: "
                f"{requested}/{attempted}/{effective}"
            )
        if row.get("objective_mode") != "conservative":
            health.add_issue(
                f"{prefix}: objective_mode={row.get('objective_mode')!r}, expected 'conservative'"
            )
        mutation_chain = row.get("mutation_chain")
        attempted_mutators = row.get("attempted_mutators")
        mutated_rule_ids = row.get("mutated_rule_ids")
        if (
            not isinstance(mutated_rule_ids, list)
            or any(
                not isinstance(value, str) or not value
                for value in (mutated_rule_ids if isinstance(mutated_rule_ids, list) else [])
            )
            or (
                isinstance(mutated_rule_ids, list)
                and len(set(mutated_rule_ids)) != len(mutated_rule_ids)
            )
        ):
            health.add_issue(f"{prefix}: mutated_rule_ids must be a unique list of strings")
            mutated_rule_ids = []
        if not isinstance(mutation_chain, list) or any(
            not isinstance(value, str) or not value for value in mutation_chain
        ):
            health.add_issue(f"{prefix}: mutation_chain must be a list of strings")
            mutation_chain = []
        if row.get("chain_length") != len(mutation_chain):
            health.add_issue(f"{prefix}: chain_length does not match mutation_chain")
        if not isinstance(attempted_mutators, list) or any(
            not isinstance(value, str) or not value for value in attempted_mutators
        ):
            health.add_issue(f"{prefix}: attempted_mutators must be a list of strings")
            attempted_mutators = []
        if not isinstance(row.get("accepted"), bool):
            health.add_issue(f"{prefix}: accepted must be boolean")
        if row.get("strategy") == "ea" and row.get("phase") == "ea":
            move_type = row.get("move_type")
            selection_meta = row.get("selection_meta")
            if (
                not isinstance(selection_meta, dict)
                or _number(selection_meta.get("parent_f1")) is None
            ):
                health.add_issue(f"{prefix}: local-EA selection_meta.parent_f1 is non-numeric")
            if args.get("ea_move") == "random_builder":
                if move_type != "random_builder" or row.get("rule_id") is not None:
                    health.add_issue(f"{prefix}: invalid random-builder EA move record")
            else:
                if move_type not in {"mutate", "order", "reverse"}:
                    health.add_issue(f"{prefix}: invalid local-EA move_type={move_type!r}")
                if not isinstance(row.get("rule_id"), str) or not row.get("rule_id"):
                    health.add_issue(f"{prefix}: local-EA rule_id missing")
                if move_type == "mutate" and (not mutation_chain or not attempted_mutators):
                    health.add_issue(f"{prefix}: local mutate move lacks mutator attribution")
        objective_values = tuple(_number(row.get(key)) for key in ("f1", "f2", "f3"))
        if budget_consumed is True:
            if identity is not False:
                health.add_issue(f"{prefix}: evaluated candidate is marked identity")
            if any(value is None for value in objective_values):
                health.add_issue(f"{prefix}: evaluated candidate has null/non-numeric objective")
            else:
                f2 = objective_values[1]
                f3 = objective_values[2]
                fidelity = _number(row.get("rule_fidelity"))
                parsimony = _number(row.get("parsimony"))
                if not 0.0 <= f2 <= 1.0:
                    health.add_issue(f"{prefix}: f2 rule fidelity is outside [0,1]")
                if fidelity is None or not math.isclose(f2, fidelity, rel_tol=1e-9, abs_tol=1e-6):
                    health.add_issue(f"{prefix}: f2 does not match rule_fidelity")
                if (
                    parsimony is None
                    or parsimony < 0
                    or not math.isclose(f3, -parsimony, rel_tol=1e-9, abs_tol=1e-6)
                ):
                    health.add_issue(f"{prefix}: f3 does not equal -parsimony")
                elif not math.isclose(
                    parsimony,
                    float(len(mutated_rule_ids)),
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                ):
                    health.add_issue(f"{prefix}: parsimony does not equal mutated-rule count")
                if not isinstance(row.get("f1_advance"), bool):
                    health.add_issue(f"{prefix}: f1_advance must be boolean")
        else:
            if identity is not True:
                health.add_issue(f"{prefix}: non-evaluated proposal is not an identity")
            if any(value is not None for value in objective_values):
                health.add_issue(f"{prefix}: identity proposal has a non-null objective")
    if proposal_attempts and (
        len(set(proposal_attempts)) != len(proposal_attempts)
        or proposal_attempts != sorted(proposal_attempts)
    ):
        health.add_issue("proposal attempt IDs are not unique and strictly increasing")
    for iteration, slots in sorted(attempt_slots.items()):
        if sorted(slots) != list(range(1, len(slots) + 1)):
            health.add_issue(
                f"attempt_in_iter values for iter={iteration} are not contiguous 1..{len(slots)}"
            )
    evaluated = [
        row
        for row in health.iterations
        if row.get("budget_consumed") is True and _number(row.get("f1")) is not None
    ]
    health.n_evaluated = len(evaluated)
    health.n_identity = sum(1 for row in health.iterations if row.get("mutation_identity") is True)
    evaluated_ids = [row.get("iter") for row in evaluated]
    if not evaluated:
        health.add_issue("no evaluated iteration records")
    elif (
        any(not isinstance(value, int) or isinstance(value, bool) for value in evaluated_ids)
        or len(set(evaluated_ids)) != len(evaluated_ids)
        or evaluated_ids != list(range(1, len(evaluated_ids) + 1))
    ):
        health.add_issue(
            f"evaluated iter IDs are not ordered unique contiguous 1..{len(evaluated_ids)}"
        )
    if health.max_iterations is not None and health.n_evaluated > health.max_iterations:
        health.add_issue(
            f"evaluated={health.n_evaluated} exceeds configured iterations={health.max_iterations}"
        )
    if health.summary:
        summary_n = health.summary.get("num_iterations_run")
        if summary_n != health.n_evaluated:
            health.add_issue(
                f"summary num_iterations_run={summary_n!r} != evaluated={health.n_evaluated}"
            )
        total_time = _number(health.summary.get("total_time_seconds"))
        if total_time is None or total_time < 0:
            health.add_issue("summary total_time_seconds is missing/invalid")
        original_fitness = _number(health.summary.get("original_fitness"))
        best_fitness = _number(health.summary.get("best_fitness"))
        improvement = _number(health.summary.get("improvement"))
        if original_fitness is None or best_fitness is None or improvement is None:
            health.add_issue("summary original/best/improvement fitness is missing/invalid")
        elif not math.isclose(
            improvement,
            best_fitness - original_fitness,
            rel_tol=1e-9,
            abs_tol=1e-6,
        ):
            health.add_issue("summary improvement does not equal best_fitness-original_fitness")
        if original_fitness is not None and best_fitness is not None:
            recorded_best_f1 = max(
                [0.0]
                + [
                    value
                    for row in evaluated
                    for value in [_number(row.get("f1"))]
                    if value is not None
                ]
            )
            if not math.isclose(
                original_fitness - best_fitness,
                recorded_best_f1,
                rel_tol=1e-9,
                abs_tol=1e-6,
            ):
                health.add_issue("summary original-best fitness does not match best recorded f1")
        if health.summary.get("llm_model") != health.model:
            health.add_issue(
                f"summary llm_model={health.summary.get('llm_model')!r} "
                f"!= args.model={health.model!r}"
            )
        if health.summary.get("llm_provider") == "MockProvider":
            health.add_issue("summary identifies a dry-run MockProvider")
        if health.summary.get("max_iterations") != health.max_iterations:
            health.add_issue("summary max_iterations disagrees with run config")
        if health.summary.get("mutators") != args.get("mutators"):
            health.add_issue("summary mutators disagree with run config")
        for key in (
            "total_llm_calls",
            "total_input_tokens",
            "total_output_tokens",
        ):
            value = health.summary.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                health.add_issue(f"summary {key} is missing/invalid")
        cache_stats = health.summary.get("eval_cache_stats")
        if not isinstance(cache_stats, dict):
            health.add_issue("summary eval_cache_stats object is missing")
        else:
            if cache_stats.get("enabled") is not args.get("enable_eval_cache"):
                health.add_issue("summary eval_cache_stats.enabled disagrees with run config")
            for key in ("hits", "misses", "total_entries"):
                value = cache_stats.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    health.add_issue(f"summary eval_cache_stats.{key} is missing/invalid")
        pool_stats = health.summary.get("pool_arm_stats")
        if not isinstance(pool_stats, dict):
            health.add_issue("summary pool_arm_stats object is missing")
        elif pool_stats.get("strategy") != health.actual_optimizer:
            health.add_issue("summary pool_arm_stats.strategy disagrees with optimizer")
        elif health.actual_optimizer == "ea":
            restart_counts = pool_stats.get("restart_reason_counts")
            if not isinstance(restart_counts, dict) or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in (restart_counts.values() if isinstance(restart_counts, dict) else [])
            ):
                health.add_issue("summary restart_reason_counts object is missing/invalid")

        cumulative_keys = (
            "llm_calls_total",
            "input_tokens_total",
            "output_tokens_total",
        )
        previous = {key: -1 for key in cumulative_keys}
        for row_number, row in enumerate(health.iterations, 1):
            for key in cumulative_keys:
                value = row.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    health.add_issue(f"iterations row {row_number}: {key} is missing/invalid")
                    continue
                if value < previous[key]:
                    health.add_issue(f"iterations row {row_number}: {key} is not monotone")
                previous[key] = value
            reused = row.get("n_prompts_reused")
            rerun = row.get("n_prompts_rerun")
            if any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in (reused, rerun)
            ):
                health.add_issue(
                    f"iterations row {row_number}: prompt cache counters are missing/invalid"
                )
            elif row.get("budget_consumed") is True and health.n_cases is not None:
                if reused + rerun != health.n_cases:
                    health.add_issue(
                        f"iterations row {row_number}: reused+rerun prompts "
                        f"{reused + rerun} != n_cases={health.n_cases}"
                    )
            selection_meta = row.get("selection_meta")
            if health.actual_optimizer == "ea" and (
                not isinstance(selection_meta, dict)
                or not isinstance(selection_meta.get("restarts_this_iter"), list)
            ):
                health.add_issue(f"iterations row {row_number}: EA restart telemetry is missing")
        if health.iterations:
            last = health.iterations[-1]
            discarded_cost_mismatch = False
            for iteration_key, summary_key in zip(
                cumulative_keys,
                (
                    "total_llm_calls",
                    "total_input_tokens",
                    "total_output_tokens",
                ),
            ):
                iteration_value = last.get(iteration_key)
                summary_value = health.summary.get(summary_key)
                if iteration_value == summary_value:
                    continue
                if (
                    graceful_inflight_discard
                    and isinstance(iteration_value, int)
                    and not isinstance(iteration_value, bool)
                    and isinstance(summary_value, int)
                    and not isinstance(summary_value, bool)
                    and summary_value >= iteration_value
                ):
                    discarded_cost_mismatch = True
                else:
                    health.add_issue(f"final {iteration_key} disagrees with summary {summary_key}")
            if discarded_cost_mismatch:
                health.warnings.append(
                    "graceful pre-timeout discarded an in-flight candidate; summary "
                    "call/token totals include partial work with no iteration outcome"
                )

    if not log_path or not log_path.is_file():
        health.add_issue("run.log/log_path missing; stop classification is not auditable")

    baseline_path = entry.run_dir / "intermediate" / "baseline.jsonl"
    if not baseline_path.is_file() or baseline_path.stat().st_size == 0:
        health.add_issue("intermediate/baseline.jsonl missing or empty")
    else:
        baseline_read = _read_jsonl(baseline_path)
        health.n_baseline_records = len(baseline_read.records)
        for error in baseline_read.errors:
            health.add_issue(f"baseline parse error: {error}")
        baseline_ids = [
            str(row.get("test_case_id"))
            for row in baseline_read.records
            if row.get("test_case_id") is not None
        ]
        if len(baseline_ids) != len(baseline_read.records):
            health.add_issue("baseline has missing test_case_id values")
        if len(set(baseline_ids)) != len(baseline_ids):
            health.add_issue("baseline has duplicate test_case_id values")
        health.baseline_ids = frozenset(baseline_ids)
        for row in baseline_read.records:
            fitness = row.get("fitness")
            raw = fitness.get("raw_count") if isinstance(fitness, dict) else None
            weighted = _number(fitness.get("weighted_score")) if isinstance(fitness, dict) else None
            checks = fitness.get("check_ids") if isinstance(fitness, dict) else None
            test_case_id = row.get("test_case_id")
            cwe_id = row.get("cwe_id")
            if test_case_id is not None and weighted is not None:
                health.baseline_weighted_by_id[str(test_case_id)] = weighted
            if (
                test_case_id is not None
                and isinstance(raw, int)
                and not isinstance(raw, bool)
                and raw >= 0
                and weighted is not None
                and isinstance(checks, list)
                and all(isinstance(check_id, str) for check_id in checks)
                and isinstance(cwe_id, str)
            ):
                health.baseline_signature_by_id[str(test_case_id)] = (
                    raw,
                    weighted,
                    tuple(sorted(checks)),
                    cwe_id,
                )
        if set(health.baseline_signature_by_id) != set(baseline_ids):
            health.add_issue("baseline has incomplete raw/weighted/check/CWE signatures")
        if rules_map_ids is not None:
            unexpected_baseline_ids = sorted(set(baseline_ids) - rules_map_ids)
            if unexpected_baseline_ids:
                health.add_issue(
                    "baseline test_case_id values absent from rules map: "
                    f"{unexpected_baseline_ids[:5]}"
                )
        baseline_languages = {
            _normalise_language(row.get("language"))
            for row in baseline_read.records
            if row.get("language") is not None
        }
        if baseline_languages != {health.actual_language}:
            health.add_issue(
                f"baseline languages={sorted(baseline_languages)} "
                f"!= run language={health.actual_language}"
            )
        if health.n_cases is not None and health.n_baseline_records != health.n_cases:
            health.add_issue(
                f"baseline record count={health.n_baseline_records} != n_cases={health.n_cases}"
            )

    for row in evaluated:
        iteration = row.get("iter")
        if not isinstance(iteration, int):
            continue
        candidate_path = _expected_intermediate(health, iteration)
        if not candidate_path.is_file() or candidate_path.stat().st_size == 0:
            health.add_issue(f"missing evaluated intermediate: {candidate_path.name}")

    expected_mutation_iters = {
        int(row["iter"]) for row in evaluated if isinstance(row.get("iter"), int)
    }
    mutation_root = entry.run_dir / "mutated_rules"
    observed_mutation_iters: set[int] = set()
    if not mutation_root.is_dir():
        health.add_issue("mutated_rules directory missing")
    else:
        for iteration_dir in mutation_root.iterdir():
            if not iteration_dir.is_dir():
                continue
            match = re.fullmatch(r"iter(\d+)", iteration_dir.name)
            if not match:
                health.add_issue(f"invalid mutated-rules directory: {iteration_dir.name}")
                continue
            observed_mutation_iters.add(int(match.group(1)))
        extras = sorted(observed_mutation_iters - expected_mutation_iters)
        if extras:
            health.add_issue(f"mutated_rules contains non-evaluated iterations: {extras}")
    for row in evaluated:
        iteration = row.get("iter")
        if not isinstance(iteration, int):
            continue
        iteration_dir = mutation_root / f"iter{iteration:03d}"
        meta_path = iteration_dir / "meta.json"
        if not meta_path.is_file():
            health.add_issue(f"missing evaluated mutation metadata: {meta_path}")
            continue
        try:
            meta = _read_json(meta_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            health.add_issue(f"mutation metadata unreadable: {meta_path}: {exc}")
            continue
        for meta_key, row_key in (
            ("iteration", "iter"),
            ("chromosome_id", "chromosome_id"),
            ("move_type", "move_type"),
            ("changed_rule_id", "rule_id"),
            ("chain", "mutation_chain"),
            ("mutated_rule_ids", "mutated_rule_ids"),
            ("accepted", "accepted"),
        ):
            if meta.get(meta_key) != row.get(row_key):
                health.add_issue(f"{meta_path}: {meta_key} disagrees with iterations.{row_key}")
        mutated_rule_ids = row.get("mutated_rule_ids")
        gene_paths = meta.get("gene_paths")
        if not isinstance(gene_paths, dict) or set(gene_paths) != set(mutated_rule_ids or []):
            health.add_issue(f"{meta_path}: gene_paths keys do not match mutated_rule_ids")
        for rule_id in mutated_rule_ids if isinstance(mutated_rule_ids, list) else []:
            short = rule_id.replace("codeguard-", "cg-")
            if not (iteration_dir / f"{short}.md").is_file():
                health.add_issue(f"{meta_path}: mutated rule text missing for {rule_id!r}")

    snapshots_with_iters: list[tuple[int, Path]] = []
    for snapshot_path in (entry.run_dir / "archive_snapshots").glob("iter*.json"):
        match = re.fullmatch(r"iter(\d+)\.json", snapshot_path.name)
        if match:
            snapshots_with_iters.append((int(match.group(1)), snapshot_path))
        else:
            health.add_issue(f"invalid archive snapshot filename: {snapshot_path.name}")
    snapshots_with_iters.sort()
    snapshot_iters = [iteration for iteration, _ in snapshots_with_iters]
    if len(set(snapshot_iters)) != len(snapshot_iters):
        health.add_issue("archive snapshots contain duplicate numeric iteration IDs")
    snapshots = [path for _, path in snapshots_with_iters]
    health.n_archive_snapshots = len(snapshots)
    if health.actual_optimizer == "ea":
        if not snapshots:
            health.add_issue("EA run has no archive snapshot")
        else:
            health.final_snapshot_path = snapshots[-1]
            try:
                final_snapshot = _read_json(health.final_snapshot_path)
                if final_snapshot.get("schema_version") != 4:
                    health.add_issue("final archive snapshot is not schema 4")
                if final_snapshot.get("iter") != health.n_evaluated:
                    health.add_issue(
                        f"final archive snapshot iter={final_snapshot.get('iter')!r} "
                        f"!= evaluated={health.n_evaluated}"
                    )
                origin = final_snapshot.get("origin")
                if not isinstance(origin, dict):
                    health.add_issue("final archive snapshot origin object missing")
                    origin = {}
                origin_cid = str(origin.get("cid") or "")
                origin_objectives = tuple(_number(origin.get(key)) for key in ("f1", "f2", "f3"))
                if not origin_cid:
                    health.add_issue("final archive snapshot origin.cid missing")
                if any(value is None for value in origin_objectives):
                    health.add_issue("final archive snapshot origin objectives are non-numeric")
                elif not all(
                    math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-6)
                    for value, expected in zip(origin_objectives, (0.0, 1.0, 0.0))
                ):
                    health.add_issue("final archive snapshot origin objectives are not (0,1,0)")
                chromosomes = final_snapshot.get("chromosomes")
                if not isinstance(chromosomes, list):
                    health.add_issue("final archive snapshot chromosomes[] missing")
                else:
                    chromosome_cids = [origin_cid] if origin_cid else []
                    for index, chromosome in enumerate(chromosomes):
                        prefix = f"final archive chromosome {index}"
                        if not isinstance(chromosome, dict):
                            health.add_issue(f"{prefix} must be an object")
                            continue
                        cid = str(chromosome.get("cid") or "")
                        if not cid:
                            health.add_issue(f"{prefix} cid missing")
                        else:
                            chromosome_cids.append(cid)
                        objectives = tuple(
                            _number(chromosome.get(key)) for key in ("f1", "f2", "f3")
                        )
                        if any(value is None for value in objectives):
                            health.add_issue(f"{prefix} objectives are non-numeric")
                        mutated_rule_ids = chromosome.get("mutated_rule_ids")
                        if not isinstance(mutated_rule_ids, list) or any(
                            not isinstance(value, str) or not value for value in mutated_rule_ids
                        ):
                            health.add_issue(f"{prefix} mutated_rule_ids must be a list of strings")
                            mutated_rule_ids = []
                        if all(value is not None for value in objectives):
                            if not 0.0 <= objectives[1] <= 1.0:
                                health.add_issue(f"{prefix} f2 rule fidelity is outside [0,1]")
                            if not math.isclose(
                                objectives[2],
                                -float(len(mutated_rule_ids)),
                                rel_tol=1e-9,
                                abs_tol=1e-6,
                            ):
                                health.add_issue(
                                    f"{prefix} f3 does not equal negative mutated-rule count"
                                )
                        order_priority = chromosome.get("order_priority")
                        if not isinstance(order_priority, dict) or any(
                            not isinstance(rule_id, str)
                            or not isinstance(priority, int)
                            or isinstance(priority, bool)
                            for rule_id, priority in (
                                order_priority.items() if isinstance(order_priority, dict) else []
                            )
                        ):
                            health.add_issue(
                                f"{prefix} order_priority must map rule IDs to integers"
                            )
                        iteration_added = chromosome.get("iteration_added")
                        if (
                            not isinstance(iteration_added, int)
                            or isinstance(iteration_added, bool)
                            or not 1 <= iteration_added <= health.n_evaluated
                        ):
                            health.add_issue(
                                f"{prefix} invalid iteration_added={iteration_added!r}"
                            )
                        genes = chromosome.get("genes")
                        if not isinstance(genes, dict):
                            health.add_issue(f"{prefix} genes must be an object")
                            continue
                        if set(genes) != set(mutated_rule_ids):
                            health.add_issue(f"{prefix} genes keys do not match mutated_rule_ids")
                        for rule_id, gene in genes.items():
                            if not isinstance(gene, dict):
                                health.add_issue(f"{prefix} gene {rule_id!r} must be an object")
                                continue
                            mutation_path = gene.get("mutation_path")
                            if (
                                not isinstance(mutation_path, list)
                                or not mutation_path
                                or any(
                                    not isinstance(value, str) or not value
                                    for value in mutation_path
                                )
                            ):
                                health.add_issue(
                                    f"{prefix} gene {rule_id!r} has invalid mutation_path"
                                )
                            if gene.get("depth") != (
                                len(mutation_path) if isinstance(mutation_path, list) else None
                            ):
                                health.add_issue(f"{prefix} gene {rule_id!r} depth/path mismatch")
                            text_ref = gene.get("text_ref")
                            text_path = entry.run_dir / str(text_ref) if text_ref else None
                            if (
                                not isinstance(text_ref, str)
                                or not text_ref.startswith("mutated_rules/")
                                or text_path is None
                                or not text_path.resolve().is_relative_to(entry.run_dir.resolve())
                                or not text_path.is_file()
                            ):
                                health.add_issue(f"unresolved final archive text_ref: {text_ref!r}")
                        if cid and isinstance(iteration_added, int):
                            source_rows = [
                                row
                                for row in evaluated
                                if row.get("chromosome_id") == cid
                                and row.get("iter") == iteration_added
                            ]
                            if len(source_rows) != 1:
                                health.add_issue(
                                    f"{prefix} has {len(source_rows)} matching "
                                    "accepted iteration records"
                                )
                            else:
                                source = source_rows[0]
                                source_objectives = tuple(
                                    _number(source.get(key)) for key in ("f1", "f2", "f3")
                                )
                                if source.get("accepted") is not True:
                                    health.add_issue(f"{prefix} source iteration is not accepted")
                                if any(value is None for value in source_objectives) or any(
                                    not math.isclose(
                                        snapshot_value,
                                        source_value,
                                        rel_tol=1e-9,
                                        abs_tol=1e-6,
                                    )
                                    for snapshot_value, source_value in zip(
                                        objectives, source_objectives
                                    )
                                    if snapshot_value is not None and source_value is not None
                                ):
                                    health.add_issue(
                                        f"{prefix} objectives do not match its "
                                        "accepted iteration record"
                                    )
                                if set(source.get("mutated_rule_ids") or []) != set(
                                    mutated_rule_ids
                                ):
                                    health.add_issue(
                                        f"{prefix} mutated_rule_ids do not match "
                                        "its accepted iteration record"
                                    )
                    if len(set(chromosome_cids)) != len(chromosome_cids):
                        health.add_issue("final archive snapshot contains duplicate chromosome IDs")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                health.add_issue(f"final archive snapshot unreadable: {exc}")
        init_n = args.get("ea_init_samples")
        if isinstance(init_n, int) and health.n_evaluated <= init_n:
            health.add_issue(
                f"EA evaluated only {health.n_evaluated} candidates, not beyond init={init_n}"
            )
        if evaluated and not any(
            row.get("phase") in {"ea", "injection", "restart"} for row in evaluated
        ):
            health.add_issue("EA has no evaluated post-init phase record")
    elif snapshots:
        health.warnings.append("random_search unexpectedly has archive snapshots")

    debug_path = entry.run_dir / "semgrep_debug" / "semgrep_debug.jsonl"
    debug_record_count: int | None = None
    if not debug_path.is_file() or debug_path.stat().st_size == 0:
        message = "semgrep_debug/semgrep_debug.jsonl missing or empty"
        if allow_missing_semgrep_debug:
            health.warnings.append(
                "QUALIFIED OVERRIDE: "
                + message
                + "; independent Semgrep process-error auditing is unavailable"
            )
        else:
            health.add_issue(message)
    else:
        debug_summary = _summarise_semgrep_jsonl(debug_path)
        debug_record_count = debug_summary.record_count
        for error in debug_summary.errors:
            health.add_issue(f"Semgrep debug parse error: {error}")
        if debug_summary.missing_error_key:
            health.add_issue(
                f"{debug_summary.missing_error_key} Semgrep records omit the "
                "required error field"
            )
        health.n_semgrep_error = debug_summary.nonnull_error
        health.n_semgrep_clean = debug_summary.null_error
        if health.n_semgrep_error:
            health.add_issue(f"{health.n_semgrep_error} Semgrep records have non-null error")

    cache_stats = health.summary.get("eval_cache_stats")
    if isinstance(cache_stats, dict):
        expected_hits = sum(
            value
            for row in evaluated
            for value in [row.get("n_prompts_reused")]
            if isinstance(value, int) and not isinstance(value, bool)
        )
        expected_misses = health.n_baseline_records + sum(
            value
            for row in evaluated
            for value in [row.get("n_prompts_rerun")]
            if isinstance(value, int) and not isinstance(value, bool)
        )
        actual_hits = cache_stats.get("hits")
        actual_misses = cache_stats.get("misses")
        if debug_record_count is not None:
            if (
                graceful_inflight_discard
                and isinstance(actual_misses, int)
                and not isinstance(actual_misses, bool)
            ):
                debug_count_valid = expected_misses <= debug_record_count <= actual_misses
                debug_expectation = (
                    f"completed-to-in-flight fresh-scan range [{expected_misses}, {actual_misses}]"
                )
            else:
                debug_count_valid = debug_record_count == expected_misses
                debug_expectation = f"expected fresh scans={expected_misses}"
            if not debug_count_valid:
                health.add_issue(
                    f"Semgrep debug records={debug_record_count} != {debug_expectation}"
                )
        if graceful_inflight_discard and all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (actual_hits, actual_misses)
        ):
            extra_hits = actual_hits - expected_hits
            extra_misses = actual_misses - expected_misses
            extra_total = extra_hits + extra_misses
            if (
                extra_hits < 0
                or extra_misses < 0
                or health.n_cases is None
                or extra_total >= health.n_cases
            ):
                health.add_issue(
                    "graceful in-flight cache accounting is inconsistent with "
                    f"completed rows: extra_hits={extra_hits}, "
                    f"extra_misses={extra_misses}"
                )
            elif extra_total:
                warning = (
                    "graceful pre-timeout discarded an in-flight candidate; "
                    f"cache totals include {extra_total} partial prompt(s)"
                )
                if warning not in health.warnings:
                    health.warnings.append(warning)
        else:
            if actual_hits != expected_hits:
                health.add_issue(
                    f"eval-cache hits={actual_hits!r} != iteration reuse total={expected_hits}"
                )
            if actual_misses != expected_misses:
                health.add_issue(
                    f"eval-cache misses={actual_misses!r} "
                    f"!= baseline+iteration reruns={expected_misses}"
                )

    reached_budget = (
        health.max_iterations is not None and health.n_evaluated == health.max_iterations
    )
    if reached_budget:
        health.stop_class = "completed_evaluation_budget"
    elif log_text and _CRASH_RE.search(log_text):
        health.stop_class = "exception_or_rate_limit"
        health.add_issue("run log indicates exception/rate-limit/abnormal abort")
    elif log_text and _GRACEFUL_RE.search(log_text) and health.summary:
        health.stop_class = "graceful_pre_timeout"
    elif health.summary:
        health.stop_class = "finalized_but_stop_unverified"
        health.add_issue("early stop cannot be classified without a graceful-stop log")
    else:
        health.stop_class = "crash_or_partial"
        health.add_issue("natural stop not verified")

    health.finalise()
    return health


def inspect_manifest(
    entries: Sequence[ManifestEntry],
    *,
    expected_seeds: Sequence[str] = (),
    expected_languages: Sequence[str] = tuple(sorted(_VALID_LANGUAGES)),
    expected_optimizers: Sequence[str] = tuple(sorted(_VALID_OPTIMIZERS)),
    allow_missing_semgrep_debug: bool = False,
    rules_map_roots: Sequence[Path] = (),
) -> list[RunHealth]:
    """Inspect all expected runs and apply cross-run manifest invariants."""
    languages = {_normalise_language(value) for value in expected_languages}
    optimizers = {_normalise_optimizer(value) for value in expected_optimizers}
    invalid_languages = sorted(languages - _VALID_LANGUAGES)
    invalid_optimizers = sorted(optimizers - _VALID_OPTIMIZERS)
    if not languages or invalid_languages:
        raise ValueError(
            "expected_languages must be a nonempty subset of "
            f"{sorted(_VALID_LANGUAGES)}; invalid={invalid_languages}"
        )
    if not optimizers or invalid_optimizers:
        raise ValueError(
            "expected_optimizers must be a nonempty subset of "
            f"{sorted(_VALID_OPTIMIZERS)}; invalid={invalid_optimizers}"
        )
    healths = [
        _inspect_single(
            entry,
            allow_missing_semgrep_debug=allow_missing_semgrep_debug,
            rules_map_roots=rules_map_roots,
        )
        for entry in entries
    ]

    by_key: dict[tuple[str, str, str, str], list[RunHealth]] = defaultdict(list)
    by_job: dict[str, list[RunHealth]] = defaultdict(list)
    for health in healths:
        by_key[health.key].append(health)
        if health.slurm_job_id:
            by_job[health.slurm_job_id].append(health)
    for key, group in by_key.items():
        if len(group) > 1:
            for health in group:
                health.add_issue(f"duplicate manifest cell {key}: {len(group)} runs")
    for job_id, group in by_job.items():
        if len(group) > 1:
            for health in group:
                health.add_issue(f"duplicate slurm_job_id={job_id}")

    present = [health for health in healths if health.status != "missing" and health.config]
    model_families = {health.key[0] for health in healths if health.key[0] in _VALID_MODEL_FAMILIES}
    expected_configs = {
        (model, language, optimizer)
        for model in model_families
        for language in languages
        for optimizer in optimizers
    }
    manifest_configs = {
        (health.key[0], health.entry.language, health.entry.optimizer) for health in healths
    }
    missing_configs = sorted(expected_configs - manifest_configs)
    if missing_configs:
        warning = f"manifest omits configuration cells: {missing_configs}"
        for health in healths:
            if warning not in health.warnings:
                health.warnings.append(warning)

    seeds_by_config: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for health in healths:
        seeds_by_config[(health.key[0], health.entry.language, health.entry.optimizer)].add(
            health.entry.seed
        )
    populated_seed_sets = {
        config: seeds
        for config, seeds in seeds_by_config.items()
        if config in expected_configs and seeds
    }
    unique_seed_sets = {
        tuple(sorted(seeds, key=_seed_sort_key)) for seeds in populated_seed_sets.values()
    }
    if len(unique_seed_sets) > 1:
        detail = ", ".join(
            f"{model}/{language}/{optimizer}={sorted(seeds, key=_seed_sort_key)}"
            for (model, language, optimizer), seeds in sorted(populated_seed_sets.items())
        )
        for health in healths:
            warning = f"incomplete model × language × optimizer × seed grid: {detail}"
            if warning not in health.warnings:
                health.warnings.append(warning)

    expected_seed_set = {_normalise_seed(seed) for seed in expected_seeds}
    if expected_seed_set:
        expected_cells = {
            (model, language, optimizer, seed)
            for model, language, optimizer in expected_configs
            for seed in expected_seed_set
        }
        supplied_cells = {health.key for health in healths}
        missing_cells = sorted(
            expected_cells - supplied_cells,
            key=lambda cell: (cell[0], cell[1], cell[2], _seed_sort_key(cell[3])),
        )
        unexpected_cells = sorted(
            supplied_cells - expected_cells,
            key=lambda cell: (cell[0], cell[1], cell[2], _seed_sort_key(cell[3])),
        )
        duplicate_cells = sorted(
            (key for key, group in by_key.items() if len(group) > 1),
            key=lambda cell: (cell[0], cell[1], cell[2], _seed_sort_key(cell[3])),
        )
        if missing_cells or unexpected_cells or duplicate_cells:
            details = []
            if missing_cells:
                details.append(f"missing={missing_cells}")
            if unexpected_cells:
                details.append(f"unexpected={unexpected_cells}")
            if duplicate_cells:
                details.append(f"duplicates={duplicate_cells}")
            warning = "manifest violates expected seed contract: " + "; ".join(details)
            for health in healths:
                if warning not in health.warnings:
                    health.warnings.append(warning)

    shas = {health.git_sha for health in present if health.git_sha}
    if len(shas) > 1:
        for health in present:
            health.add_issue(f"git_sha differs across manifest: {sorted(shas)}")
    model_languages = sorted(
        {
            (health.actual_model_family, health.actual_language)
            for health in present
            if health.actual_model_family in _VALID_MODEL_FAMILIES
            and health.actual_language in _VALID_LANGUAGES
        }
    )
    for model, language in model_languages:
        counts = {
            health.n_cases
            for health in present
            if health.actual_model_family == model
            and health.actual_language == language
            and health.n_cases is not None
        }
        if len(counts) > 1:
            for health in present:
                if health.actual_model_family == model and health.actual_language == language:
                    health.add_issue(f"n_cases differs for {model}/{language}: {sorted(counts)}")

    by_model_language_seed: dict[tuple[str, str, str], list[RunHealth]] = defaultdict(list)
    for health in present:
        by_model_language_seed[
            (
                health.actual_model_family,
                health.actual_language,
                health.actual_seed,
            )
        ].append(health)
    for (model, language, seed), group in by_model_language_seed.items():
        arms = {health.actual_optimizer for health in group}
        if len(arms) < 2:
            continue
        id_sets = {health.baseline_ids for health in group}
        if len(id_sets) > 1:
            for health in group:
                health.add_issue(
                    "baseline task-set mismatch between optimizer arms for "
                    f"{model}/{language}/seed={seed}"
                )
            continue
        signature_maps = [health.baseline_signature_by_id for health in group]
        if signature_maps and any(
            set(signature_map) != set(group[0].baseline_ids) for signature_map in signature_maps
        ):
            for health in group:
                health.add_issue(
                    f"incomplete baseline result signature map for {model}/{language}/seed={seed}"
                )
            continue
        reference = signature_maps[0] if signature_maps else {}

        def signature_differs(
            first: tuple[int, float, tuple[str, ...], str],
            second: tuple[int, float, tuple[str, ...], str],
        ) -> bool:
            return (
                first[0] != second[0]
                or not math.isclose(first[1], second[1], rel_tol=1e-9, abs_tol=1e-6)
                or first[2:] != second[2:]
            )

        if any(
            any(
                signature_differs(reference[test_case_id], signature_map[test_case_id])
                for test_case_id in reference
            )
            for signature_map in signature_maps[1:]
        ):
            for health in group:
                health.add_issue(
                    f"baseline raw/weighted/check/CWE mismatch between optimizer arms "
                    f"for {model}/{language}/seed={seed}"
                )

    for model, language in model_languages:
        language_runs = [
            health
            for health in present
            if health.actual_model_family == model and health.actual_language == language
        ]
        if len({health.baseline_ids for health in language_runs}) > 1:
            for health in language_runs:
                health.add_issue(
                    f"baseline task set differs across {model}/{language} runs; "
                    "final seeds must evaluate one common full-population map"
                )

    comparable_keys = (
        "backend",
        "model",
        "quantization",
        "bnb_compute_dtype",
        "temperature",
        "rules_map",
        "n_cases",
        "iterations",
        "selection",
        "mutators",
        "objective_direction",
        "max_depth",
        "random_max_changes",
        "order_move_weight",
        "enable_validation",
        "enable_perplexity",
        "enable_eval_cache",
        "semgrep_config",
        "semgrep_timeout_seconds",
        "semgrep_jobs",
    )
    ea_only_keys = (
        "archive_cap",
        "restart_h",
        "ea_n_mutations",
        "ea_init_samples",
        "ea_injection_every",
        "ea_move",
        "ea_origin_parent",
    )
    for model, language in model_languages:
        group = [
            health
            for health in present
            if health.actual_model_family == model and health.actual_language == language
        ]
        for key in comparable_keys:
            values = {
                json.dumps(
                    health.config.get("args", {}).get(key),
                    sort_keys=True,
                    default=str,
                )
                for health in group
            }
            if len(values) > 1:
                for health in group:
                    health.add_issue(
                        f"comparison config mismatch for {model}/{language}: "
                        f"args.{key}={sorted(values)}"
                    )
        ea_group = [health for health in group if health.actual_optimizer == "ea"]
        for key in ea_only_keys:
            values = {
                json.dumps(
                    health.config.get("args", {}).get(key),
                    sort_keys=True,
                    default=str,
                )
                for health in ea_group
            }
            if len(values) > 1:
                for health in ea_group:
                    health.add_issue(
                        f"EA config mismatch for {model}/{language}: args.{key}={sorted(values)}"
                    )

    for health in healths:
        health.finalise()
    return healths


def common_budgets(healths: Sequence[RunHealth]) -> dict[str, int]:
    """Shortest healthy candidate-evaluation horizon shared by both arms."""
    result: dict[str, int] = {}
    for language in sorted(_VALID_LANGUAGES):
        by_arm = {
            optimizer: [
                health.n_evaluated
                for health in healths
                if health.healthy
                and health.actual_language == language
                and health.actual_optimizer == optimizer
            ]
            for optimizer in sorted(_VALID_OPTIMIZERS)
        }
        if all(by_arm.values()):
            result[language] = min(min(values) for values in by_arm.values())
    return result


@dataclass(frozen=True)
class PromptResult:
    test_case_id: str
    language: str
    cwe_id: str
    raw_count: int
    weighted_score: float
    check_ids: frozenset[str]
    iteration: int
    source: str

    @property
    def vulnerable(self) -> bool:
        return self.raw_count > 0


def _baseline_results_match(
    first: dict[str, PromptResult], second: dict[str, PromptResult]
) -> bool:
    if set(first) != set(second):
        return False
    return all(
        first[test_case_id].raw_count == second[test_case_id].raw_count
        and math.isclose(
            first[test_case_id].weighted_score,
            second[test_case_id].weighted_score,
            rel_tol=1e-9,
            abs_tol=1e-6,
        )
        and first[test_case_id].check_ids == second[test_case_id].check_ids
        and first[test_case_id].cwe_id == second[test_case_id].cwe_id
        for test_case_id in first
    )


@dataclass
class TaskOutcome:
    test_case_id: str
    cwe_id: str
    baseline_class: str
    baseline: PromptResult
    best: PromptResult

    @property
    def delta_raw(self) -> int:
        return self.baseline.raw_count - self.best.raw_count

    @property
    def delta_weighted(self) -> float:
        return self.baseline.weighted_score - self.best.weighted_score

    @property
    def movable(self) -> bool:
        return self.baseline.vulnerable

    @property
    def repaired_to_zero(self) -> bool:
        return self.baseline.vulnerable and not self.best.vulnerable


def _prompt_result(row: dict[str, Any], *, iteration: int, source: str) -> PromptResult:
    test_case_id = row.get("test_case_id")
    if test_case_id is None or not str(test_case_id).strip():
        raise ValueError(f"{source}: missing test_case_id")
    fitness = row.get("fitness")
    if not isinstance(fitness, dict):
        raise ValueError(f"{source}: missing fitness object")
    raw = fitness.get("raw_count")
    weighted = fitness.get("weighted_score")
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"{source}: invalid raw_count={raw!r}")
    weighted_number = _number(weighted)
    if weighted_number is None or weighted_number < 0:
        raise ValueError(f"{source}: invalid weighted_score={weighted!r}")
    checks = fitness.get("check_ids")
    if (
        not isinstance(checks, list)
        or any(not isinstance(value, str) or not value.strip() for value in checks)
        or len(set(checks)) != len(checks)
    ):
        raise ValueError(f"{source}: check_ids must be a unique list of nonblank strings")
    language = _normalise_language(row.get("language"))
    cwe_id = str(row.get("cwe_id") or "").strip()
    if not language:
        raise ValueError(f"{source}: language is blank")
    if not cwe_id:
        raise ValueError(f"{source}: cwe_id is blank")
    return PromptResult(
        test_case_id=str(test_case_id),
        language=language,
        cwe_id=cwe_id,
        raw_count=raw,
        weighted_score=weighted_number,
        check_ids=frozenset(str(value) for value in checks),
        iteration=iteration,
        source=source,
    )


def _is_safer(candidate: PromptResult, current: PromptResult) -> bool:
    return (
        candidate.weighted_score,
        candidate.raw_count,
        candidate.iteration,
    ) < (
        current.weighted_score,
        current.raw_count,
        current.iteration,
    )


def _load_subset_classes(
    subset_dir: Path,
    language: str,
    model: str,
) -> tuple[dict[str, str], str]:
    """Load classes only when the persisted column matches the final-run model.

    The checked-in ``qwen_class`` labels were built for Qwen2.5-Coder-32B.
    Treating them as generic model labels would silently change the RQ1 subset
    estimand, so other model families remain explicitly unavailable.
    """
    path = subset_dir / f"baseline_common_{language}.csv"
    if not path.is_file():
        return ({}, f"baseline subset file missing for {language}")
    if _model_family_from_config(model) != "qwen":
        return (
            {},
            f"baseline subset labels are unavailable for model={model!r}; "
            "qwen_class is verified only for Qwen2.5-Coder-32B-Instruct",
        )
    classes: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"tid", "qwen_class"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            return ({}, f"{path.name} lacks required columns: {sorted(missing)}")
        for row in reader:
            test_case_id = str(row.get("tid") or "").strip()
            if not test_case_id or test_case_id in classes:
                return ({}, f"{path.name} has blank or duplicate tid={test_case_id!r}")
            normalized = labels.normalize(str(row.get("qwen_class") or ""))
            classes[test_case_id] = normalized if normalized in labels.ALL else ""
    return (classes, "")


def _subset_match(outcome: TaskOutcome, subset: str) -> bool:
    if subset == "full":
        return True
    if subset == "persistent":
        return outcome.baseline_class == labels.ALWAYS_VULNERABLE
    if subset == "variable":
        return outcome.baseline_class in {
            labels.SOMETIMES_VULNERABLE,
            labels.FIXED_BY_RULES,
        }
    if subset == "never":
        return outcome.baseline_class == labels.ALWAYS_SAFE
    if subset == "movable":
        return outcome.movable
    raise ValueError(f"unknown subset: {subset}")


def _task_summary(outcomes: Sequence[TaskOutcome], subset: str) -> dict[str, Any]:
    selected = [outcome for outcome in outcomes if _subset_match(outcome, subset)]
    movable = [outcome for outcome in selected if outcome.movable]
    repaired = [outcome for outcome in movable if outcome.repaired_to_zero]
    reduced = [outcome for outcome in movable if outcome.delta_raw > 0]
    point, ci_low, ci_high = stats_helpers.wilson_ci(len(repaired), len(movable))
    return {
        "subset": subset,
        "n_tasks": len(selected),
        "n_movable": len(movable),
        "n_repaired": len(repaired),
        "n_reduced": len(reduced),
        "repair_rate": point,
        "repair_ci_low": ci_low,
        "repair_ci_high": ci_high,
        "raw_reduction": sum(outcome.delta_raw for outcome in movable),
        "weighted_reduction": sum(outcome.delta_weighted for outcome in movable),
        "mean_weighted_reduction": (
            sum(outcome.delta_weighted for outcome in movable) / len(movable)
            if movable
            else math.nan
        ),
    }


def _best_f1(
    iterations: Sequence[dict[str, Any]], budget: int | None = None
) -> tuple[float, int, str]:
    best = (0.0, 0, "origin")
    for row in iterations:
        if row.get("budget_consumed") is not True:
            continue
        iteration = row.get("iter")
        f1 = _number(row.get("f1"))
        if not isinstance(iteration, int) or f1 is None:
            continue
        if budget is not None and iteration > budget:
            continue
        if f1 > best[0]:
            best = (f1, iteration, str(row.get("phase") or ""))
    return best


def _operator_rows(iterations: Sequence[dict[str, Any]], *, budget: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in iterations:
        if row.get("strategy") != "ea" or row.get("phase") != "ea":
            continue
        iteration = row.get("iter")
        if not isinstance(iteration, int) or iteration > budget:
            continue
        move_type = str(row.get("move_type") or "")
        chain = row.get("mutation_chain") or []
        attempted = row.get("attempted_mutators") or []
        if move_type == "mutate":
            names = chain if isinstance(chain, list) and chain else attempted
            operator = str(names[-1]) if names else "unknown_mutator"
        elif move_type in {"order", "reverse"}:
            operator = move_type
        else:
            continue
        evaluated = row.get("budget_consumed") is True and _number(row.get("f1")) is not None
        parent_f1 = _number((row.get("selection_meta") or {}).get("parent_f1"))
        child_f1 = _number(row.get("f1"))
        delta = (
            child_f1 - parent_f1
            if evaluated and child_f1 is not None and parent_f1 is not None
            else None
        )
        rows.append(
            {
                "operator": operator,
                "family": _operator_family(operator),
                "evaluated": evaluated,
                "identity": row.get("mutation_identity") is True,
                "security_improving": delta is not None and delta > 0,
                "delta_f1": delta,
                "accepted": row.get("accepted") is True,
            }
        )
    return rows


def _operator_family(operator: str) -> str:
    if operator in {"negation_injection", "voice_change", "paraphrase"}:
        return "llm"
    if operator in {"order", "reverse", "section_reorder_shuffle", "section_reorder_degrade"}:
        return "structural"
    return "rule_based"


def _final_front_best(health: RunHealth) -> dict[str, Any]:
    """Best surviving final-front chromosome, explicitly including the origin."""
    if health.actual_optimizer != "ea" or not health.final_snapshot_path:
        return {}
    snapshot = _read_json(health.final_snapshot_path)
    origin = snapshot["origin"]
    origin_f1 = _number(origin.get("f1"))
    origin_f2 = _number(origin.get("f2"))
    origin_f3 = _number(origin.get("f3"))
    assert origin_f1 is not None and origin_f2 is not None and origin_f3 is not None
    candidates: list[dict[str, Any]] = [
        {
            "cid": origin["cid"],
            "f1": origin_f1,
            "f2": origin_f2,
            "f3": origin_f3,
            "mutated_rule_ids": [],
            "order_priority": {},
            "genes": {},
            "iteration_added": 0,
            "source": "origin",
        }
    ]
    for chromosome in snapshot.get("chromosomes") or []:
        if isinstance(chromosome, dict):
            candidate = dict(chromosome)
            candidate["source"] = "final_front"
            candidates.append(candidate)

    def rank(candidate: dict[str, Any]) -> tuple[float, float]:
        f1 = _number(candidate.get("f1"))
        f2 = _number(candidate.get("f2"))
        f3 = _number(candidate.get("f3"))
        return (
            f1 if f1 is not None else -math.inf,
            (f2 if f2 is not None else 0.0) + (f3 if f3 is not None else 0.0),
        )

    return max(candidates, key=rank)


@dataclass
class RunAnalysis:
    health: RunHealth
    comparison_budget: int
    horizon_scope: str
    baseline: dict[str, PromptResult]
    final_outcomes: list[TaskOutcome]
    budget_outcomes: list[TaskOutcome]
    best_f1_final: float
    best_f1_iter: int
    best_f1_phase: str
    best_f1_budget: float
    best_f1_budget_iter: int
    best_f1_budget_phase: str
    task_summaries_final: dict[str, dict[str, Any]]
    task_summaries_budget: dict[str, dict[str, Any]]
    operator_rows: list[dict[str, Any]]
    final_front_best: dict[str, Any]
    subset_warnings: list[str]
    subset_classification_complete: bool

    @property
    def model_family(self) -> str:
        return self.health.actual_model_family

    @property
    def language(self) -> str:
        return self.health.actual_language

    @property
    def optimizer(self) -> str:
        return self.health.actual_optimizer

    @property
    def seed(self) -> str:
        return self.health.actual_seed


def _analyze_single(
    health: RunHealth,
    *,
    comparison_budget: int,
    horizon_scope: str,
    subset_dir: Path,
) -> RunAnalysis:
    assert health.path is not None
    baseline_path = health.path / "intermediate" / "baseline.jsonl"
    baseline: dict[str, PromptResult] = {}
    for row in _iter_jsonl(baseline_path):
        rules_used = row.get("rules_used")
        if (
            row.get("iter_id") != "baseline"
            or not isinstance(rules_used, dict)
            or not isinstance(rules_used.get("chromosome_id"), str)
            or not rules_used.get("chromosome_id")
            or rules_used.get("mutated_rule_ids") != []
            or rules_used.get("prompt_affected") is not False
        ):
            raise ValueError(f"{baseline_path}: invalid baseline iter/rules_used provenance")
        prompt = _prompt_result(row, iteration=0, source=str(baseline_path))
        if prompt.test_case_id in baseline:
            raise ValueError(f"{baseline_path}: duplicate test_case_id={prompt.test_case_id}")
        if prompt.language != health.actual_language:
            raise ValueError(
                f"{baseline_path}: test_case_id={prompt.test_case_id} has "
                f"language={prompt.language!r}, expected {health.actual_language!r}"
            )
        baseline[prompt.test_case_id] = prompt
    final_best = dict(baseline)
    budget_best = dict(baseline)

    evaluated = [
        row
        for row in health.iterations
        if row.get("budget_consumed") is True
        and _number(row.get("f1")) is not None
        and isinstance(row.get("iter"), int)
    ]
    for iteration_row in sorted(evaluated, key=lambda row: row["iter"]):
        iteration = int(iteration_row["iter"])
        path = _expected_intermediate(health, iteration)
        expected_iter_id = path.stem
        expected_chromosome_id = iteration_row["chromosome_id"]
        seen: set[str] = set()
        candidate_weighted_total = 0.0
        for row in _iter_jsonl(path):
            rules_used = row.get("rules_used")
            if (
                row.get("iter_id") != expected_iter_id
                or not isinstance(rules_used, dict)
                or rules_used.get("chromosome_id") != expected_chromosome_id
            ):
                raise ValueError(
                    f"{path}: prompt provenance does not match iteration "
                    f"{iteration}/{expected_chromosome_id}"
                )
            candidate = _prompt_result(row, iteration=iteration, source=str(path))
            if candidate.test_case_id in seen:
                raise ValueError(f"{path}: duplicate test_case_id={candidate.test_case_id}")
            seen.add(candidate.test_case_id)
            if candidate.test_case_id not in baseline:
                raise ValueError(f"{path}: unexpected test_case_id={candidate.test_case_id}")
            if candidate.cwe_id != baseline[candidate.test_case_id].cwe_id:
                raise ValueError(
                    f"{path}: test_case_id={candidate.test_case_id} has "
                    "a different cwe_id from baseline"
                )
            if candidate.language != health.actual_language:
                raise ValueError(
                    f"{path}: test_case_id={candidate.test_case_id} has "
                    f"language={candidate.language!r}, expected "
                    f"{health.actual_language!r}"
                )
            candidate_weighted_total += candidate.weighted_score
            if _is_safer(candidate, final_best[candidate.test_case_id]):
                final_best[candidate.test_case_id] = candidate
            if iteration <= comparison_budget and _is_safer(
                candidate, budget_best[candidate.test_case_id]
            ):
                budget_best[candidate.test_case_id] = candidate
        expected_ids = set(baseline)
        if seen != expected_ids:
            missing = sorted(expected_ids - seen)
            extra = sorted(seen - expected_ids)
            raise ValueError(
                f"{path}: prompt set mismatch; missing={missing[:5]}, extra={extra[:5]}"
            )
        baseline_weighted_total = sum(prompt.weighted_score for prompt in baseline.values())
        recorded_f1 = _number(iteration_row.get("f1"))
        expected_f1 = baseline_weighted_total - candidate_weighted_total
        if recorded_f1 is None or not math.isclose(
            recorded_f1, expected_f1, rel_tol=1e-9, abs_tol=1e-6
        ):
            raise ValueError(
                f"{path}: per-prompt weighted scores imply f1={expected_f1}, "
                f"iterations.jsonl records f1={recorded_f1!r}"
            )

    classes, subset_load_warning = _load_subset_classes(
        subset_dir,
        health.actual_language,
        health.model,
    )
    final_outcomes = [
        TaskOutcome(
            test_case_id=test_case_id,
            cwe_id=base.cwe_id,
            baseline_class=classes.get(test_case_id, ""),
            baseline=base,
            best=final_best[test_case_id],
        )
        for test_case_id, base in sorted(baseline.items())
    ]
    budget_outcomes = [
        TaskOutcome(
            test_case_id=test_case_id,
            cwe_id=base.cwe_id,
            baseline_class=classes.get(test_case_id, ""),
            baseline=base,
            best=budget_best[test_case_id],
        )
        for test_case_id, base in sorted(baseline.items())
    ]

    subset_warnings: list[str] = []
    if subset_load_warning:
        subset_warnings.append(
            f"{subset_load_warning}; persistent/variable results are unavailable"
        )
    if not classes:
        if not subset_load_warning:
            subset_warnings.append(
                f"baseline subset classes unavailable for {health.actual_language}; "
                "persistent/variable results are unavailable"
            )
    unknown = sum(1 for outcome in final_outcomes if not outcome.baseline_class)
    if classes and unknown:
        subset_warnings.append(f"{unknown} final baseline task IDs lack a subset class")
    never_vulnerable = sum(
        1
        for outcome in final_outcomes
        if outcome.baseline_class == labels.ALWAYS_SAFE and outcome.baseline.vulnerable
    )
    if never_vulnerable:
        subset_warnings.append(
            f"never-floor violation: {never_vulnerable} ALWAYS_SAFE tasks are vulnerable "
            "in the final run baseline"
        )
    persistent_safe = sum(
        1
        for outcome in final_outcomes
        if outcome.baseline_class == labels.ALWAYS_VULNERABLE and not outcome.baseline.vulnerable
    )
    if persistent_safe:
        subset_warnings.append(
            f"persistent-baseline drift: {persistent_safe} ALWAYS_VULNERABLE tasks "
            "are safe in the final run baseline"
        )

    best_final = _best_f1(health.iterations)
    best_budget = _best_f1(health.iterations, comparison_budget)
    subsets = ("full", "persistent", "variable", "never")
    return RunAnalysis(
        health=health,
        comparison_budget=comparison_budget,
        horizon_scope=horizon_scope,
        baseline=baseline,
        final_outcomes=final_outcomes,
        budget_outcomes=budget_outcomes,
        best_f1_final=best_final[0],
        best_f1_iter=best_final[1],
        best_f1_phase=best_final[2],
        best_f1_budget=best_budget[0],
        best_f1_budget_iter=best_budget[1],
        best_f1_budget_phase=best_budget[2],
        task_summaries_final={subset: _task_summary(final_outcomes, subset) for subset in subsets},
        task_summaries_budget={
            subset: _task_summary(budget_outcomes, subset) for subset in subsets
        },
        operator_rows=_operator_rows(health.iterations, budget=comparison_budget),
        final_front_best=_final_front_best(health),
        subset_warnings=subset_warnings,
        subset_classification_complete=bool(classes) and unknown == 0,
    )


@dataclass
class AnalysisBundle:
    healths: list[RunHealth]
    runs: list[RunAnalysis]
    common_budgets: dict[str, int]
    analysis_budgets: dict[str, int]
    model_family: str
    extraction_errors: list[str] = field(default_factory=list)
    expected_seeds: tuple[str, ...] = ()
    expected_languages: tuple[str, ...] = tuple(sorted(_VALID_LANGUAGES))
    expected_optimizers: tuple[str, ...] = tuple(sorted(_VALID_OPTIMIZERS))

    @property
    def healthy_n(self) -> int:
        return sum(1 for health in self.healths if health.healthy)

    @property
    def analysis_warnings(self) -> list[str]:
        return sorted(
            {warning for health in self.healths for warning in health.warnings if warning}
            | {warning for run in self.runs for warning in run.subset_warnings if warning}
            | {f"metric extraction exclusion: {error}" for error in self.extraction_errors}
        )

    @property
    def has_cautions(self) -> bool:
        return bool(self.analysis_warnings) or any(not health.healthy for health in self.healths)

    @property
    def manifest_warnings(self) -> list[str]:
        prefixes = (
            "manifest omits configuration cells:",
            "incomplete model × language × optimizer × seed grid:",
        )
        return sorted(
            {
                warning
                for health in self.healths
                for warning in health.warnings
                if warning.startswith(prefixes)
            }
        )

    @property
    def expected_grid_warnings(self) -> list[str]:
        return sorted(
            {
                warning
                for health in self.healths
                for warning in health.warnings
                if warning.startswith("manifest violates expected seed contract:")
            }
        )

    @property
    def expected_grid_complete(self) -> bool | None:
        """Whether the independently declared final seed matrix is complete."""
        if not self.expected_seeds:
            return None
        return not self.expected_grid_warnings

    @property
    def supplied_grid_rectangular(self) -> bool:
        """Whether supplied rows form the declared language/optimizer grid.

        This cannot detect a seed omitted from every cell; that requires the
        independently confirmed submitted-SLURM seed list.
        """
        return not self.manifest_warnings


def analyze_manifest(
    entries: Sequence[ManifestEntry],
    *,
    subset_dir: Path,
    expected_seeds: Sequence[str] = (),
    expected_languages: Sequence[str] = tuple(sorted(_VALID_LANGUAGES)),
    expected_optimizers: Sequence[str] = tuple(sorted(_VALID_OPTIMIZERS)),
    allow_missing_semgrep_debug: bool = False,
    rules_map_roots: Sequence[Path] = (),
) -> AnalysisBundle:
    """Health-check one model family's final manifest and analyze healthy runs.

    Downstream summaries intentionally do not pool model families. Callers with
    a combined Qwen/Llama manifest must partition it and produce one bundle per
    family.
    """
    normalised_expected_seeds = tuple(_normalise_seed(seed) for seed in expected_seeds)
    normalised_expected_languages = tuple(
        _normalise_language(language) for language in expected_languages
    )
    normalised_expected_optimizers = tuple(
        _normalise_optimizer(optimizer) for optimizer in expected_optimizers
    )
    declared_model_families = {
        family
        for entry in entries
        for family in [_normalise_model_family(entry.model)]
        if family in _VALID_MODEL_FAMILIES
    }
    if len(declared_model_families) > 1:
        raise ValueError(
            "an analysis bundle must contain exactly one model family; "
            f"found {sorted(declared_model_families)}"
        )
    healths = inspect_manifest(
        entries,
        expected_seeds=normalised_expected_seeds,
        expected_languages=expected_languages,
        expected_optimizers=expected_optimizers,
        allow_missing_semgrep_debug=allow_missing_semgrep_debug,
        rules_map_roots=rules_map_roots,
    )
    bundle_model_families = declared_model_families | {
        health.actual_model_family
        for health in healths
        if health.actual_model_family in _VALID_MODEL_FAMILIES
    }
    if len(bundle_model_families) != 1:
        found = sorted(bundle_model_families)
        raise ValueError(
            "an analysis bundle must resolve to exactly one model family; "
            f"found {found or '[none]'}"
        )
    model_family = next(iter(bundle_model_families))
    errors: list[str] = []
    while True:
        budgets = common_budgets(healths)
        analysis_budgets = dict(budgets)
        for language in sorted(_VALID_LANGUAGES):
            available = [
                health.n_evaluated
                for health in healths
                if health.healthy and health.actual_language == language
            ]
            if language not in analysis_budgets and available:
                analysis_budgets[language] = min(available)
        runs: list[RunAnalysis] = []
        excluded_this_pass = False
        for health in healths:
            if not health.healthy:
                continue
            budget = analysis_budgets.get(health.actual_language)
            if budget is None:
                continue
            try:
                runs.append(
                    _analyze_single(
                        health,
                        comparison_budget=budget,
                        horizon_scope=(
                            "cross_arm_common"
                            if health.actual_language in budgets
                            else "available_runs_minimum"
                        ),
                        subset_dir=subset_dir,
                    )
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                health.add_issue(f"metric extraction failed: {exc}")
                health.finalise()
                message = f"{health.path}: {exc}"
                if message not in errors:
                    errors.append(message)
                excluded_this_pass = True
        if not excluded_this_pass:
            break
    return AnalysisBundle(
        healths=healths,
        runs=runs,
        common_budgets=budgets,
        analysis_budgets=analysis_budgets,
        model_family=model_family,
        extraction_errors=errors,
        expected_seeds=normalised_expected_seeds,
        expected_languages=normalised_expected_languages,
        expected_optimizers=normalised_expected_optimizers,
    )


def paired_rank_biserial(baseline: Sequence[float], treatment: Sequence[float]) -> float:
    """Matched-pairs rank-biserial effect; positive means treatment is lower/safer."""
    diffs = [float(a) - float(b) for a, b in zip(baseline, treatment) if a != b]
    if not diffs:
        return math.nan
    abs_values = sorted((abs(value), index) for index, value in enumerate(diffs))
    ranks = [0.0] * len(diffs)
    cursor = 0
    while cursor < len(abs_values):
        end = cursor + 1
        while end < len(abs_values) and abs_values[end][0] == abs_values[cursor][0]:
            end += 1
        rank = ((cursor + 1) + end) / 2
        for _, original_index in abs_values[cursor:end]:
            ranks[original_index] = rank
        cursor = end
    positive = sum(rank for rank, diff in zip(ranks, diffs) if diff > 0)
    negative = sum(rank for rank, diff in zip(ranks, diffs) if diff < 0)
    return (positive - negative) / (positive + negative)


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """Benjamini-Hochberg adjusted p-values, preserving None entries."""
    indexed = [(index, value) for index, value in enumerate(p_values) if value is not None]
    if not indexed:
        return [None] * len(p_values)
    ordered = sorted(indexed, key=lambda pair: float(pair[1]))
    adjusted: dict[int, float] = {}
    running = 1.0
    m = len(ordered)
    for reverse_rank, (index, value) in enumerate(reversed(ordered), 1):
        rank = m - reverse_rank + 1
        running = min(running, float(value) * m / rank)
        adjusted[index] = min(1.0, running)
    return [adjusted.get(index) for index in range(len(p_values))]


def config_groups(runs: Sequence[RunAnalysis]) -> dict[tuple[str, str], list[RunAnalysis]]:
    groups: dict[tuple[str, str], list[RunAnalysis]] = defaultdict(list)
    for run in runs:
        groups[(run.language, run.optimizer)].append(run)
    return dict(groups)


def per_config_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (language, optimizer), group in sorted(config_groups(runs).items()):
        f1_final = [run.best_f1_final for run in group]
        f1_budget = [run.best_f1_budget for run in group]
        final_med, final_q1, final_q3 = _median_iqr(f1_final)
        budget_med, budget_q1, budget_q3 = _median_iqr(f1_budget)
        for subset in ("full", "persistent", "variable"):
            subset_available = subset == "full" or all(
                run.subset_classification_complete for run in group
            )
            if not subset_available:
                rows.append(
                    {
                        "language": language,
                        "optimizer": optimizer,
                        "subset": subset,
                        "subset_status": (
                            "UNAVAILABLE: baseline subset classification missing or incomplete"
                        ),
                        "n_seeds": len(group),
                        "comparison_budget": group[0].comparison_budget,
                        "horizon_scope": group[0].horizon_scope,
                        **{
                            key: math.nan
                            for key in (
                                "baseline_raw_median",
                                "baseline_raw_q1",
                                "baseline_raw_q3",
                                "baseline_weighted_median",
                                "baseline_weighted_q1",
                                "baseline_weighted_q3",
                                "global_best_f1_final_median",
                                "global_best_f1_final_q1",
                                "global_best_f1_final_q3",
                                "global_best_f1_analysis_horizon_median",
                                "global_best_f1_analysis_horizon_q1",
                                "global_best_f1_analysis_horizon_q3",
                                "repaired_per_seed_median",
                                "repaired_per_seed_q1",
                                "repaired_per_seed_q3",
                                "repair_rate_pooled",
                                "repair_rate_wilson_low",
                                "repair_rate_wilson_high",
                                "mean_seed_repair_rate",
                                "seed_rate_bootstrap_low",
                                "seed_rate_bootstrap_high",
                            )
                        },
                        "repair_successes_pooled": "",
                        "movable_observations_pooled": "",
                        "rate_inference_note": (
                            "not computed without complete baseline subset labels"
                        ),
                    }
                )
                continue
            baseline_raw = [
                sum(
                    outcome.baseline.raw_count
                    for outcome in run.budget_outcomes
                    if _subset_match(outcome, subset)
                )
                for run in group
            ]
            baseline_weighted = [
                sum(
                    outcome.baseline.weighted_score
                    for outcome in run.budget_outcomes
                    if _subset_match(outcome, subset)
                )
                for run in group
            ]
            br_med, br_q1, br_q3 = _median_iqr(baseline_raw)
            bw_med, bw_q1, bw_q3 = _median_iqr(baseline_weighted)
            summaries = [run.task_summaries_budget[subset] for run in group]
            repaired = [summary["n_repaired"] for summary in summaries]
            rep_med, rep_q1, rep_q3 = _median_iqr(repaired)
            successes = sum(summary["n_repaired"] for summary in summaries)
            denominator = sum(summary["n_movable"] for summary in summaries)
            rate, lo, hi = stats_helpers.wilson_ci(successes, denominator)
            persistent_drift = subset == "persistent" and any(
                warning.startswith("persistent-baseline drift:")
                for run in group
                for warning in run.subset_warnings
            )
            seed_rates = [
                float(summary["repair_rate"])
                for summary in summaries
                if isinstance(summary["repair_rate"], (int, float))
                and math.isfinite(float(summary["repair_rate"]))
            ]
            seed_rate_mean, seed_rate_low, seed_rate_high = _seed_bootstrap_ci(seed_rates)
            rows.append(
                {
                    "language": language,
                    "optimizer": optimizer,
                    "subset": subset,
                    "subset_status": (
                        "AVAILABLE_WITH_CAUTION: persistent labels drift from final baseline"
                        if persistent_drift
                        else "AVAILABLE"
                    ),
                    "n_seeds": len(group),
                    "comparison_budget": group[0].comparison_budget,
                    "horizon_scope": group[0].horizon_scope,
                    "baseline_raw_median": br_med,
                    "baseline_raw_q1": br_q1,
                    "baseline_raw_q3": br_q3,
                    "baseline_weighted_median": bw_med,
                    "baseline_weighted_q1": bw_q1,
                    "baseline_weighted_q3": bw_q3,
                    "global_best_f1_final_median": final_med,
                    "global_best_f1_final_q1": final_q1,
                    "global_best_f1_final_q3": final_q3,
                    "global_best_f1_analysis_horizon_median": budget_med,
                    "global_best_f1_analysis_horizon_q1": budget_q1,
                    "global_best_f1_analysis_horizon_q3": budget_q3,
                    "repaired_per_seed_median": rep_med,
                    "repaired_per_seed_q1": rep_q1,
                    "repaired_per_seed_q3": rep_q3,
                    "repair_successes_pooled": successes,
                    "movable_observations_pooled": denominator,
                    "repair_rate_pooled": rate,
                    "repair_rate_wilson_low": lo,
                    "repair_rate_wilson_high": hi,
                    "mean_seed_repair_rate": seed_rate_mean,
                    "seed_rate_bootstrap_low": seed_rate_low,
                    "seed_rate_bootstrap_high": seed_rate_high,
                    "rate_inference_note": (
                        (
                            "seed-level bootstrap unavailable with fewer than 2 eligible seeds; "
                            if len(seed_rates) < 2
                            else "seed-level bootstrap is primary; "
                        )
                        + "pooled Wilson is descriptive because task observations "
                        "repeat across seeds"
                    ),
                }
            )
    return rows


def rq1_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    p_values: list[float | None] = []
    for run in runs:
        for subset in ("full", "persistent", "variable"):
            if subset != "full" and not run.subset_classification_complete:
                continue
            outcomes = [
                outcome
                for outcome in run.budget_outcomes
                if _subset_match(outcome, subset) and outcome.movable
            ]
            baseline = [outcome.baseline.weighted_score for outcome in outcomes]
            treatment = [outcome.best.weighted_score for outcome in outcomes]
            wilcoxon = stats_helpers.wilcoxon_paired(baseline, treatment)
            mcnemar = stats_helpers.mcnemar_binary(
                [outcome.baseline.vulnerable for outcome in outcomes],
                [outcome.best.vulnerable for outcome in outcomes],
            )
            fixed = sum(outcome.repaired_to_zero for outcome in outcomes)
            newly_vulnerable = sum(
                (not outcome.baseline.vulnerable) and outcome.best.vulnerable
                for outcome in outcomes
            )
            discordant = fixed + newly_vulnerable
            matched_flip_effect = (
                (fixed - newly_vulnerable) / discordant if discordant else math.nan
            )
            row = {
                "run": run.health.label,
                "language": run.language,
                "optimizer": run.optimizer,
                "seed": run.seed,
                "subset": subset,
                "comparison_budget": run.comparison_budget,
                "horizon_scope": run.horizon_scope,
                "n_tasks": len(outcomes),
                "wilcoxon_stat": wilcoxon.statistic,
                "wilcoxon_p": wilcoxon.p,
                "wilcoxon_note": wilcoxon.note,
                "paired_rank_biserial": paired_rank_biserial(baseline, treatment),
                "mcnemar_stat": mcnemar.statistic,
                "mcnemar_p": mcnemar.p,
                "mcnemar_note": mcnemar.note,
                "matched_flip_effect": matched_flip_effect,
                "repaired_to_zero": fixed,
                "test_validity": "DESCRIPTIVE_ONLY_POST_SELECTION",
                "inference_note": (
                    "per-task best is selected after search with the baseline retained "
                    "as an oracle floor, so worsening/new vulnerability is structurally "
                    "prevented; p-values are descriptive only and fresh pre-specified "
                    "Stage-2 replicates are required for generalization"
                ),
            }
            rows.append(row)
            p_values.extend([wilcoxon.p, mcnemar.p])
    adjusted = benjamini_hochberg(p_values)
    cursor = 0
    for row in rows:
        row["wilcoxon_p_bh"] = adjusted[cursor]
        row["mcnemar_p_bh"] = adjusted[cursor + 1]
        cursor += 2
    return rows


def rq3_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    """Primary unpaired MWU/A12 plus an explicit matched-seed sensitivity.

    The handoff specifies unpaired seeds, while the runner uses common random
    seeds and a shared sampler for the opening draws. Both views are emitted so
    the inferential-design disagreement remains visible rather than being
    silently resolved by code.
    """
    rows: list[dict[str, Any]] = []
    p_values: list[float | None] = []
    paired_p_values: list[float | None] = []
    for language in sorted({run.language for run in runs}):
        ea = [run for run in runs if run.language == language and run.optimizer == "ea"]
        random_runs = [
            run for run in runs if run.language == language and run.optimizer == "random_search"
        ]
        if not ea or not random_runs:
            continue
        metrics: list[tuple[str, str, list[float], list[float]]] = [
            (
                "best_f1",
                "full",
                [run.best_f1_budget for run in ea],
                [run.best_f1_budget for run in random_runs],
            )
        ]
        for subset in ("full", "persistent", "variable"):
            if subset != "full" and not all(
                run.subset_classification_complete for run in ea + random_runs
            ):
                continue
            metrics.extend(
                [
                    (
                        "tasks_repaired_to_zero",
                        subset,
                        [float(run.task_summaries_budget[subset]["n_repaired"]) for run in ea],
                        [
                            float(run.task_summaries_budget[subset]["n_repaired"])
                            for run in random_runs
                        ],
                    ),
                    (
                        "weighted_reduction",
                        subset,
                        [
                            float(run.task_summaries_budget[subset]["weighted_reduction"])
                            for run in ea
                        ],
                        [
                            float(run.task_summaries_budget[subset]["weighted_reduction"])
                            for run in random_runs
                        ],
                    ),
                ]
            )
        for metric, subset, ea_values, random_values in metrics:
            if len(ea_values) < 2 or len(random_values) < 2:
                mwu_stat = None
                mwu_p = None
                mwu_note = "insufficient seeds: need at least 2 runs per arm"
            else:
                mwu = stats_helpers.mann_whitney_u(ea_values, random_values)
                mwu_stat = mwu.statistic
                mwu_p = mwu.p
                mwu_note = mwu.note
            a12, magnitude = stats_helpers.vargha_delaney_a12(ea_values, random_values)
            a12_low, a12_high = _bootstrap_a12_ci(ea_values, random_values)
            ea_by_seed = {run.seed: run for run in ea}
            random_by_seed = {run.seed: run for run in random_runs}
            matched_seeds = sorted(
                set(ea_by_seed) & set(random_by_seed),
                key=_seed_sort_key,
            )

            def value_for(run: RunAnalysis) -> float:
                if metric == "best_f1":
                    return run.best_f1_budget
                key = "n_repaired" if metric == "tasks_repaired_to_zero" else "weighted_reduction"
                return float(run.task_summaries_budget[subset][key])

            paired_deltas = [
                value_for(ea_by_seed[seed]) - value_for(random_by_seed[seed])
                for seed in matched_seeds
            ]
            if len(matched_seeds) < 2:
                sign_stat = None
                sign_p = None
                sign_note = "insufficient matched seeds: need at least 2 pairs"
            else:
                sign = stats_helpers.sign_test(paired_deltas)
                sign_stat = sign.statistic
                sign_p = sign.p
                sign_note = sign.note
            positive = sum(delta > 0 for delta in paired_deltas)
            negative = sum(delta < 0 for delta in paired_deltas)
            paired_sign_effect = (
                (positive - negative) / (positive + negative)
                if len(matched_seeds) >= 2 and positive + negative
                else math.nan
            )
            row = {
                "language": language,
                "subset": subset,
                "metric": metric,
                "comparison_budget": min(run.comparison_budget for run in ea + random_runs),
                "horizon_scope": "cross_arm_common",
                "n_ea": len(ea_values),
                "n_random": len(random_values),
                "ea_values": ea_values,
                "random_values": random_values,
                "mwu_stat": mwu_stat,
                "mwu_p": mwu_p,
                "mwu_note": mwu_note,
                "a12_ea_vs_random": a12,
                "a12_bootstrap_low": a12_low,
                "a12_bootstrap_high": a12_high,
                "a12_bootstrap_note": (
                    "insufficient seeds for a bootstrap interval"
                    if len(ea_values) < 2 or len(random_values) < 2
                    else "independent-sample percentile bootstrap"
                ),
                "a12_magnitude": magnitude,
                "matched_seed_n": len(matched_seeds),
                "matched_seed_deltas": paired_deltas,
                "paired_sign_stat": sign_stat,
                "paired_sign_p": sign_p,
                "paired_sign_effect": paired_sign_effect,
                "paired_sign_note": sign_note,
                "design_status": "UNRESOLVED: handoff says unpaired; runner uses matched seeds/CRN",
            }
            rows.append(row)
            p_values.append(mwu_p)
            paired_p_values.append(sign_p)
    mwu_adjusted = benjamini_hochberg(p_values)
    paired_adjusted = benjamini_hochberg(paired_p_values)
    for row, mwu_value, paired_value in zip(rows, mwu_adjusted, paired_adjusted):
        row["mwu_p_bh"] = mwu_value
        row["paired_sign_p_bh"] = paired_value
    return rows


def _bootstrap_a12_ci(
    first: Sequence[float],
    second: Sequence[float],
    *,
    n_boot: int = 10_000,
    seed: int = 0,
) -> tuple[float, float]:
    """Independent-sample percentile bootstrap interval for A12."""
    first_values = [float(value) for value in first]
    second_values = [float(value) for value in second]
    if not first_values or not second_values:
        return (math.nan, math.nan)

    def estimate(a: Sequence[float], b: Sequence[float]) -> float:
        wins = sum(x > y for x in a for y in b)
        ties = sum(x == y for x in a for y in b)
        return (wins + 0.5 * ties) / (len(a) * len(b))

    if len(first_values) < 2 or len(second_values) < 2:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    estimates = []
    for _ in range(n_boot):
        sampled_first = rng.choices(first_values, k=len(first_values))
        sampled_second = rng.choices(second_values, k=len(second_values))
        estimates.append(estimate(sampled_first, sampled_second))
    return (_quantile(estimates, 0.025), _quantile(estimates, 0.975))


def rq3_friedman_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    """Three-condition matched-seed sensitivity: baseline, EA-best, random-best.

    Friedman is only defined for related blocks. The experiment runner uses the
    same seed values and common opening samples, but the handoff separately calls
    EA/random unpaired. This table therefore stays a labelled sensitivity
    analysis and does not silently settle that design contradiction.
    """
    rows: list[dict[str, Any]] = []
    p_values: list[float | None] = []
    for language in sorted({run.language for run in runs}):
        ea_by_seed = {
            run.seed: run for run in runs if run.language == language and run.optimizer == "ea"
        }
        random_by_seed = {
            run.seed: run
            for run in runs
            if run.language == language and run.optimizer == "random_search"
        }
        if not ea_by_seed or not random_by_seed:
            continue
        matched_seeds = sorted(
            set(ea_by_seed) & set(random_by_seed),
            key=_seed_sort_key,
        )
        usable_seeds: list[str] = []
        baseline_values: list[float] = []
        ea_values: list[float] = []
        random_values: list[float] = []
        baseline_mismatch_seeds: list[str] = []
        for seed in matched_seeds:
            ea_run = ea_by_seed[seed]
            random_run = random_by_seed[seed]
            ea_baseline = sum(prompt.weighted_score for prompt in ea_run.baseline.values())
            random_baseline = sum(prompt.weighted_score for prompt in random_run.baseline.values())
            if not _baseline_results_match(ea_run.baseline, random_run.baseline):
                baseline_mismatch_seeds.append(seed)
                continue
            usable_seeds.append(seed)
            baseline_values.append(ea_baseline)
            ea_values.append(ea_baseline - ea_run.best_f1_budget)
            random_values.append(random_baseline - random_run.best_f1_budget)
        test = stats_helpers.friedman_test(baseline_values, ea_values, random_values)
        kendall_w = (
            float(test.statistic) / (len(usable_seeds) * 2)
            if test.statistic is not None and usable_seeds
            else math.nan
        )
        row = {
            "language": language,
            "comparison_budget": min(
                (run.comparison_budget for run in [*ea_by_seed.values(), *random_by_seed.values()]),
                default=None,
            ),
            "horizon_scope": "cross_arm_common",
            "matched_seed_n": len(matched_seeds),
            "usable_block_n": len(usable_seeds),
            "usable_seeds": usable_seeds,
            "baseline_mismatch_seeds": baseline_mismatch_seeds,
            "baseline_weighted_values": baseline_values,
            "ea_best_weighted_values": ea_values,
            "random_best_weighted_values": random_values,
            "baseline_weighted_median": (median(baseline_values) if baseline_values else math.nan),
            "ea_best_weighted_median": median(ea_values) if ea_values else math.nan,
            "random_best_weighted_median": (median(random_values) if random_values else math.nan),
            "friedman_stat": test.statistic,
            "friedman_p": test.p,
            "friedman_note": test.note,
            "kendall_w": kendall_w,
            "test_validity": "DESCRIPTIVE_ONLY_POST_SELECTION",
            "design_status": (
                "PAIRED-SEED SENSITIVITY ONLY: handoff also specifies an "
                "unpaired EA/random primary analysis"
            ),
            "inference_note": (
                "EA/random endpoints are best-of-budget selections from the same "
                "Stage-1 search outputs used for estimation; Friedman is a descriptive "
                "matched-block sensitivity, not confirmatory evidence"
            ),
        }
        rows.append(row)
        p_values.append(test.p)
    for row, adjusted in zip(rows, benjamini_hochberg(p_values)):
        row["friedman_p_bh"] = adjusted
    return rows


def rq2_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    aggregates: dict[tuple[str, str, str], list[tuple[RunAnalysis, dict[str, Any]]]] = defaultdict(
        list
    )
    for run in runs:
        if run.optimizer != "ea":
            continue
        for row in run.operator_rows:
            aggregates[(run.language, row["family"], row["operator"])].append((run, row))
    output: list[dict[str, Any]] = []
    for (language, family, operator), run_rows in sorted(aggregates.items()):
        rows = [row for _, row in run_rows]
        evaluated = [row for row in rows if row["evaluated"]]
        improving = sum(row["security_improving"] for row in evaluated)
        proposal_rate, proposal_lo, proposal_hi = stats_helpers.wilson_ci(improving, len(rows))
        evaluated_rate, evaluated_lo, evaluated_hi = stats_helpers.wilson_ci(
            improving, len(evaluated)
        )
        deltas = [float(row["delta_f1"]) for row in evaluated if row["delta_f1"] is not None]
        mean_delta = sum(deltas) / len(deltas) if deltas else math.nan
        by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run, row in run_rows:
            run_name = run.health.label
            by_run[run_name].append(row)
        seed_rates = []
        seed_mean_deltas = []
        for rows_for_run in by_run.values():
            evaluated_for_run = [row for row in rows_for_run if row["evaluated"]]
            if rows_for_run:
                seed_rates.append(
                    sum(row["security_improving"] for row in rows_for_run) / len(rows_for_run)
                )
            if evaluated_for_run:
                run_deltas = [
                    float(row["delta_f1"])
                    for row in evaluated_for_run
                    if row["delta_f1"] is not None
                ]
                if run_deltas:
                    seed_mean_deltas.append(sum(run_deltas) / len(run_deltas))
        seed_mean, seed_lo, seed_hi = _seed_bootstrap_ci(seed_rates)
        mean_seed_delta, mean_lo, mean_hi = _seed_bootstrap_ci(seed_mean_deltas)
        output.append(
            {
                "language": language,
                "family": family,
                "operator": operator,
                "comparison_budget": min(run.comparison_budget for run, _ in run_rows),
                "horizon_scope": (
                    "cross_arm_common"
                    if all(run.horizon_scope == "cross_arm_common" for run, _ in run_rows)
                    else "available_runs_minimum"
                ),
                "n_runs_observed": len(seed_rates),
                "proposals": len(rows),
                "identities": sum(row["identity"] for row in rows),
                "evaluated": len(evaluated),
                "security_improving": improving,
                "accepted_and_security_improving": sum(
                    row["accepted"] and row["security_improving"] for row in evaluated
                ),
                "proposal_improving_rate": proposal_rate,
                "proposal_wilson_low": proposal_lo,
                "proposal_wilson_high": proposal_hi,
                "evaluated_candidate_improving_rate": evaluated_rate,
                "evaluated_candidate_wilson_low": evaluated_lo,
                "evaluated_candidate_wilson_high": evaluated_hi,
                "mean_seed_improving_rate": seed_mean,
                "seed_rate_bootstrap_low": seed_lo,
                "seed_rate_bootstrap_high": seed_hi,
                "archive_accepted": sum(row["accepted"] for row in evaluated),
                "pooled_mean_delta_f1": mean_delta,
                "mean_seed_delta_f1": mean_seed_delta,
                "mean_seed_delta_f1_bootstrap_low": mean_lo,
                "mean_seed_delta_f1_bootstrap_high": mean_hi,
                "credit_scope": "EA phase local move; last proposed text mutator",
                "inference_note": (
                    (
                        "seed-level bootstrap unavailable with fewer than 2 observed runs; "
                        if len(seed_rates) < 2
                        else "seed-level bootstrap over proposal-level rates is primary; "
                    )
                    + "proposal/evaluated-candidate Wilson intervals are descriptive "
                    "because attempts are nested within runs/chromosomes/rules"
                ),
            }
        )
    return output


def rq2_family_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    """Run-balanced RQ2 aggregates over mutator families."""
    grouped: dict[tuple[str, str], list[tuple[RunAnalysis, dict[str, Any]]]] = defaultdict(list)
    for run in runs:
        if run.optimizer != "ea":
            continue
        for row in run.operator_rows:
            grouped[(run.language, str(row["family"]))].append((run, row))
    output: list[dict[str, Any]] = []
    for (language, family), run_rows in sorted(grouped.items()):
        rows = [row for _, row in run_rows]
        evaluated = [row for row in rows if row["evaluated"]]
        improving = sum(row["security_improving"] for row in evaluated)
        proposal_rate, proposal_low, proposal_high = stats_helpers.wilson_ci(improving, len(rows))
        evaluated_rate, evaluated_low, evaluated_high = stats_helpers.wilson_ci(
            improving, len(evaluated)
        )
        by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run, row in run_rows:
            by_run[run.seed].append(row)
        seed_rates: list[float] = []
        seed_mean_deltas: list[float] = []
        for run_family_rows in by_run.values():
            seed_rates.append(
                sum(row["security_improving"] for row in run_family_rows) / len(run_family_rows)
            )
            deltas = [
                float(row["delta_f1"])
                for row in run_family_rows
                if row["evaluated"] and row["delta_f1"] is not None
            ]
            if deltas:
                seed_mean_deltas.append(sum(deltas) / len(deltas))
        seed_rate, seed_rate_low, seed_rate_high = _seed_bootstrap_ci(seed_rates)
        seed_delta, seed_delta_low, seed_delta_high = _seed_bootstrap_ci(seed_mean_deltas)
        output.append(
            {
                "language": language,
                "family": family,
                "comparison_budget": min(run.comparison_budget for run, _ in run_rows),
                "horizon_scope": (
                    "cross_arm_common"
                    if all(run.horizon_scope == "cross_arm_common" for run, _ in run_rows)
                    else "available_runs_minimum"
                ),
                "n_runs_observed": len(by_run),
                "proposals": len(rows),
                "identities": sum(row["identity"] for row in rows),
                "evaluated": len(evaluated),
                "security_improving": improving,
                "accepted_and_security_improving": sum(
                    row["accepted"] and row["security_improving"] for row in evaluated
                ),
                "proposal_improving_rate": proposal_rate,
                "proposal_wilson_low": proposal_low,
                "proposal_wilson_high": proposal_high,
                "evaluated_candidate_improving_rate": evaluated_rate,
                "evaluated_candidate_wilson_low": evaluated_low,
                "evaluated_candidate_wilson_high": evaluated_high,
                "mean_seed_improving_rate": seed_rate,
                "seed_rate_bootstrap_low": seed_rate_low,
                "seed_rate_bootstrap_high": seed_rate_high,
                "mean_seed_delta_f1": seed_delta,
                "mean_seed_delta_f1_bootstrap_low": seed_delta_low,
                "mean_seed_delta_f1_bootstrap_high": seed_delta_high,
                "inference_note": (
                    (
                        "bootstrap interval unavailable with fewer than 2 observed runs; "
                        if len(by_run) < 2
                        else ""
                    )
                    + "run-balanced family aggregate at the labelled analysis "
                    "horizon; descriptive because proposals are nested"
                ),
            }
        )
    return output


def language_comparison_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    """Descriptive, denominator-normalized language summary.

    Python and Java use different task populations. This output supports a
    low-headroom comparison without treating language as a randomized factor.
    """
    rows: list[dict[str, Any]] = []
    for (language, optimizer), group in sorted(config_groups(runs).items()):
        for subset in ("full", "persistent", "variable"):
            if subset != "full" and not all(run.subset_classification_complete for run in group):
                continue
            repair_rates: list[float] = []
            normalized_weighted_reductions: list[float] = []
            for run in group:
                summary = run.task_summaries_budget[subset]
                rate = _number(summary.get("repair_rate"))
                if rate is not None:
                    repair_rates.append(rate)
                outcomes = [
                    outcome
                    for outcome in run.budget_outcomes
                    if _subset_match(outcome, subset) and outcome.movable
                ]
                baseline_total = sum(outcome.baseline.weighted_score for outcome in outcomes)
                reduction_total = sum(outcome.delta_weighted for outcome in outcomes)
                if baseline_total > 0:
                    normalized_weighted_reductions.append(reduction_total / baseline_total)
            rate_mean, rate_low, rate_high = _seed_bootstrap_ci(repair_rates)
            reduction_mean, reduction_low, reduction_high = _seed_bootstrap_ci(
                normalized_weighted_reductions
            )
            rows.append(
                {
                    "language": language,
                    "optimizer": optimizer,
                    "subset": subset,
                    "n_seeds": len(group),
                    "comparison_budget": group[0].comparison_budget,
                    "horizon_scope": group[0].horizon_scope,
                    "mean_seed_repair_rate": rate_mean,
                    "repair_rate_bootstrap_low": rate_low,
                    "repair_rate_bootstrap_high": rate_high,
                    "mean_normalized_weighted_reduction": reduction_mean,
                    "normalized_reduction_bootstrap_low": reduction_low,
                    "normalized_reduction_bootstrap_high": reduction_high,
                    "comparison_scope": (
                        "DESCRIPTIVE_ONLY: languages use different task "
                        "populations and are not randomized conditions"
                        + (
                            "; bootstrap interval unavailable with fewer than 2 seeds"
                            if len(group) < 2
                            else ""
                        )
                    ),
                }
            )
    return rows


def best_chromosome_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        front = run.final_front_best
        genes = front.get("genes") if isinstance(front.get("genes"), dict) else {}
        mutators = sorted(
            {
                str(mutator)
                for gene in genes.values()
                if isinstance(gene, dict)
                for mutator in (gene.get("mutation_path") or [])
            }
        )
        if run.optimizer != "ea":
            front_note = "not applicable: random search has no Pareto archive"
        elif front.get("source") == "origin":
            front_note = "no mutated repair survives final front"
        else:
            front_note = "final surviving front; may differ from best-ever after restart"
        rows.append(
            {
                "run": run.health.label,
                "language": run.language,
                "optimizer": run.optimizer,
                "seed": run.seed,
                "best_ever_f1": run.best_f1_final,
                "best_ever_iter": run.best_f1_iter,
                "best_ever_phase": run.best_f1_phase,
                "final_front_source": front.get("source", "not_applicable"),
                "final_front_cid": front.get("cid"),
                "final_front_f1": front.get("f1"),
                "final_front_f2": front.get("f2"),
                "final_front_f3": front.get("f3"),
                "n_rules_mutated": len(front.get("mutated_rule_ids") or []),
                "mutated_rule_ids": front.get("mutated_rule_ids") or [],
                "mutators": mutators,
                "order_priority": front.get("order_priority") or {},
                "parsimony": (
                    -float(front["f3"]) if _number(front.get("f3")) is not None else None
                ),
                "note": front_note,
            }
        )
    return rows


def best_chromosome_per_config_rows(
    runs: Sequence[RunAnalysis],
) -> list[dict[str, Any]]:
    """Select one explicitly labelled surviving-front representative per config."""
    per_run = best_chromosome_rows(runs)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in per_run:
        grouped[(str(row["language"]), str(row["optimizer"]))].append(row)

    output: list[dict[str, Any]] = []
    for (language, optimizer), rows in sorted(grouped.items()):
        if optimizer != "ea":
            output.append(
                {
                    "language": language,
                    "optimizer": optimizer,
                    "n_runs": len(rows),
                    "representative_run": None,
                    "representative_seed": None,
                    "best_ever_f1_max": max(float(row["best_ever_f1"]) for row in rows),
                    "final_front_f1": None,
                    "final_front_f2": None,
                    "final_front_f3": None,
                    "n_rules_mutated": None,
                    "mutated_rule_ids": [],
                    "mutators": [],
                    "parsimony": None,
                    "fidelity": None,
                    "order_priority": {},
                    "selection_basis": (
                        "not applicable: random search has no persistent Pareto archive"
                    ),
                }
            )
            continue

        eligible = [
            row
            for row in rows
            if all(
                _number(row.get(key)) is not None
                for key in ("final_front_f1", "final_front_f2", "final_front_f3")
            )
        ]
        if not eligible:
            representative: dict[str, Any] | None = None
        else:
            representative = max(
                eligible,
                key=lambda row: (
                    float(row["final_front_f1"]),
                    float(row["final_front_f2"]) + float(row["final_front_f3"]),
                    str(row["seed"]),
                ),
            )
        output.append(
            {
                "language": language,
                "optimizer": optimizer,
                "n_runs": len(rows),
                "representative_run": (
                    representative.get("run") if representative is not None else None
                ),
                "representative_seed": (
                    representative.get("seed") if representative is not None else None
                ),
                "best_ever_f1_max": max(float(row["best_ever_f1"]) for row in rows),
                "final_front_f1": (
                    representative.get("final_front_f1") if representative is not None else None
                ),
                "final_front_f2": (
                    representative.get("final_front_f2") if representative is not None else None
                ),
                "final_front_f3": (
                    representative.get("final_front_f3") if representative is not None else None
                ),
                "n_rules_mutated": (
                    representative.get("n_rules_mutated") if representative is not None else None
                ),
                "mutated_rule_ids": (
                    representative.get("mutated_rule_ids") if representative is not None else []
                ),
                "mutators": (representative.get("mutators") if representative is not None else []),
                "parsimony": (
                    representative.get("parsimony") if representative is not None else None
                ),
                "fidelity": (
                    representative.get("final_front_f2") if representative is not None else None
                ),
                "order_priority": (
                    representative.get("order_priority") if representative is not None else {}
                ),
                "selection_basis": (
                    "best surviving final-front f1 across healthy seeds; ties use f2+f3; "
                    "best-ever search f1 is reported separately because restarts can "
                    "remove an earlier candidate"
                    if representative is not None
                    else "no eligible surviving-front representative"
                ),
            }
        )
    return output


def cost_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        summary = run.health.summary
        cache = summary.get("eval_cache_stats")
        cache = cache if isinstance(cache, dict) else None
        hits = cache.get("hits") if cache is not None else None
        misses = cache.get("misses") if cache is not None else None
        pool_stats = summary.get("pool_arm_stats")
        restarts = (
            pool_stats.get("restart_reason_counts")
            if run.optimizer == "ea" and isinstance(pool_stats, dict)
            else None
        )
        horizon_records = [
            row
            for row in run.health.iterations
            if isinstance(row.get("iter"), int) and row["iter"] <= run.comparison_budget
        ]
        horizon_evaluated = [row for row in horizon_records if row.get("budget_consumed") is True]
        last_horizon = (
            max(horizon_evaluated, key=lambda row: int(row["iter"])) if horizon_evaluated else {}
        )
        baseline_misses = run.health.n_baseline_records
        horizon_cache_hits = sum(int(row["n_prompts_reused"]) for row in horizon_evaluated)
        horizon_cache_misses = baseline_misses + sum(
            int(row["n_prompts_rerun"]) for row in horizon_evaluated
        )
        horizon_restart_counts: Counter[str] = Counter()
        for record in horizon_records:
            selection_meta = record.get("selection_meta")
            restart_events = (
                selection_meta.get("restarts_this_iter", [])
                if isinstance(selection_meta, dict)
                else []
            )
            if isinstance(restart_events, list):
                for event in restart_events:
                    if isinstance(event, dict) and event.get("reason"):
                        horizon_restart_counts[str(event["reason"])] += 1
        rows.append(
            {
                "run": run.health.label,
                "language": run.language,
                "optimizer": run.optimizer,
                "seed": run.seed,
                "n_evaluated": run.health.n_evaluated,
                "n_proposals": run.health.n_proposals,
                "n_identity": run.health.n_identity,
                "candidate_evaluation_horizon": run.comparison_budget,
                "horizon_scope": run.horizon_scope,
                "proposals_at_horizon": len(horizon_records),
                "identity_proposals_at_horizon": sum(
                    record.get("mutation_identity") is True for record in horizon_records
                ),
                "codegen_calls_at_horizon": last_horizon.get("llm_calls_total"),
                "codegen_input_tokens_at_horizon": last_horizon.get("input_tokens_total"),
                "codegen_output_tokens_at_horizon": last_horizon.get("output_tokens_total"),
                "eval_cache_hits_at_horizon": horizon_cache_hits,
                "eval_cache_misses_at_horizon": horizon_cache_misses,
                "eval_cache_hit_rate_at_horizon": (
                    horizon_cache_hits / (horizon_cache_hits + horizon_cache_misses)
                    if horizon_cache_hits + horizon_cache_misses
                    else math.nan
                ),
                "restart_stagnation_at_horizon": (
                    horizon_restart_counts.get("stagnation", 0) if run.optimizer == "ea" else None
                ),
                "restart_exhausted_at_horizon": (
                    horizon_restart_counts.get("exhausted", 0) if run.optimizer == "ea" else None
                ),
                "total_time_seconds": summary.get("total_time_seconds"),
                "codegen_calls_full_run": summary.get("total_llm_calls"),
                "codegen_input_tokens_full_run": summary.get("total_input_tokens"),
                "codegen_output_tokens_full_run": summary.get("total_output_tokens"),
                "eval_cache_hits": hits,
                "eval_cache_misses": misses,
                "eval_cache_hit_rate": (
                    hits / (hits + misses)
                    if isinstance(hits, int) and isinstance(misses, int) and hits + misses
                    else math.nan
                ),
                "restart_stagnation": (
                    restarts.get("stagnation", 0) if isinstance(restarts, dict) else None
                ),
                "restart_exhausted": (
                    restarts.get("exhausted", 0) if isinstance(restarts, dict) else None
                ),
                "llm_accounting_scope": (
                    "code-generation calls only; excludes direct LLM-mutator "
                    "backend.generate calls and is not total LLM compute"
                ),
            }
        )
    return rows


def cwe_check_rows(
    runs: Sequence[RunAnalysis],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cwe_agg: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    check_agg: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    movable_by_stratum: Counter[tuple[str, str]] = Counter()
    for run in runs:
        for outcome in run.budget_outcomes:
            if not outcome.movable:
                continue
            stratum = (run.language, run.optimizer)
            movable_by_stratum[stratum] += 1
            key = (run.language, run.optimizer, outcome.cwe_id)
            cwe_agg[key]["movable"] += 1
            cwe_agg[key]["reduced"] += int(outcome.delta_raw > 0)
            cwe_agg[key]["repaired"] += int(outcome.repaired_to_zero)
            removed = outcome.baseline.check_ids - outcome.best.check_ids
            added = outcome.best.check_ids - outcome.baseline.check_ids
            for check_id in outcome.baseline.check_ids:
                check_agg[(run.language, run.optimizer, check_id)]["baseline_present"] += 1
            for check_id in removed:
                check_agg[(run.language, run.optimizer, check_id)]["removed"] += 1
            for check_id in added:
                check_agg[(run.language, run.optimizer, check_id)]["added"] += 1
    cwe_rows = []
    for (language, optimizer, cwe), counts in sorted(cwe_agg.items()):
        movable = counts["movable"]
        cwe_rows.append(
            {
                "language": language,
                "optimizer": optimizer,
                "subset_scope": "baseline_vulnerable_movable",
                "cwe_id": cwe,
                "movable": movable,
                "reduced": counts["reduced"],
                "reduced_rate": counts["reduced"] / movable if movable else math.nan,
                "repaired": counts["repaired"],
                "repaired_rate": counts["repaired"] / movable if movable else math.nan,
            }
        )
    check_rows = []
    for (language, optimizer, check_id), counts in sorted(check_agg.items()):
        movable = movable_by_stratum[(language, optimizer)]
        baseline_present = counts["baseline_present"]
        baseline_absent = movable - baseline_present
        check_rows.append(
            {
                "language": language,
                "optimizer": optimizer,
                "subset_scope": "baseline_vulnerable_movable",
                "check_id": check_id,
                "movable_observations": movable,
                "baseline_present": baseline_present,
                "baseline_absent": baseline_absent,
                "removed": counts["removed"],
                "removed_rate": (
                    counts["removed"] / baseline_present if baseline_present else math.nan
                ),
                "added": counts["added"],
                "added_rate": counts["added"] / baseline_absent if baseline_absent else math.nan,
            }
        )
    return cwe_rows, check_rows


def convergence_series(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        best = 0.0
        for row in run.health.iterations:
            if row.get("budget_consumed") is not True:
                continue
            iteration = row.get("iter")
            f1 = _number(row.get("f1"))
            if not isinstance(iteration, int) or f1 is None:
                continue
            best = max(best, f1)
            rows.append(
                {
                    "run": run.health.label,
                    "language": run.language,
                    "optimizer": run.optimizer,
                    "seed": run.seed,
                    "iteration": iteration,
                    "best_f1_so_far": best,
                }
            )
    return rows


def aggregate_convergence(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    raw = convergence_series(runs)
    grouped: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for row in raw:
        grouped[(row["language"], row["optimizer"], row["iteration"])].append(row["best_f1_so_far"])
    rows: list[dict[str, Any]] = []
    for (language, optimizer, iteration), values in sorted(grouped.items()):
        med, q1, q3 = _median_iqr(values)
        rows.append(
            {
                "language": language,
                "optimizer": optimizer,
                "iteration": iteration,
                "n_runs": len(values),
                "median": med,
                "q1": q1,
                "q3": q3,
            }
        )
    return rows


def values_csv(value: Any) -> Any:
    """Stable CSV representation for list/dict-valued report cells."""
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, float) and math.isnan(value):
        return "NA"
    return value
