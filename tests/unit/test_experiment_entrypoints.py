"""Regression checks for experiment-script wiring after entrypoint renames."""

from types import SimpleNamespace

import pytest


def _recorded_args() -> dict:
    """Minimal schema-4 argument payload consumed by the rerun builders."""
    return {
        "backend": "openai",
        "model": "test-model",
        "temperature": 0.25,
        "quantization": "4bit",
        "bnb_compute_dtype": "bfloat16",
        "rules_map": "rules.json",
        "n_cases": 2,
        "iterations": 20,
        "seed": 42,
        "selection": "first",
        "languages": ["python"],
        "mutators": ["synonym_replacement"],
        "optimizer": "ea",
        "objective_direction": "minimize",
        "archive_cap": 6,
        "restart_h": 8,
        "max_depth": 4,
        "random_max_changes": 10,
        "ea_n_mutations": 1,
        "ea_init_samples": 10,
        "ea_injection_every": 10,
        "ea_move": "local",
        "order_move_weight": 0.1,
        "ea_origin_parent": False,
        "enable_validation": True,
        "enable_perplexity": False,
        "enable_eval_cache": True,
        "semgrep_config": "p/security-audit",
        "semgrep_timeout_seconds": 180,
        "semgrep_jobs": 1,
    }


def test_baseline_harness_uses_current_experiment_entrypoint() -> None:
    """The replicate harness must not import the removed legacy module."""
    from scripts.experiments import baseline_harness, run_experiment

    assert baseline_harness.load_prompts_with_rules is run_experiment.load_prompts_with_rules
    assert baseline_harness.create_rule_loader is run_experiment.create_rule_loader
    assert baseline_harness.RULES_DIR == run_experiment.RULES_DIR


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


def test_rerun_api_command_preserves_origin_parent_and_temperature() -> None:
    from scripts.experiments.rerun_from_config import _build_api_command

    cmd = _build_api_command(_recorded_args(), "rerun-output")

    assert cmd[cmd.index("--temperature") + 1] == "0.25"
    # ea_origin_parent=False in the payload ⇒ the negated flag is emitted
    assert "--no-ea-origin-parent" in cmd
    assert "--ea-origin-parent" not in cmd


def test_rerun_slurm_env_preserves_origin_parent_and_dtype() -> None:
    from scripts.experiments.rerun_from_config import _build_slurm_env

    env = _build_slurm_env(_recorded_args())

    assert env["TEMPERATURE"] == "0.25"
    assert env["BNB_COMPUTE_DTYPE"] == "bfloat16"
    assert env["EA_ORIGIN_PARENT"] == "false"


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


def test_search_numeric_knobs_are_validated() -> None:
    import pytest

    from scripts.experiments.run_experiment import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--random-max-changes", "0"])
    with pytest.raises(SystemExit):
        parse_args(["--dry-run", "--order-move-weight", "1.1"])
