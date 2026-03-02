"""
Unified Dataset Configuration and Selection System.

This module provides a flexible system for test prompt selection that:
1. Always uses CyberSecEval (or other datasets) as the source of truth
2. Supports various selection methods: random, by ID, by filter, from JSON selectors
3. Is easily configurable to swap dataset backends
4. Removes the need for hardcoded test prompts

Design Principles:
- Dataset is the single source of truth for test prompts
- Selection criteria (IDs, filters, JSON files) narrow down the dataset
- Configuration makes it easy to swap datasets for reproducibility
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal
import json
import random

from .dataset import (
    TestPrompt,
    CyberSecEvalDataset,
    INJECTION_CWES,
    CRYPTO_CWES,
    MEMORY_CWES,
    LANGUAGE_EXTENSIONS,
)


class DatasetBackend(Enum):
    """Supported dataset backends."""
    CYBERSEC_EVAL = "cybersec_eval"
    # Future: SVEN = "sven"
    # Future: CUSTOM_JSON = "custom_json"


@dataclass
class DatasetConfig:
    """Configuration for dataset loading.
    
    This configuration allows easy swapping of dataset backends and
    setting default filters/limits.
    
    Example:
        # Use CyberSecEval with default settings
        config = DatasetConfig()
        
        # Use CyberSecEval with specific languages
        config = DatasetConfig(
            languages=["python", "javascript"],
            cwe_filter="injection",
        )
        
        # Different backend (future)
        config = DatasetConfig(backend=DatasetBackend.SVEN)
    """
    
    backend: DatasetBackend = DatasetBackend.CYBERSEC_EVAL
    """Which dataset to use."""
    
    config_name: str = "instruct"
    """Backend-specific configuration (e.g., 'instruct' for CyberSecEval)."""
    
    languages: list[str] | None = None
    """Languages to include (None = all available)."""
    
    cwe_filter: Literal["injection", "crypto", "memory", "all"] | None = None
    """Preset CWE filter."""
    
    cwes: list[str] | None = None
    """Specific CWE IDs to include."""
    
    cache_enabled: bool = True
    """Whether to cache loaded dataset."""
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "backend": self.backend.value,
            "config_name": self.config_name,
            "languages": self.languages,
            "cwe_filter": self.cwe_filter,
            "cwes": self.cwes,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "DatasetConfig":
        """Deserialize from dictionary."""
        return cls(
            backend=DatasetBackend(data.get("backend", "cybersec_eval")),
            config_name=data.get("config_name", "instruct"),
            languages=data.get("languages"),
            cwe_filter=data.get("cwe_filter"),
            cwes=data.get("cwes"),
        )


@dataclass
class SelectionCriteria:
    """Criteria for selecting test prompts from a dataset.
    
    Multiple selection methods can be combined:
    - test_case_ids: Select specific cases by ID
    - selector_json: Use a JSON file (like interesting_cases) to select
    - languages: Filter by language
    - cwes: Filter by CWE
    - limit: Limit total number of prompts
    - shuffle: Randomize selection
    
    Example:
        # Select 10 random Python prompts
        criteria = SelectionCriteria(
            languages=["python"],
            limit=10,
            shuffle=True,
            seed=42,
        )
        
        # Use interesting_cases.json as selector
        criteria = SelectionCriteria(
            selector_json="path/to/interesting_cases.json",
        )
        
        # Select specific test case IDs
        criteria = SelectionCriteria(
            test_case_ids=[3, 4, 17, 23],
        )
    """
    
    test_case_ids: list[int] | None = None
    """Specific test case IDs to select."""
    
    selector_json: str | Path | None = None
    """JSON file containing test case IDs or prompts to match."""
    
    languages: list[str] | None = None
    """Filter by languages."""
    
    cwes: list[str] | None = None
    """Filter by CWE IDs."""
    
    diff_types: list[str] | None = None
    """Filter by diff_type (for interesting_cases selector)."""
    
    limit: int | None = None
    """Maximum number of prompts to return."""
    
    limit_per_cwe: int | None = None
    """Maximum prompts per CWE (for balanced sampling)."""
    
    shuffle: bool = False
    """Whether to shuffle results."""
    
    seed: int = 42
    """Random seed for reproducibility."""
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "test_case_ids": self.test_case_ids,
            "selector_json": str(self.selector_json) if self.selector_json else None,
            "languages": self.languages,
            "cwes": self.cwes,
            "diff_types": self.diff_types,
            "limit": self.limit,
            "limit_per_cwe": self.limit_per_cwe,
            "shuffle": self.shuffle,
            "seed": self.seed,
        }


class DatasetProvider(ABC):
    """Abstract base class for dataset providers.
    
    Implement this to add new dataset backends.
    """
    
    @abstractmethod
    def load_all(self) -> list[TestPrompt]:
        """Load all prompts from the dataset."""
        pass
    
    @abstractmethod
    def get_by_id(self, test_case_id: int) -> TestPrompt | None:
        """Get a specific prompt by its ID."""
        pass
    
    @abstractmethod
    def filter(
        self,
        languages: list[str] | None = None,
        cwes: list[str] | None = None,
        limit_per_cwe: int | None = None,
    ) -> list[TestPrompt]:
        """Filter prompts by criteria."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of this dataset provider."""
        pass


