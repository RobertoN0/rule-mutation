"""
LLM Backend abstraction for the SBST framework.

Provides a unified interface for LLM inference on DelftBlue (local Qwen model).
"""

from .base import LLMBackend, LLMResponse, LLMConfig, LLMError, RateLimitError
from .delftblue_local_backend import (
    DelftBlueLocalBackend,
    create_delftblue_local_backend,
)

__all__ = [
    # Base classes
    "LLMBackend",
    "LLMResponse",
    "LLMConfig",
    "LLMError",
    "RateLimitError",
    # Backends
    "DelftBlueLocalBackend",
    "create_delftblue_local_backend",
]
