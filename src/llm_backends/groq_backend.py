"""
Groq LLM backend implementation.

Uses Groq's OpenAI-compatible API for fast inference on Llama and other models.
Free tier: 500K tokens/day for Llama 3.1 8B, 100K tokens/day for Llama 3.3 70B.

Requires:
    pip install openai
    
Environment:
    GROQ_API_KEY - Your Groq API key from https://console.groq.com
"""

from __future__ import annotations

import os
import time
from typing import Any

from .base import (
    LLMBackend,
    LLMConfig,
    LLMResponse,
    LLMError,
    RateLimitError,
    AuthenticationError,
    ModelNotFoundError,
)
from .quota import (
    RateLimitInfo,
    QuotaTracker,
    QuotaUsage,
    get_quota_tracker,
    GROQ_FREE_TIER_LIMITS,
)

# Groq API endpoint (OpenAI-compatible)
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Model metadata (context lengths, descriptions)
# Rate limits are now in quota.py (GROQ_FREE_TIER_LIMITS)
GROQ_MODELS = {
    "llama-3.1-8b-instant": {
        "context": 131072,
        "description": "Meta Llama 3.1 8B - Fast, good for iteration",
    },
    "llama-3.3-70b-versatile": {
        "context": 131072,
        "description": "Meta Llama 3.3 70B - Higher quality, limited free tier",
    },
    "qwen/qwen3-32b": {
        "context": 131072,
        "description": "Qwen 3 32B - Good reasoning capabilities",
    },
    "gemma2-9b-it": {
        "context": 8192,
        "description": "Google Gemma 2 9B - Efficient instruction following",
    },
}


