"""Regression checks for experiment-script wiring after entrypoint renames."""

from pathlib import Path
from types import SimpleNamespace

import pytest


def _recorded_args() -> dict:
    """Minimal current argument payload consumed by the rerun builders."""
    return {
        "backend": "openai",
        "model": "test-model",
        "temperature": 0.25,
        "quantization": "4bit",
        "bnb_compute_dtype": "bfloat16",
        "rules_map": "rules.json",
        "n_cases": 2,
        "main_loop_budget": 20,
        "seed": 42,
        "selection": "first",
        "languages": ["python"],
        "mutators": ["synonym_replacement"],
        "optimizer": "ea",
        "objective_direction": "minimize",
        "archive_cap": 6,
        "max_depth": 4,
        "random_max_changes": 10,
        "ea_injection_every": 10,
        "order_move_weight": 0.1,
        "prompt_profile": "original_no_language",
        "initialization_bundle": None,
        "enable_validation": True,
        "enable_perplexity": False,
        "enable_eval_cache": True,
        "semgrep_config": "p/security-audit",
        "semgrep_timeout_seconds": 180,
        "semgrep_jobs": 1,
    }


def test_replicate_runner_uses_current_experiment_entrypoint() -> None:
    from scripts.experiments import run_experiment, run_replicates

    assert run_replicates.load_prompts_with_rules is run_experiment.load_prompts_with_rules
    assert run_replicates.create_rule_loader is run_experiment.create_rule_loader
    assert run_replicates.RULES_DIR == run_experiment.RULES_DIR


