"""
OpenRouter LLM backend implementation.

Uses OpenRouter's unified API to access multiple LLM providers.
Free tier: 50 requests/day (1000 with $10 credit).

Requires:
    pip install openai
    
Environment:
    OPENROUTER_API_KEY - Your OpenRouter API key from https://openrouter.ai
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

# OpenRouter API endpoint (OpenAI-compatible)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Free models on OpenRouter (append :free to model name)
OPENROUTER_FREE_MODELS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-2-9b-it:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen-2-7b-instruct:free",
]

# Paid models (for reference)
OPENROUTER_PAID_MODELS = [
    "anthropic/claude-3.5-sonnet",
    "openai/gpt-4o-mini",
    "meta-llama/llama-3.1-70b-instruct",
    "google/gemini-pro-1.5",
]


class OpenRouterBackend(LLMBackend):
    """OpenRouter LLM backend using OpenAI-compatible API.
    
    OpenRouter provides access to multiple LLM providers through a single API.
    Append ':free' to model names for free tier access.
    
    Example:
        config = LLMConfig(
            model="meta-llama/llama-3.1-8b-instruct:free",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        backend = OpenRouterBackend(config)
        
        response = backend.generate(
            system="You are a code generator.",
            messages=[{"role": "user", "content": "Write hello world"}]
        )
        print(response.content)
    """
    
    def __init__(self, config: LLMConfig):
        """Initialize OpenRouter backend.
        
        Args:
            config: LLMConfig with model and optional API key.
                   API key defaults to OPENROUTER_API_KEY environment variable.
        """
        super().__init__(config)
        
        # Get API key from config or environment
        self.api_key = config.api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise AuthenticationError(
                "OpenRouter API key not provided. Set OPENROUTER_API_KEY "
                "environment variable or pass api_key in LLMConfig."
            )
        
        # Use provided base_url or default
        self.base_url = config.base_url or OPENROUTER_BASE_URL
        
        # Site info for OpenRouter (helps with rate limits)
        self.site_url = config.extra.get("site_url", "https://github.com/thesis-sbst")
        self.site_name = config.extra.get("site_name", "Thesis SBST Framework")
        
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
                default_headers={
                    "HTTP-Referer": self.site_url,
                    "X-Title": self.site_name,
                },
            )
        return self._client
    
    @property
    def provider_name(self) -> str:
        return "OpenRouter"
    
    def is_available(self) -> bool:
        """Check if OpenRouter API is accessible."""
        if not self.api_key:
            return False
        try:
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
        """Generate a response using OpenRouter API.
        
        Args:
            system: System message (string or list of content blocks).
            messages: List of user/assistant message dicts.
            **kwargs: Additional parameters.
            
        Returns:
            LLMResponse with generated content.
        """
        start_time = time.perf_counter()
        
        # Build messages list
        all_messages = []
        
        # Handle system message
        if isinstance(system, list):
            system_text = "\n".join(
                block.get("text", "") for block in system
                if isinstance(block, dict) and "text" in block
            )
        else:
            system_text = system
        
        if system_text:
            all_messages.append({"role": "system", "content": system_text})
        
        all_messages.extend(messages)
        
        # Prepare request parameters
        request_params = {
            "model": self.config.model,
            "messages": all_messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }
        
        try:
            response = self.client.chat.completions.create(**request_params)
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            choice = response.choices[0]
            content = choice.message.content or ""
            
            return LLMResponse(
                content=content,
                model=response.model,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                latency_ms=latency_ms,
                finish_reason=choice.finish_reason or "stop",
                raw_response=response,
            )
            
        except Exception as e:
            error_str = str(e).lower()
            
            if "rate limit" in error_str or "429" in error_str:
                raise RateLimitError(f"OpenRouter rate limit exceeded: {e}")
            elif "authentication" in error_str or "401" in error_str:
                raise AuthenticationError(f"OpenRouter authentication failed: {e}")
            elif "model" in error_str and "not found" in error_str:
                raise ModelNotFoundError(f"Model {self.config.model} not available: {e}")
            else:
                raise LLMError(f"OpenRouter API error: {e}")
    
    def list_models(self) -> list[str]:
        """List available models on OpenRouter."""
        try:
            models = self.client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            raise LLMError(f"Failed to list OpenRouter models: {e}")


def create_openrouter_backend(
    model: str = "meta-llama/llama-3.1-8b-instruct:free",
    **kwargs: Any,
) -> OpenRouterBackend:
    """Convenience function to create an OpenRouter backend.
    
    Args:
        model: Model identifier (append :free for free tier).
        **kwargs: Additional LLMConfig parameters.
        
    Returns:
        Configured OpenRouterBackend instance.
    """
    config = LLMConfig(model=model, **kwargs)
    return OpenRouterBackend(config)