class CyberSecEvalProvider(DatasetProvider):
    """CyberSecEval dataset provider.
    
    This is the default provider, loading from the HuggingFace dataset.
    """
    
    def __init__(self, config: DatasetConfig):
        self.config = config
        self._dataset = CyberSecEvalDataset(config=config.config_name)
        self._cached_prompts: list[TestPrompt] | None = None
        self._id_index: dict[int, TestPrompt] | None = None
    
    @property
    def name(self) -> str:
        return "CyberSecEval"
    
    def _build_index(self, prompts: list[TestPrompt]) -> dict[int, TestPrompt]:
        """Build an index mapping test_case_id to TestPrompt."""
        # Use hash of prompt content as fallback ID if not present
        index = {}
        for i, p in enumerate(prompts):
            # Use metadata test_case_id if available, else use index
            test_id = p.metadata.get("test_case_id", i)
            index[test_id] = p
            # Also store the index for lookup
            p.metadata["_internal_index"] = i
        return index
    
    def load_all(self) -> list[TestPrompt]:
        """Load all prompts matching the config filters."""
        if self._cached_prompts is not None and self.config.cache_enabled:
            return self._cached_prompts
        
        prompts = self._dataset.load(
            languages=self.config.languages,
            cwes=self.config.cwes,
            cwe_filter=self.config.cwe_filter,
        )
        
        # Assign test_case_ids based on position
        for i, p in enumerate(prompts):
            if "test_case_id" not in p.metadata:
                p.metadata["test_case_id"] = i
        
        if self.config.cache_enabled:
            self._cached_prompts = prompts
            self._id_index = self._build_index(prompts)
        
        return prompts
    
    def get_by_id(self, test_case_id: int) -> TestPrompt | None:
        """Get a prompt by its test case ID."""
        if self._id_index is None:
            self.load_all()
        
        return self._id_index.get(test_case_id) if self._id_index else None
    
    def filter(
        self,
        languages: list[str] | None = None,
        cwes: list[str] | None = None,
        limit_per_cwe: int | None = None,
    ) -> list[TestPrompt]:
        """Filter prompts by criteria."""
        return self._dataset.load(
            languages=languages or self.config.languages,
            cwes=cwes or self.config.cwes,
            cwe_filter=self.config.cwe_filter,
            limit_per_cwe=limit_per_cwe,
        )


