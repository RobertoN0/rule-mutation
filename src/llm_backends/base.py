"""
Abstract base class for LLM backends.

All LLM providers (Groq, OpenRouter, Together AI) implement this interface
to ensure consistent behavior across the SBST framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMConfig:
    """Configuration for an LLM backend."""
    
    model: str
    """Model identifier (e.g., 'llama-3.1-8b-instant')."""
    
    temperature: float = 0.0
    """Sampling temperature (0.0 = deterministic)."""
    
    max_tokens: int = 4096
    """Maximum tokens in response."""
    
    api_key: str | None = None
    """API key (if not set via environment)."""
    
    base_url: str | None = None
    """Base URL for API (provider-specific default if None)."""
    
    timeout: float = 60.0
    """Request timeout in seconds."""
    
    max_retries: int = 3
    """Number of retries on transient failures."""
    
    extra: dict[str, Any] = field(default_factory=dict)
    """Provider-specific extra configuration."""


@dataclass
class LLMResponse:
    """Response from an LLM generation request."""
    
    content: str
    """The generated text content."""
    
    model: str
    """Model that generated the response."""
    
    input_tokens: int = 0
    """Number of input tokens (if available)."""
    
    output_tokens: int = 0
    """Number of output tokens (if available)."""
    
    latency_ms: float = 0.0
    """Request latency in milliseconds."""
    
    finish_reason: str = "stop"
    """Why generation stopped (stop, length, etc.)."""
    
    raw_response: Any = None
    """Raw response object from the provider."""
    
    rate_limit_info: Any = None
    """Rate limit info from response headers (RateLimitInfo object)."""
    
    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens


class LLMBackend(ABC):
    """Abstract base class for LLM providers.
    
    All backends use the OpenAI-compatible chat completions format:
    - system: str | list[dict] - System message(s)
    - messages: list[dict] - User/assistant messages
    
    Example usage:
        backend = GroqBackend(config)
        response = backend.generate(
            system="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hello!"}]
        )
        print(response.content)
    """
    
    def __init__(self, config: LLMConfig):
        """Initialize the backend with configuration.
        
        Args:
            config: LLMConfig with model, API key, and other settings.
        """
        self.config = config
    
    @abstractmethod
    def generate(
        self,
        system: str | list[dict],
        messages: list[dict],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response from the LLM.
        
        Args:
            system: System message(s). Can be a string or list of content blocks.
            messages: List of message dicts with 'role' and 'content' keys.
            **kwargs: Additional provider-specific parameters.
            
        Returns:
            LLMResponse with the generated content and metadata.
            
        Raises:
            LLMError: On API errors or rate limiting.
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend is configured and available.
        
        Returns:
            True if API key is set and the service appears reachable.
        """
        pass
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""
        pass
    
    @property
    def model_name(self) -> str:
        """Currently configured model name."""
        return self.config.model


class LLMError(Exception):
    """Base exception for LLM backend errors."""
    pass


class RateLimitError(LLMError):
    """Raised when rate limited by the provider."""
    
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class AuthenticationError(LLMError):
    """Raised when API key is invalid or missing."""
    pass


class ModelNotFoundError(LLMError):
    """Raised when the specified model is not available."""
    pass
