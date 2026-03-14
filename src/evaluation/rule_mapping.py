"""
Rule Mapping: Link test prompts to their relevant CodeGuard rules.

This module provides functionality to:
1. Load rule retrieval mappings (created by rule_retrieval_mapping.py)
2. Look up which rules to apply for each test prompt
3. Load and combine multiple rule files

The retrieval map JSON format:
{
  "metadata": { ... },
  "rule_frequency": { ... },
  "mappings": [
    {
      "index": 0,
      "cwe_id": "CWE-120",
      "language": "c",
      "prompt_hash": "abc123",
      "prompt": "Write a C function...",
      "rules_retrieved": ["codeguard-0-safe-c-functions", ...]
    },
    ...
  ]
}
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RuleMapping:
    """Mapping between a test prompt and its associated rules.
    
    Attributes:
        index: Original index from the mapping file
        cwe_id: CWE identifier for the prompt
        language: Programming language
        prompt_hash: Hash of the prompt text (for lookup)
        prompt: Full prompt text
        rules_retrieved: List of rule IDs to apply
    """
    index: int
    cwe_id: str
    language: str
    prompt_hash: str
    prompt: str
    rules_retrieved: list[str]
    
    @property
    def num_rules(self) -> int:
        return len(self.rules_retrieved)


@dataclass
class RuleMappingIndex:
    """Index for fast lookup of rule mappings.
    
    Provides lookups by:
    - prompt_hash (primary, O(1))
    - prompt text (secondary, O(1) via computed hash)
    - index (O(1))
    """
    
    mappings: list[RuleMapping]
    """All mappings."""
    
    metadata: dict[str, Any] = field(default_factory=dict)
    """Metadata from the mapping file."""
    
    _by_hash: dict[str, RuleMapping] = field(default_factory=dict, repr=False)
    """Index by prompt_hash."""
    
    _by_index: dict[int, RuleMapping] = field(default_factory=dict, repr=False)
    """Index by original index."""
    
    def __post_init__(self) -> None:
        """Build lookup indexes."""
        self._by_hash = {m.prompt_hash: m for m in self.mappings}
        self._by_index = {m.index: m for m in self.mappings}
    
    @classmethod
    def from_json_file(cls, path: Path | str) -> "RuleMappingIndex":
        """Load a rule mapping from a JSON file.
        
        Args:
            path: Path to the JSON file (retrieval_map_*.json)
            
        Returns:
            RuleMappingIndex with all mappings loaded
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            json.JSONDecodeError: If the file is invalid JSON
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        mappings = []
        for entry in data.get("mappings", []):
            mappings.append(RuleMapping(
                index=entry["index"],
                cwe_id=entry["cwe_id"],
                language=entry["language"],
                prompt_hash=entry["prompt_hash"],
                prompt=entry["prompt"],
                rules_retrieved=entry["rules_retrieved"],
            ))
        
        index = cls(
            mappings=mappings,
            metadata=data.get("metadata", {}),
        )
        return index
    
    def get_by_hash(self, prompt_hash: str) -> RuleMapping | None:
        """Look up a mapping by prompt hash."""
        return self._by_hash.get(prompt_hash)
    
    def get_by_index(self, index: int) -> RuleMapping | None:
        """Look up a mapping by original index."""
        return self._by_index.get(index)
    
    def get_by_prompt(self, prompt: str) -> RuleMapping | None:
        """Look up a mapping by computing the hash of the prompt text."""
        prompt_hash = compute_prompt_hash(prompt)
        return self._by_hash.get(prompt_hash)
    
    def get_rules_for_prompt(self, prompt: str) -> list[str]:
        """Get the list of rule IDs for a prompt.
        
        Returns an empty list if the prompt is not in the mapping.
        """
        mapping = self.get_by_prompt(prompt)
        return mapping.rules_retrieved if mapping else []
    
    @property
    def all_rules(self) -> set[str]:
        """Get all unique rule IDs used in this mapping."""
        return {rule for m in self.mappings for rule in m.rules_retrieved}
    
    @property
    def num_mappings(self) -> int:
        return len(self.mappings)
    
    def __len__(self) -> int:
        return len(self.mappings)


def compute_prompt_hash(prompt: str) -> str:
    """Compute the same hash used in rule_retrieval_mapping.py.
    
    The hash is the first 16 hex characters of the SHA-256 hash.
    This matches the hash computation in the original mapping script.
    """
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


