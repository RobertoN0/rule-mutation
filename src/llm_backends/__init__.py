"""
LLM Backend abstraction for the SBST framework.

Provides a unified interface for different LLM providers (Groq, OpenRouter, Together AI).
"""

from .base import LLMBackend, LLMResponse, LLMConfig, LLMError, RateLimitError
from .groq_backend import GroqBackend, create_groq_backend
from .openrouter_backend import OpenRouterBackend, create_openrouter_backend
from .quota import (
    QuotaTracker,
    QuotaUsage,
    RateLimitInfo,
    get_quota_tracker,
    GROQ_FREE_TIER_LIMITS,
)

__all__ = [
    # Base classes
    "LLMBackend",
    "LLMResponse",
    "LLMConfig",
    "LLMError",
    "RateLimitError",
    # Backends
    "GroqBackend",
    "create_groq_backend",
    "OpenRouterBackend",
    "create_openrouter_backend",
    # Quota tracking
    "QuotaTracker",
    "QuotaUsage",
    "RateLimitInfo",
    "get_quota_tracker",
    "GROQ_FREE_TIER_LIMITS",
]
