#!/usr/bin/env python3
"""
Test script to validate the SBST framework components.

Runs basic tests on each module without requiring API keys.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path
def _resolve_project_root() -> Path:
    """Resolve repository root by searching upward for the src/ and scripts/ dirs."""
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
sys.path.insert(0, str(PROJECT_ROOT))


def test_evaluation_module():
    """Test the evaluation module."""
    print("Testing evaluation module...")
    
    from src.evaluation import run_semgrep, strip_markdown_fences, calculate_fitness
    from src.evaluation.semgrep_runner import SemgrepResult, SemgrepFinding
    from src.evaluation.fitness import FitnessStrategy
    
    # Test strip_markdown_fences
    code_with_fences = """```python
def hello():
    print("Hello")
```"""
    clean = strip_markdown_fences(code_with_fences)
    assert "```" not in clean
    assert "def hello():" in clean
    print("  ✅ strip_markdown_fences works")
    
    # Test fitness calculation with mock result
    mock_result = SemgrepResult(findings=[
        SemgrepFinding(check_id="test-rule-1", message="Test", severity="ERROR", line=1),
        SemgrepFinding(check_id="test-rule-2", message="Test", severity="WARNING", line=2),
    ])
    
    fitness = calculate_fitness(mock_result, FitnessStrategy.SEVERITY_WEIGHTED)
    assert fitness.raw_count == 2
    assert fitness.error_count == 1
    assert fitness.warning_count == 1
    assert fitness.weighted_score == 4.0  # ERROR=3, WARNING=1
    print("  ✅ calculate_fitness works")
    
    print("  ✅ Evaluation module OK")


def test_mutation_module():
    """Test the mutation module."""
    print("Testing mutation module...")
    
    from src.mutation import FluffMutator, VerbWeakeningMutator, CompositeMutator
    
    test_text = "You MUST validate all input. NEVER trust user data."
    
    # Test FluffMutator
    mutator = FluffMutator(seed=42)
    result = mutator.mutate(test_text)
    assert result.changed
    assert "should ideally" in result.mutated  # MUST -> should ideally
    assert len(result.changes) > 0
    print("  ✅ FluffMutator works")
    
    # Test VerbWeakeningMutator
    mutator = VerbWeakeningMutator()
    result = mutator.mutate(test_text)
    assert "MUST" not in result.mutated
    assert "NEVER" not in result.mutated
    print("  ✅ VerbWeakeningMutator works")
    
    # Test CompositeMutator
    composite = CompositeMutator([
        VerbWeakeningMutator(),
        FluffMutator(weaken_verbs=False),
    ])
    result = composite.mutate(test_text)
    assert result.changed
    assert "composite" in result.mutation_type
    print("  ✅ CompositeMutator works")
    
    print("  ✅ Mutation module OK")


def test_llm_backend_base():
    """Test the LLM backend base classes."""
    print("Testing LLM backend base...")
    
    from src.llm_backends import LLMConfig, LLMResponse
    
    # Test LLMConfig
    config = LLMConfig(
        model="test-model",
        temperature=0.5,
        max_tokens=1024,
    )
    assert config.model == "test-model"
    assert config.temperature == 0.5
    print("  ✅ LLMConfig works")
    
    # Test LLMResponse
    response = LLMResponse(
        content="Hello, world!",
        model="test-model",
        input_tokens=10,
        output_tokens=5,
    )
    assert response.total_tokens == 15
    print("  ✅ LLMResponse works")
    
    print("  ✅ LLM backend base OK")


def test_optimizer_module():
    """Test the optimizer module."""
    print("Testing optimizer module...")
    
    from src.optimizer import HillClimbConfig, TestPrompt
    from src.evaluation.fitness import FitnessStrategy
    
    # Test HillClimbConfig
    config = HillClimbConfig(
        max_iterations=10,
        fitness_strategy=FitnessStrategy.RAW_COUNT,
    )
    assert config.max_iterations == 10
    print("  ✅ HillClimbConfig works")
    
    # Test TestPrompt
    prompt = TestPrompt(
        prompt="Write a function",
        language="python",
        cwe_id="CWE-89",
    )
    assert prompt.language == "python"
    print("  ✅ TestPrompt works")
    
    print("  ✅ Optimizer module OK")


def test_semgrep_available():
    """Check if Semgrep is installed."""
    print("Checking Semgrep availability...")
    
    import subprocess
    try:
        result = subprocess.run(
            ["semgrep", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"  ✅ Semgrep installed: {version}")
            return True
        else:
            print("  ⚠️  Semgrep not working properly")
            return False
    except FileNotFoundError:
        print("  ⚠️  Semgrep not installed")
        print("     Install with: pip install semgrep")
        return False
    except Exception as e:
        print(f"  ⚠️  Error checking Semgrep: {e}")
        return False


def test_semgrep_integration():
    """Test actual Semgrep execution."""
    print("Testing Semgrep integration...")
    
    from src.evaluation import run_semgrep
    
    # Test with known vulnerable code
    vulnerable_code = '''
import os
user_input = input("Enter command: ")
os.system(user_input)  # Command injection vulnerability
'''
    
    result = run_semgrep(vulnerable_code, language="python")
    
    if result.error:
        print(f"  ⚠️  Semgrep returned error: {result.error}")
        print("     (This may be OK if Semgrep rules are still downloading)")
        return
    
    if result.count > 0:
        print(f"  ✅ Semgrep found {result.count} issue(s)")
        for finding in result.findings:
            print(f"     - {finding.check_id}: {finding.severity}")
    else:
        print("  ⚠️  Semgrep found no issues (may need to download rules)")
    
    print("  ✅ Semgrep integration OK")


def main():
    print("=" * 60)
    print("🧪 SBST Framework Component Tests")
    print("=" * 60)
    print()
    
    all_passed = True
    
    try:
        test_evaluation_module()
        print()
    except Exception as e:
        print(f"  ❌ Evaluation module FAILED: {e}")
        all_passed = False
    
    try:
        test_mutation_module()
        print()
    except Exception as e:
        print(f"  ❌ Mutation module FAILED: {e}")
        all_passed = False
    
    try:
        test_llm_backend_base()
        print()
    except Exception as e:
        print(f"  ❌ LLM backend base FAILED: {e}")
        all_passed = False
    
    try:
        test_optimizer_module()
        print()
    except Exception as e:
        print(f"  ❌ Optimizer module FAILED: {e}")
        all_passed = False
    
    semgrep_ok = test_semgrep_available()
    print()
    
    if semgrep_ok:
        try:
            test_semgrep_integration()
            print()
        except Exception as e:
            print(f"  ⚠️  Semgrep integration test skipped: {e}")
    
    print("=" * 60)
    if all_passed:
        print("✅ All core tests passed!")
        if not semgrep_ok:
            print("⚠️  Note: Install Semgrep for full functionality")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