def test_mutator_dependency_preflight_aborts_before_search(monkeypatch) -> None:
    from scripts.experiments import run_experiment
    from src.mutation.rule_based import SynonymReplacementMutator

    def unavailable() -> None:
        raise RuntimeError("test-only missing corpus")

    monkeypatch.setattr(
        SynonymReplacementMutator,
        "validate_runtime_dependencies",
        staticmethod(unavailable),
    )
    args = SimpleNamespace(
        mutators=["synonym_replacement"],
        seed=42,
        backend="delftblue",
        dry_run=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_experiment.create_pool(args, backend=object())

    assert exc_info.value.code == 1


def test_rerun_api_command_preserves_final_budget_profile_and_temperature() -> None:
    from scripts.experiments.rerun_from_config import _build_api_command

    cmd = _build_api_command(_recorded_args(), "rerun-output")

    assert cmd[cmd.index("--temperature") + 1] == "0.25"
    assert cmd[cmd.index("--main-loop-budget") + 1] == "20"
    assert cmd[cmd.index("--prompt-profile") + 1] == "original_no_language"
    assert "--ea-origin-parent" not in cmd
    assert "--restart-h" not in cmd


def test_rerun_slurm_env_preserves_final_budget_profile_and_dtype() -> None:
    from scripts.experiments.rerun_from_config import _build_slurm_env

    env = _build_slurm_env(_recorded_args())

    assert env["TEMPERATURE"] == "0.25"
    assert env["BNB_COMPUTE_DTYPE"] == "bfloat16"
    assert env["MAIN_LOOP_BUDGET"] == "20"
    assert env["PROMPT_PROFILE"] == "original_no_language"
    assert "EA_ORIGIN_PARENT" not in env
    assert env["N_CASES"] == "2"


def test_rerun_full_population_uses_all_sentinel() -> None:
    from scripts.experiments.rerun_from_config import _build_slurm_env

    args = _recorded_args()
    args["n_cases_requested"] = None

    assert _build_slurm_env(args)["N_CASES"] == "all"


def test_rerun_qualification_uses_dedicated_wrapper_contract() -> None:
    from scripts.experiments.rerun_from_config import _build_qualification_slurm_env

    args = _recorded_args()
    args.update(
        {
            "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
            "languages": ["python"],
            "prompt_profile": "original_no_language",
        }
    )

    env = _build_qualification_slurm_env(args)

    assert env["MODEL"] == "qwen"
    assert env["LANGUAGES"] == "python"
    assert env["PROMPT_PROFILE"] == "original_no_language"
    assert env["RULES_MAP"] == "rules.json"


def test_rerun_qualification_api_uses_dedicated_entrypoint() -> None:
    from scripts.experiments.rerun_from_config import (
        _build_qualification_api_command,
    )

    args = _recorded_args()
    args.update(
        {
            "languages": ["python"],
            "prompt_profile": "original_with_language",
        }
    )

    cmd = _build_qualification_api_command(args, "rerun-output")

    assert "scripts/experiments/run_qualification.py" in cmd
    assert cmd[cmd.index("--prompt-profile") + 1] == "original_with_language"
    assert "--iterations" not in cmd


def test_delftblue_llama_run_selects_llama_wrapper() -> None:
    from scripts.experiments.rerun_from_config import (
        _build_slurm_env,
        _slurm_wrapper_for_model,
    )

    args = _recorded_args()
    args.update({
        "backend": "delftblue",
        "model": "meta-llama/Llama-3.3-70B-Instruct",
    })

    wrapper = _slurm_wrapper_for_model(args["model"])
    env = _build_slurm_env(args)

    assert wrapper == "scripts/slurm/slurm_ea_llama70b.sh"
    assert env["TEMPERATURE"] == "0.25"
    assert env["QUANTIZATION"] == "4bit"
    assert env["BNB_COMPUTE_DTYPE"] == "bfloat16"


def test_delftblue_unknown_model_is_rejected_clearly() -> None:
    import pytest

    from scripts.experiments.rerun_from_config import _slurm_wrapper_for_model

    with pytest.raises(ValueError, match="Unsupported DelftBlue model"):
        _slurm_wrapper_for_model("organization/unsupported-model")


@pytest.mark.parametrize(
    "wrapper",
    [
        "scripts/slurm/slurm_ea_qwen32b.sh",
        "scripts/slurm/slurm_ea_llama70b.sh",
    ],
)
def test_delftblue_wrappers_honor_curated_output_base(wrapper: str) -> None:
    text = Path(wrapper).read_text(encoding="utf-8")

    assert 'OUTPUT_BASE=${OUTPUT_BASE:-"$REPO_ROOT/experiments/results"}' in text
    assert 'OUTPUT_DIR="${OUTPUT_BASE}/job${SLURM_JOB_ID}_${STRAT_TAG}_${LANG_TAG}_s${SEED}_${DATE}"' in text
    assert 'RULES_MAP="$REPO_ROOT/rule_maps/qualified/final_search_map_' in text
    assert 'FILTER="$REPO_ROOT/scripts/experiments/filter_semgrep_debug.py"' in text
    assert 'VALIDATOR="$REPO_ROOT/scripts/analyze/validate_search_run.py"' in text


def test_qualification_wrapper_is_full_population_and_self_validating() -> None:
    text = Path("scripts/slurm/slurm_qualification.sh").read_text()

    assert "#SBATCH --time=02:00:00" in text
    assert "run_qualification.py" in text
    assert "PROMPT_PROFILE=${PROMPT_PROFILE:-original_with_language}" in text
    assert '--prompt-profile "$PROMPT_PROFILE"' in text
    assert "--n-cases" not in text
    assert "validate_qualification_run.py" in text
    assert "final_consensus_map_${MODEL}_${LANGUAGES}.json" in text


def test_replicate_runner_defaults_to_frozen_maps_without_fixed_counts() -> None:
    text = Path("scripts/slurm/slurm_replicates.sh").read_text()

    assert "final_search_norules_map_${LANGUAGES}.json" in text
    assert "final_search_map_${MODEL}_${LANGUAGES}.json" in text
    assert "N_CASES=${N_CASES:-}" in text
    assert "SELECTION=${SELECTION:-first}" in text


def test_search_numeric_knobs_are_validated() -> None:
    import pytest

    from scripts.experiments.run_experiment import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--random-max-changes", "0"])
    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--order-move-weight", "1.1"])


def test_qualification_has_a_dedicated_full_population_cli() -> None:
    from scripts.experiments.run_qualification import parse_args

    args = parse_args(
        [
            "--dry-run",
            "--languages",
            "python",
            "--rules-map",
            "map.json",
            "--output-dir",
            "out",
            "--prompt-profile",
            "original_no_language",
        ]
    )
    assert args.temperature == 0.0
    assert args.selection == "first"
    assert args.n_cases is None
    assert args.prompt_profile == "original_no_language"
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--dry-run",
                "--languages",
                "python",
                "--rules-map",
                "map.json",
                "--output-dir",
                "out",
                "--prompt-profile",
                "unknown",
            ]
        )


def test_search_cli_does_not_expose_qualification_mode() -> None:
    from scripts.experiments.run_experiment import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--qualification-only"])
