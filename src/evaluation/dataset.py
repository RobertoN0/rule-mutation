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
    
    Compatible with src.optimizer.engine.TestPrompt
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
            "📊 Dataset Statistics",
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