class GroqBackend(LLMBackend):
    """Groq LLM backend using OpenAI-compatible API.
    
    Features:
    - Automatic quota tracking (tokens and requests per day)
    - Rate limit header parsing for accurate remaining quota
    - Pre-flight checks before experiments
    
    Example:
        config = LLMConfig(
            model="llama-3.1-8b-instant",
            api_key=os.getenv("GROQ_API_KEY"),
        )
        backend = GroqBackend(config)
        
        response = backend.generate(
            system="You are a code generator.",
            messages=[{"role": "user", "content": "Write a Python hello world"}]
        )
        print(response.content)
    """
    
    def __init__(self, config: LLMConfig, quota_tracker: QuotaTracker | None = None):
        """Initialize Groq backend.
        
        Args:
            config: LLMConfig with model and optional API key.
                   API key defaults to GROQ_API_KEY environment variable.
            quota_tracker: Optional QuotaTracker instance. If None, uses global tracker.
        """
        super().__init__(config)
        
        # Get API key from config or environment
        self.api_key = config.api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise AuthenticationError(
                "Groq API key not provided. Set GROQ_API_KEY environment variable "
                "or pass api_key in LLMConfig."
            )
        
        # Use provided base_url or default
        self.base_url = config.base_url or GROQ_BASE_URL
        
        # Quota tracking
        self._quota_tracker = quota_tracker or get_quota_tracker()
        
        # Lazy-load OpenAI client
        self._client = None
    
    @property
    def client(self):
        """Lazy-load the OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI # type: ignore
            except ImportError:
                raise LLMError(
                    "openai package not installed. Run: pip install openai"
                )
            
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
            )
        return self._client
    
    @property
    def provider_name(self) -> str:
        return "Groq"
    
    def is_available(self) -> bool:
        """Check if Groq API is accessible."""
        if not self.api_key:
            return False
        try:
            # Quick model list call to verify connectivity
            self.client.models.list()
            return True
        except Exception:
            return False
    
    def generate(
        self,
        system: str | list[dict],
        messages: list[dict],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response using Groq API.
        
        Args:
            system: System message (string or list of content blocks).
                   For Groq, list format is flattened to a single string.
            messages: List of user/assistant message dicts.
            **kwargs: Additional parameters (temperature, max_tokens override).
            
        Returns:
            LLMResponse with generated content and rate limit info.
        """
        start_time = time.perf_counter()
        
        # Build messages list
        all_messages = []
        
        # Handle system message (Groq expects string, not list)
        if isinstance(system, list):
            # Flatten list of content blocks to single string
            system_text = "\n".join(
                block.get("text", "") for block in system
                if isinstance(block, dict) and "text" in block
            )
        else:
            system_text = system
        
        if system_text:
            all_messages.append({"role": "system", "content": system_text})
        
        # Add user/assistant messages
        all_messages.extend(messages)
        
        # Prepare request parameters
        request_params = {
            "model": self.config.model,
            "messages": all_messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        
        try:
            # Use with_raw_response to get headers
            raw_response = self.client.chat.completions.with_raw_response.create(
                **request_params
            )
            response = raw_response.parse()
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            # Extract rate limit info from headers
            rate_limit_info = RateLimitInfo.from_headers(dict(raw_response.headers))
            
            # Extract response content
            choice = response.choices[0]
            content = choice.message.content or ""
            
            # Calculate tokens
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            total_tokens = input_tokens + output_tokens
            
            # Record usage in tracker
            self._quota_tracker.record_usage(
                model=self.config.model,
                tokens_used=total_tokens,
                rate_limit_info=rate_limit_info,
            )
            
            return LLMResponse(
                content=content,
                model=response.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                finish_reason=choice.finish_reason or "stop",
                raw_response=response,
                rate_limit_info=rate_limit_info,
            )
            
        except Exception as e:
            error_str = str(e).lower()
            
            if "rate limit" in error_str or "429" in error_str:
                raise RateLimitError(f"Groq rate limit exceeded: {e}")
            elif "authentication" in error_str or "401" in error_str:
                raise AuthenticationError(f"Groq authentication failed: {e}")
            elif "model" in error_str and ("not found" in error_str or "404" in error_str):
                raise ModelNotFoundError(f"Model {self.config.model} not available: {e}")
            else:
                raise LLMError(f"Groq API error: {e}")
    
    def list_models(self) -> list[str]:
        """List available models on Groq."""
        try:
            models = self.client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            raise LLMError(f"Failed to list Groq models: {e}")
    
    # -------------------------------------------------------------------------
    # Quota tracking methods
    # -------------------------------------------------------------------------
    
    def check_quota(
        self,
        estimated_tokens: int,
        estimated_requests: int,
        warn_threshold: float = 0.8,
    ) -> tuple[bool, str]:
        """Pre-flight check: can an experiment run without exceeding quota?
        
        Call this before running experiments to ensure you won't hit limits.
        
        Args:
            estimated_tokens: Expected total tokens for the experiment
            estimated_requests: Expected number of API calls
            warn_threshold: Warn if usage would exceed this fraction (0.8 = 80%)
            
        Returns:
            Tuple of (is_safe, message)
            - is_safe: True if experiment can run without exceeding limits
            - message: Human-readable status/warning message
            
        Example:
            is_ok, msg = backend.check_quota(
                estimated_tokens=50000,  # 20 iterations × 10 prompts × 250 tokens
                estimated_requests=200,
            )
            if not is_ok:
                print(msg)
                sys.exit(1)
        """
        return self._quota_tracker.check_quota(
            model=self.config.model,
            estimated_tokens=estimated_tokens,
            estimated_requests=estimated_requests,
            warn_threshold=warn_threshold,
        )
    
    def get_quota_status(self) -> str:
        """Get human-readable quota status for the current model."""
        return self._quota_tracker.get_summary(self.config.model)
    
    def get_quota_usage(self) -> QuotaUsage:
        """Get detailed quota usage object for the current model."""
        return self._quota_tracker.get_usage(self.config.model)
    
    @property
    def quota_tracker(self) -> QuotaTracker:
        """Access the quota tracker for advanced usage."""
        return self._quota_tracker


def create_groq_backend(
    model: str = "llama-3.1-8b-instant",
    **kwargs: Any,
) -> GroqBackend:
    """Convenience function to create a Groq backend.
    
    Args:
        model: Model identifier.
        **kwargs: Additional LLMConfig parameters.
        
    Returns:
        Configured GroqBackend instance.
    """
    config = LLMConfig(model=model, **kwargs)
    return GroqBackend(config)