class TestCaseSelector:
    """Unified test case selector that uses dataset as source of truth.
    
    This replaces hardcoded prompts and provides a consistent interface
    for selecting test cases from any dataset backend.
    
    Example:
        # Create selector with default CyberSecEval backend
        selector = TestCaseSelector()
        
        # Select 10 random Python injection prompts
        prompts = selector.select(SelectionCriteria(
            languages=["python"],
            cwes=INJECTION_CWES,
            limit=10,
            shuffle=True,
        ))
        
        # Use interesting_cases.json as selector (matches by prompt hash)
        prompts = selector.select(SelectionCriteria(
            selector_json="path/to/interesting_cases.json",
        ))
        
        # MVP-style selection (5 random injection prompts)
        prompts = selector.select_mvp()
    """
    
    def __init__(
        self,
        config: DatasetConfig | None = None,
        provider: DatasetProvider | None = None,
    ):
        """Initialize the selector.
        
        Args:
            config: Dataset configuration (uses defaults if None)
            provider: Custom provider (auto-creates from config if None)
        """
        self.config = config or DatasetConfig()
        
        if provider:
            self.provider = provider
        else:
            # Create provider based on config
            if self.config.backend == DatasetBackend.CYBERSEC_EVAL:
                self.provider = CyberSecEvalProvider(self.config)
            else:
                raise ValueError(f"Unsupported backend: {self.config.backend}")
    
    def select(self, criteria: SelectionCriteria) -> list[TestPrompt]:
        """Select test prompts based on criteria.
        
        Args:
            criteria: Selection criteria
            
        Returns:
            List of TestPrompt objects
        """
        prompts: list[TestPrompt] = []
        
        # Method 1: Use selector JSON (e.g., interesting_cases.json)
        if criteria.selector_json:
            prompts = self._select_from_json(criteria)
        
        # Method 2: Select by specific IDs
        elif criteria.test_case_ids:
            prompts = self._select_by_ids(criteria.test_case_ids)
        
        # Method 3: Filter from dataset
        else:
            prompts = self._select_by_filter(criteria)
        
        # Apply shuffle if requested
        if criteria.shuffle and prompts:
            rng = random.Random(criteria.seed)
            prompts = list(prompts)  # Copy to avoid mutating original
            rng.shuffle(prompts)
        
        # Apply limit
        if criteria.limit and len(prompts) > criteria.limit:
            prompts = prompts[:criteria.limit]
        
        return prompts
    
    def _select_from_json(self, criteria: SelectionCriteria) -> list[TestPrompt]:
        """Select prompts using a JSON file as selector.
        
        The JSON file can be:
        1. interesting_cases format: {"cases": [...]} - extracts test_case_ids and metadata
        2. Simple prompt list: [{"prompt": "...", ...}] - matches by prompt text
        3. ID list: {"test_case_ids": [1, 2, 3]} - direct ID lookup
        """
        json_path = Path(criteria.selector_json)  # type: ignore
        if not json_path.exists():
            raise FileNotFoundError(f"Selector JSON not found: {json_path}")
        
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        prompts = []
        
        # Handle interesting_cases format
        if isinstance(data, dict) and "cases" in data:
            # Extract metadata from interesting cases for enriched TestPrompts
            for case in data["cases"]:
                # Apply diff_type filter if specified
                if criteria.diff_types:
                    if case.get("diff_type") not in criteria.diff_types:
                        continue
                
                # Apply language filter
                if criteria.languages:
                    if case.get("language") not in criteria.languages:
                        continue
                
                # Apply CWE filter
                if criteria.cwes:
                    if case.get("cwe_id") not in criteria.cwes:
                        continue
                
                # Create TestPrompt with rich metadata from interesting case
                prompt = TestPrompt(
                    prompt=case["prompt"],
                    language=case["language"],
                    cwe_id=case.get("cwe_id"),
                    metadata={
                        "source": "interesting_cases",
                        "test_case_id": case.get("test_case_id"),
                        "diff_type": case.get("diff_type"),
                        "security_improvement": case.get("security_improvement", 0),
                        "selector_json": str(json_path),
                        # Store reference data for comparison
                        "baseline_vuln_count": case.get("baseline_vuln_count"),
                        "control_vuln_count": case.get("control_vuln_count"),
                        "mutant_vuln_count": case.get("mutant_vuln_count"),
                    },
                )
                prompts.append(prompt)
        
        # Handle ID list format
        elif isinstance(data, dict) and "test_case_ids" in data:
            ids = data["test_case_ids"]
            prompts = self._select_by_ids(ids)
        
        # Handle simple prompt list
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "prompt" in item:
                    prompt = TestPrompt.from_dict(item)
                    prompts.append(prompt)
        
        return prompts
    
    def _select_by_ids(self, test_case_ids: list[int]) -> list[TestPrompt]:
        """Select prompts by their test case IDs."""
        prompts = []
        for test_id in test_case_ids:
            prompt = self.provider.get_by_id(test_id)
            if prompt:
                prompts.append(prompt)
            else:
                print(f"   Warning: Test case ID {test_id} not found in dataset")
        return prompts
    
    def _select_by_filter(self, criteria: SelectionCriteria) -> list[TestPrompt]:
        """Select prompts by filtering the dataset."""
        return self.provider.filter(
            languages=criteria.languages,
            cwes=criteria.cwes,
            limit_per_cwe=criteria.limit_per_cwe,
        )
    
    def select_mvp(
        self,
        language: str = "python",
        n_prompts: int = 5,
        cwe_category: str = "injection",
        seed: int = 42,
    ) -> list[TestPrompt]:
        """Select prompts for MVP testing (replaces hardcoded prompts).
        
        Args:
            language: Target language
            n_prompts: Number of prompts
            cwe_category: "injection", "crypto", or "memory"
            seed: Random seed
            
        Returns:
            List of TestPrompt objects
        """
        criteria = SelectionCriteria(
            languages=[language],
            cwes=self._get_cwes_for_category(cwe_category),
            limit=n_prompts,
            limit_per_cwe=2,  # Balance across CWEs
            shuffle=True,
            seed=seed,
        )
        return self.select(criteria)
    
    def select_random(
        self,
        n_prompts: int,
        seed: int = 42,
        languages: list[str] | None = None,
    ) -> list[TestPrompt]:
        """Select random prompts from the dataset.
        
        Args:
            n_prompts: Number of prompts to select
            seed: Random seed for reproducibility
            languages: Filter by languages (None = all)
            
        Returns:
            List of TestPrompt objects
        """
        criteria = SelectionCriteria(
            languages=languages,
            limit=n_prompts,
            shuffle=True,
            seed=seed,
        )
        return self.select(criteria)
    
    def _get_cwes_for_category(self, category: str) -> list[str]:
        """Get CWE list for a category."""
        if category == "injection":
            return INJECTION_CWES
        elif category == "crypto":
            return CRYPTO_CWES
        elif category == "memory":
            return MEMORY_CWES
        else:
            return []  # All CWEs
    
    def summary(self) -> str:
        """Get a summary of the dataset."""
        all_prompts = self.provider.load_all()
        languages = sorted(set(p.language for p in all_prompts))
        cwes = sorted(set(p.cwe_id for p in all_prompts if p.cwe_id))
        
        lines = [
            f"📊 Dataset: {self.provider.name}",
            f"   Total prompts available: {len(all_prompts)}",
            f"   Languages: {', '.join(languages)}",
            f"   CWEs ({len(cwes)}): {', '.join(cwes[:5])}{'...' if len(cwes) > 5 else ''}",
        ]
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Functions
# ═══════════════════════════════════════════════════════════════════════════════


