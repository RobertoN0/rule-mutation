"""
CyberSecEval dataset loader for the SBST framework.

Loads prompts from the walledai/CyberSecEval HuggingFace dataset and
converts them to TestPrompt objects for use in experiments.

Dataset: https://huggingface.co/datasets/walledai/CyberSecEval
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Supported languages and their file extensions
LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "c": ".c",
    "cpp": ".cpp",
    "csharp": ".cs",
    "java": ".java",
    "javascript": ".js",
    "php": ".php",
    "rust": ".rs",
}

# CWE categories relevant to code injection (high-value for CodeGuard testing)
INJECTION_CWES = [
    "CWE-22",   # Path Traversal
    "CWE-78",   # OS Command Injection
    "CWE-79",   # XSS (Cross-site Scripting)
    "CWE-89",   # SQL Injection
    "CWE-94",   # Code Injection
    "CWE-95",   # Eval Injection
    "CWE-117",  # Log Injection
    "CWE-611",  # XXE (XML External Entity)
    "CWE-918",  # SSRF (Server-Side Request Forgery)
]

# Cryptography-related CWEs (for crypto rules)
CRYPTO_CWES = [
    "CWE-327",  # Use of Broken Crypto Algorithm
    "CWE-328",  # Reversible One-Way Hash
    "CWE-330",  # Use of Insufficiently Random Values
    "CWE-338",  # Use of Weak PRNG
    "CWE-347",  # Improper Verification of Crypto Signature
    "CWE-798",  # Hard-coded Credentials
]

# Memory safety CWEs (for C/C++)
MEMORY_CWES = [
    "CWE-120",  # Buffer Overflow
    "CWE-122",  # Heap Overflow
    "CWE-125",  # Out-of-bounds Read
    "CWE-416",  # Use After Free
    "CWE-476",  # NULL Pointer Dereference
    "CWE-787",  # Out-of-bounds Write
]


@dataclass
class TestPrompt:
    """A test prompt from CyberSecEval dataset.
    
    Compatible with src.optimizer.hill_climber.TestPrompt
    """
    
    prompt: str
    """The code generation prompt text."""
    
    language: str
    """Target programming language (python, javascript, etc.)."""
    
    cwe_id: str | None = None
    """CWE identifier (e.g., 'CWE-89')."""
    
    metadata: dict = field(default_factory=dict)
    """Additional metadata from the dataset."""
    
    @property
    def file_extension(self) -> str:
        """Get file extension for this language."""
        return LANGUAGE_EXTENSIONS.get(self.language, ".txt")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "prompt": self.prompt,
            "language": self.language,
            "cwe_id": self.cwe_id,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TestPrompt":
        """Create from dictionary."""
        return cls(
            prompt=data["prompt"],
            language=data["language"],
            cwe_id=data.get("cwe_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DatasetStats:
    """Statistics about loaded dataset."""
    
    total_prompts: int
    languages: list[str]
    cwes: list[str]
    prompts_per_language: dict[str, int]
    prompts_per_cwe: dict[str, int]
    
    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"📊 Dataset Statistics",
            f"   Total prompts: {self.total_prompts}",
            f"   Languages ({len(self.languages)}): {', '.join(self.languages)}",
            f"   CWEs ({len(self.cwes)}): {', '.join(self.cwes[:5])}{'...' if len(self.cwes) > 5 else ''}",
        ]
        return "\n".join(lines)


class CyberSecEvalDataset:
    """Loader for the CyberSecEval dataset.
    
    Example:
        # Load all Python prompts
        dataset = CyberSecEvalDataset()
        prompts = dataset.load(languages=["python"])
        
        # Load injection-related prompts for multiple languages
        prompts = dataset.load(
            languages=["python", "javascript"],
            cwe_filter="injection",
            limit_per_cwe=5,
        )
        
        # Get statistics
        print(dataset.get_stats(prompts).summary())
    """
    
    def __init__(self, config: str = "instruct"):
        """Initialize the dataset loader.
        
        Args:
            config: HuggingFace dataset config name ("instruct" for code generation)
        """
        self.config = config
        self._raw_data: dict | None = None
    
    def _ensure_loaded(self) -> dict:
        """Lazy-load the raw dataset."""
        if self._raw_data is None:
            try:
                from datasets import load_dataset
            except ImportError:
                raise ImportError(
                    "datasets package not installed. Run: pip install datasets"
                )
            
            print(f"📦 Loading CyberSecEval dataset (config={self.config})...")
            self._raw_data = load_dataset("walledai/CyberSecEval", self.config)
            
            # Show what's available
            available_langs = [k for k in self._raw_data.keys() if k in LANGUAGE_EXTENSIONS]
            print(f"   Available languages: {', '.join(available_langs)}") # type: ignore
            
        return self._raw_data
    
    def load(
        self,
        languages: list[str] | None = None,
        cwes: list[str] | None = None,
        cwe_filter: Literal["injection", "crypto", "memory", "all"] | None = None,
        limit_per_cwe: int | None = None,
        limit_total: int | None = None,
        shuffle: bool = False,
        seed: int = 42,
    ) -> list[TestPrompt]:
        """Load prompts from the dataset with filtering.
        
        Args:
            languages: List of languages to include (None = all available)
            cwes: Specific CWE IDs to include (e.g., ["CWE-89", "CWE-78"])
            cwe_filter: Preset filter - "injection", "crypto", "memory", or "all"
            limit_per_cwe: Max prompts per CWE (for balanced sampling)
            limit_total: Max total prompts to return
            shuffle: Whether to shuffle results
            seed: Random seed for shuffling
            
        Returns:
            List of TestPrompt objects
        """
        raw_data = self._ensure_loaded()
        
        # Determine which CWEs to include
        target_cwes: set[str] | None = None
        if cwes:
            target_cwes = set(cwes)
        elif cwe_filter:
            if cwe_filter == "injection":
                target_cwes = set(INJECTION_CWES)
            elif cwe_filter == "crypto":
                target_cwes = set(CRYPTO_CWES)
            elif cwe_filter == "memory":
                target_cwes = set(MEMORY_CWES)
            # "all" means no filter
        
        # Determine which languages to include
        target_languages = languages or list(LANGUAGE_EXTENSIONS.keys())
        
        # Collect prompts
        prompts: list[TestPrompt] = []
        cwe_counts: dict[str, int] = {}
        
        for lang in target_languages:
            if lang not in raw_data:
                continue
            
            for item in raw_data[lang]:
                cwe_id = item.get("cwe_identifier", "unknown")
                
                # Apply CWE filter
                if target_cwes and cwe_id not in target_cwes:
                    continue
                
                # Apply per-CWE limit
                if limit_per_cwe:
                    if cwe_counts.get(cwe_id, 0) >= limit_per_cwe:
                        continue
                    cwe_counts[cwe_id] = cwe_counts.get(cwe_id, 0) + 1
                
                prompt = TestPrompt(
                    prompt=item["prompt"],
                    language=lang,
                    cwe_id=cwe_id,
                    metadata={
                        "origin": "CyberSecEval",
                        "config": self.config,
                    },
                )
                prompts.append(prompt)
        
        # Shuffle if requested
        if shuffle:
            import random
            rng = random.Random(seed)
            rng.shuffle(prompts)
        
        # Apply total limit
        if limit_total and len(prompts) > limit_total:
            prompts = prompts[:limit_total]
        
        print(f"   Loaded {len(prompts)} prompts")
        return prompts
    
    def get_stats(self, prompts: list[TestPrompt]) -> DatasetStats:
        """Get statistics for a list of prompts."""
        languages = sorted(set(p.language for p in prompts))
        cwes = sorted(set(p.cwe_id for p in prompts if p.cwe_id))
        
        prompts_per_language = {}
        for p in prompts:
            prompts_per_language[p.language] = prompts_per_language.get(p.language, 0) + 1
        
        prompts_per_cwe = {}
        for p in prompts:
            if p.cwe_id:
                prompts_per_cwe[p.cwe_id] = prompts_per_cwe.get(p.cwe_id, 0) + 1
        
        return DatasetStats(
            total_prompts=len(prompts),
            languages=languages,
            cwes=cwes,
            prompts_per_language=prompts_per_language,
            prompts_per_cwe=prompts_per_cwe,
        )
    
    def list_available_cwes(self, language: str | None = None) -> list[str]:
        """List all CWE IDs available in the dataset.
        
        Args:
            language: Filter to specific language (None = all)
            
        Returns:
            Sorted list of CWE identifiers
        """
        raw_data = self._ensure_loaded()
        cwes = set()
        
        langs = [language] if language else list(LANGUAGE_EXTENSIONS.keys())
        for lang in langs:
            if lang not in raw_data:
                continue
            for item in raw_data[lang]:
                if cwe := item.get("cwe_identifier"):
                    cwes.add(cwe)
        
        return sorted(cwes)


# Convenience functions for quick loading

def load_injection_prompts(
    languages: list[str] | None = None,
    limit_per_cwe: int = 5,
) -> list[TestPrompt]:
    """Load injection-related prompts for testing input validation rules.
    
    Args:
        languages: Target languages (default: ["python"])
        limit_per_cwe: Max prompts per CWE type
        
    Returns:
        List of TestPrompt objects
    """
    dataset = CyberSecEvalDataset()
    return dataset.load(
        languages=languages or ["python"],
        cwe_filter="injection",
        limit_per_cwe=limit_per_cwe,
    )


def load_crypto_prompts(
    languages: list[str] | None = None,
    limit_per_cwe: int = 5,
) -> list[TestPrompt]:
    """Load cryptography-related prompts for testing crypto rules."""
    dataset = CyberSecEvalDataset()
    return dataset.load(
        languages=languages or ["python"],
        cwe_filter="crypto",
        limit_per_cwe=limit_per_cwe,
    )


def load_mvp_prompts() -> list[TestPrompt]:
    """Load a small set of prompts for MVP testing.
    
    Returns 5 injection prompts (Python only) for quick iteration.
    """
    dataset = CyberSecEvalDataset()
    return dataset.load(
        languages=["python"],
        cwe_filter="injection",
        limit_per_cwe=2,
        limit_total=5,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Interesting Cases Loader (Pre-analyzed test cases with known behavior)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class InterestingCase:
    """A pre-analyzed test case with baseline/control/mutant results.
    
    These cases have been pre-screened to show interesting behavior:
    - rules_helped: The rule improved the code security
    - rules_hurt: The rule made the code less secure
    - mutation_improved: A mutated rule produced better results
    - mutation_degraded: A mutated rule produced worse results
    """
    
    test_case_id: int
    """Original ID from the dataset."""
    
    cwe_id: str
    """CWE identifier (e.g., 'CWE-120')."""
    
    language: str
    """Programming language."""
    
    prompt: str
    """The code generation prompt."""
    
    baseline_code: str
    """Code generated WITHOUT any rules."""
    
    control_code: str
    """Code generated WITH the security rule."""
    
    mutant_code: str
    """Code generated WITH the mutated rule."""
    
    baseline_vuln_count: int
    """Vulnerability count in baseline."""
    
    control_vuln_count: int
    """Vulnerability count with rules."""
    
    mutant_vuln_count: int
    """Vulnerability count with mutated rules."""
    
    baseline_findings: list[str]
    """Semgrep rule IDs found in baseline."""
    
    control_findings: list[str]
    """Semgrep rule IDs found with rules."""
    
    mutant_findings: list[str]
    """Semgrep rule IDs found with mutated rules."""
    
    security_improvement: int
    """Improvement score (baseline_vuln - control_vuln)."""
    
    security_regression: bool
    """Whether mutated rule caused regression."""
    
    diff_type: str
    """Classification: rules_helped, rules_hurt, mutation_improved, etc."""
    
    metadata: dict = field(default_factory=dict)
    """Additional metadata."""
    
    def to_test_prompt(self) -> TestPrompt:
        """Convert to TestPrompt for use in experiments."""
        return TestPrompt(
            prompt=self.prompt,
            language=self.language,
            cwe_id=self.cwe_id,
            metadata={
                "source": "interesting_cases",
                "test_case_id": self.test_case_id,
                "diff_type": self.diff_type,
                "security_improvement": self.security_improvement,
            },
        )
    
    @classmethod
    def from_dict(cls, data: dict) -> "InterestingCase":
        """Create from a dictionary (JSON entry)."""
        return cls(
            test_case_id=data["test_case_id"],
            cwe_id=data["cwe_id"],
            language=data["language"],
            prompt=data["prompt"],
            baseline_code=data["baseline_code"],
            control_code=data["control_code"],
            mutant_code=data["mutant_code"],
            baseline_vuln_count=data["baseline_vuln_count"],
            control_vuln_count=data["control_vuln_count"],
            mutant_vuln_count=data["mutant_vuln_count"],
            baseline_findings=data.get("baseline_findings", []),
            control_findings=data.get("control_findings", []),
            mutant_findings=data.get("mutant_findings", []),
            security_improvement=data["security_improvement"],
            security_regression=data.get("security_regression", False),
            diff_type=data["diff_type"],
            metadata={
                "baseline_severities": data.get("baseline_severities", []),
                "control_severities": data.get("control_severities", []),
                "mutant_severities": data.get("mutant_severities", []),
            },
        )


@dataclass 
class InterestingCasesDataset:
    """Collection of interesting cases loaded from a JSON file.
    
    Example:
        # Load all cases
        dataset = load_interesting_cases("path/to/interesting_cases.json")
        
        # Get test prompts for experiments
        prompts = dataset.to_test_prompts()
        
        # Filter by diff type or language
        helped_cases = dataset.filter(diff_type="rules_helped")
        c_cases = dataset.filter(language="c")
        
        # Batch for multi-round experiments
        batches = dataset.batch(batch_size=4)
    """
    
    cases: list[InterestingCase]
    """All loaded cases."""
    
    batch_id: str | None = None
    """Original batch ID from the file."""
    
    model: str | None = None
    """Model that generated the code."""
    
    timestamp: str | None = None
    """When the cases were generated."""
    
    def __len__(self) -> int:
        return len(self.cases)
    
    def __iter__(self):
        return iter(self.cases)
    
    def __getitem__(self, idx: int) -> InterestingCase:
        return self.cases[idx]
    
    def to_test_prompts(self) -> list[TestPrompt]:
        """Convert all cases to TestPrompt objects for experiments."""
        return [case.to_test_prompt() for case in self.cases]
    
    def filter(
        self,
        language: str | None = None,
        cwe_id: str | None = None,
        diff_type: str | None = None,
        min_improvement: int | None = None,
    ) -> "InterestingCasesDataset":
        """Filter cases by criteria.
        
        Args:
            language: Filter by language (e.g., "c", "python")
            cwe_id: Filter by CWE (e.g., "CWE-120")
            diff_type: Filter by diff_type (e.g., "rules_helped", "rules_hurt")
            min_improvement: Only cases with security_improvement >= this
            
        Returns:
            New InterestingCasesDataset with filtered cases
        """
        filtered = self.cases
        
        if language:
            filtered = [c for c in filtered if c.language == language]
        if cwe_id:
            filtered = [c for c in filtered if c.cwe_id == cwe_id]
        if diff_type:
            filtered = [c for c in filtered if c.diff_type == diff_type]
        if min_improvement is not None:
            filtered = [c for c in filtered if c.security_improvement >= min_improvement]
        
        return InterestingCasesDataset(
            cases=filtered,
            batch_id=self.batch_id,
            model=self.model,
            timestamp=self.timestamp,
        )
    
    def batch(self, batch_size: int, shuffle: bool = False, seed: int = 42) -> list[list[InterestingCase]]:
        """Split cases into batches for multi-round experiments.
        
        Args:
            batch_size: Number of cases per batch
            shuffle: Whether to shuffle before batching
            seed: Random seed for shuffling
            
        Returns:
            List of batches, each batch is a list of InterestingCase
        """
        cases = list(self.cases)
        
        if shuffle:
            import random
            rng = random.Random(seed)
            rng.shuffle(cases)
        
        batches = []
        for i in range(0, len(cases), batch_size):
            batches.append(cases[i:i + batch_size])
        
        return batches
    
    def summary(self) -> str:
        """Get a human-readable summary of the dataset."""
        languages = sorted(set(c.language for c in self.cases))
        cwes = sorted(set(c.cwe_id for c in self.cases))
        diff_types = sorted(set(c.diff_type for c in self.cases))
        
        # Count by diff type
        type_counts = {}
        for c in self.cases:
            type_counts[c.diff_type] = type_counts.get(c.diff_type, 0) + 1
        
        lines = [
            f"📊 Interesting Cases Summary",
            f"   Total cases: {len(self.cases)}",
            f"   Languages: {', '.join(languages)}",
            f"   CWEs ({len(cwes)}): {', '.join(cwes[:5])}{'...' if len(cwes) > 5 else ''}",
            f"   Diff types:",
        ]
        for dtype, count in sorted(type_counts.items()):
            lines.append(f"      - {dtype}: {count}")
        
        if self.model:
            lines.append(f"   Generated by: {self.model}")
        
        return "\n".join(lines)


def load_interesting_cases(json_path: str) -> InterestingCasesDataset:
    """Load interesting cases from a JSON file.
    
    Args:
        json_path: Path to the interesting cases JSON file
        
    Returns:
        InterestingCasesDataset with all loaded cases
        
    Example:
        dataset = load_interesting_cases(
            "pipeline_breakdown/generation_results/interesting_cases_96_sonnet_4_6.json"
        )
        print(dataset.summary())
        
        # Get prompts for experiment
        prompts = dataset.to_test_prompts()
        
        # Or filter first
        c_prompts = dataset.filter(language="c").to_test_prompts()
    """
    import json
    from pathlib import Path
    
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Interesting cases file not found: {json_path}")
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    cases = [InterestingCase.from_dict(c) for c in data.get("cases", [])]
    
    return InterestingCasesDataset(
        cases=cases,
        batch_id=data.get("batch_id"),
        model=data.get("model"),
        timestamp=data.get("timestamp"),
    )
