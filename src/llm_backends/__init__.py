"""
LLM Backend abstraction for the SBST framework.

Provides a unified interface for multiple LLM providers:
- DelftBlue local HuggingFace inference (cluster-only, requires [gpu] extras)
- Anthropic Claude API (replication-friendly)
- OpenAI Chat Completions API
"""

from .base import LLMBackend, LLMResponse, LLMConfig, LLMError, RateLimitError
from .claude_backend import ClaudeBackend, create_claude_backend
from .openai_backend import OpenAIBackend, create_openai_backend

# DelftBlue local-inference backend depends on torch/transformers (pulled by
# core in this branch via sentence-transformers), and additionally accelerate/
# bitsandbytes which are only installed via the [gpu] extras. Import lazily so
# the package still loads if optional pieces are missing on a reviewer's box.
try:
    from .delftblue_local_backend import (
        DelftBlueLocalBackend,
        create_delftblue_local_backend,
    )
    _HAS_DELFTBLUE = True
except ImportError:
    _HAS_DELFTBLUE = False

__all__ = [
    # Base classes
    "LLMBackend",
    "LLMResponse",
    "LLMConfig",
    "LLMError",
    "RateLimitError",
    # Backends
    "ClaudeBackend",
    "create_claude_backend",
    "OpenAIBackend",
    "create_openai_backend",
]

if _HAS_DELFTBLUE:
    __all__.extend(["DelftBlueLocalBackend", "create_delftblue_local_backend"])