def create_selector(
    backend: str = "cybersec_eval",
    languages: list[str] | None = None,
    cwe_filter: str | None = None,
) -> TestCaseSelector:
    """Create a TestCaseSelector with common defaults.
    
    Args:
        backend: Dataset backend ("cybersec_eval")
        languages: Languages to include
        cwe_filter: CWE category filter ("injection", "crypto", "memory")
        
    Returns:
        Configured TestCaseSelector
    """
    config = DatasetConfig(
        backend=DatasetBackend(backend),
        languages=languages,
        cwe_filter=cwe_filter,  # type: ignore
    )
    return TestCaseSelector(config=config)


def select_from_interesting_cases(
    json_path: str | Path,
    languages: list[str] | None = None,
    diff_types: list[str] | None = None,
    limit: int | None = None,
    shuffle: bool = False,
    seed: int = 42,
) -> list[TestPrompt]:
    """Load test prompts from an interesting_cases JSON file.
    
    This is the preferred way to use pre-screened test cases.
    
    Args:
        json_path: Path to interesting_cases JSON
        languages: Filter by languages
        diff_types: Filter by diff_type (e.g., ["rules_helped"])
        limit: Max prompts to return
        shuffle: Whether to shuffle
        seed: Random seed
        
    Returns:
        List of TestPrompt objects
        
    Example:
        prompts = select_from_interesting_cases(
            "pipeline_breakdown/generation_results/interesting_cases_96_sonnet_4_6.json",
            languages=["c"],
            diff_types=["rules_helped"],
        )
    """
    selector = create_selector()
    criteria = SelectionCriteria(
        selector_json=json_path,
        languages=languages,
        diff_types=diff_types,
        limit=limit,
        shuffle=shuffle,
        seed=seed,
    )
    return selector.select(criteria)


def select_mvp_prompts(
    language: str = "python",
    n_prompts: int = 5,
    cwe_category: str = "injection",
    seed: int = 42,
) -> list[TestPrompt]:
    """Select prompts for MVP testing (deterministic, from dataset).
    
    This replaces the hardcoded MVP_TEST_PROMPTS.
    
    Args:
        language: Target language
        n_prompts: Number of prompts
        cwe_category: "injection", "crypto", or "memory"
        seed: Random seed for reproducibility
        
    Returns:
        List of TestPrompt objects
    """
    selector = create_selector()
    return selector.select_mvp(
        language=language,
        n_prompts=n_prompts,
        cwe_category=cwe_category,
        seed=seed,
    )