class RuleLoader:
    """Load CodeGuard rule files from the rules directory.
    
    Caches loaded rules to avoid re-reading files.
    """
    
    def __init__(self, rules_dir: Path | str):
        """Initialize the rule loader.
        
        Args:
            rules_dir: Path to the directory containing rule .md files
        """
        self.rules_dir = Path(rules_dir)
        self._cache: dict[str, str] = {}
    
    def load(self, rule_id: str) -> str:
        """Load a single rule by ID.
        
        Args:
            rule_id: Rule identifier (e.g., "codeguard-0-input-validation-injection")
            
        Returns:
            The rule content as a string
            
        Raises:
            FileNotFoundError: If the rule file doesn't exist
        """
        if rule_id in self._cache:
            return self._cache[rule_id]
        
        rule_path = self.rules_dir / f"{rule_id}.md"
        if not rule_path.exists():
            raise FileNotFoundError(f"Rule not found: {rule_path}")
        
        content = rule_path.read_text(encoding="utf-8")
        self._cache[rule_id] = content
        return content
    
    def load_multiple(self, rule_ids: list[str]) -> dict[str, str]:
        """Load multiple rules by ID.
        
        Args:
            rule_ids: List of rule identifiers
            
        Returns:
            Dict mapping rule_id -> content
        """
        return {rule_id: self.load(rule_id) for rule_id in rule_ids}
    
    def combine_rules(
        self,
        rule_ids: list[str],
        separator: str = "\n\n---\n\n",
    ) -> str:
        """Load and combine multiple rules into a single text block.
        
        Args:
            rule_ids: List of rule identifiers to combine
            separator: Text to insert between rules
            
        Returns:
            Combined rule text
        """
        rules = self.load_multiple(rule_ids)
        return separator.join(rules.values())
    
    def clear_cache(self) -> None:
        """Clear the rule cache."""
        self._cache.clear()
    
    @property
    def available_rules(self) -> list[str]:
        """List all available rule IDs."""
        return [
            f.stem for f in sorted(self.rules_dir.glob("*.md"))
        ]


@dataclass
class PromptWithRules:
    """A test prompt enriched with its associated rules.
    
    This combines a TestPrompt with the specific rules to apply.
    """
    
    prompt: str
    """The code generation prompt."""
    
    language: str
    """Target programming language."""
    
    cwe_id: str | None = None
    """Associated CWE identifier."""
    
    rule_ids: list[str] = field(default_factory=list)
    """Rule IDs to apply for this prompt."""
    
    combined_rules: str = ""
    """Pre-combined rule text (for efficiency)."""
    
    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""
    
    @property
    def num_rules(self) -> int:
        return len(self.rule_ids)
    
    @classmethod
    def from_test_prompt(
        cls,
        prompt,  # TestPrompt from optimizer
        rule_mapping: RuleMappingIndex | None = None,
        rule_loader: RuleLoader | None = None,
        default_rule_ids: list[str] | None = None,
    ) -> "PromptWithRules":
        """Create a PromptWithRules from a TestPrompt and optional rule mapping.
        
        Args:
            prompt: A TestPrompt object
            rule_mapping: Optional mapping index to look up rules
            rule_loader: Optional loader to combine rules
            default_rule_ids: Fallback rule IDs if not in mapping
            
        Returns:
            PromptWithRules with rules resolved
        """
        rule_ids: list[str] = []
        
        # Try to get rules from mapping
        if rule_mapping:
            rule_ids = rule_mapping.get_rules_for_prompt(prompt.prompt)
        
        # Fallback to default
        if not rule_ids and default_rule_ids:
            rule_ids = list(default_rule_ids)
        
        # Combine rules if loader provided
        combined = ""
        if rule_ids and rule_loader:
            combined = rule_loader.combine_rules(rule_ids)
        
        return cls(
            prompt=prompt.prompt,
            language=prompt.language,
            cwe_id=prompt.cwe_id,
            rule_ids=rule_ids,
            combined_rules=combined,
            metadata=prompt.metadata,
        )


def enrich_prompts_with_rules(
    prompts: list,  # list[TestPrompt]
    rule_mapping: RuleMappingIndex,
    rule_loader: RuleLoader,
    default_rule_ids: list[str] | None = None,
) -> list[PromptWithRules]:
    """Enrich a list of test prompts with their associated rules.
    
    Args:
        prompts: List of TestPrompt objects
        rule_mapping: Mapping from prompts to rule IDs
        rule_loader: Loader for rule content
        default_rule_ids: Fallback rules for prompts not in mapping
        
    Returns:
        List of PromptWithRules with rules resolved and combined
    """
    enriched = []
    for prompt in prompts:
        pwr = PromptWithRules.from_test_prompt(
            prompt=prompt,
            rule_mapping=rule_mapping,
            rule_loader=rule_loader,
            default_rule_ids=default_rule_ids,
        )
        enriched.append(pwr)
    return enriched


def load_rule_mapping(path: Path | str) -> RuleMappingIndex:
    """Convenience function to load a rule mapping file.
    
    Args:
        path: Path to retrieval_map_*.json file
        
    Returns:
        RuleMappingIndex ready for lookups
    """
    return RuleMappingIndex.from_json_file(path)


def create_rule_loader(rules_dir: Path | str | None = None) -> RuleLoader:
    """Create a rule loader with default or specified directory.
    
    Args:
        rules_dir: Path to rules directory, or None for default
        
    Returns:
        RuleLoader instance
    """
    if rules_dir is None:
        # Default to project-codeguard rules
        module_path = Path(__file__).resolve()
        repo_root: Path | None = None
        for parent in [module_path.parent, *module_path.parents]:
            candidate = parent / "project-codeguard" / "skills" / "software-security" / "rules"
            if candidate.is_dir():
                repo_root = parent
                break
        if repo_root is None:
            raise FileNotFoundError(
                "Could not locate project root containing project-codeguard/skills/software-security/rules"
            )
        default = repo_root / "project-codeguard" / "skills" / "software-security" / "rules"
        rules_dir = default
    
    return RuleLoader(rules_dir)
