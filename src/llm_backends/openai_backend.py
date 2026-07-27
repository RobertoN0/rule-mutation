"""
OpenAI LLM backend implementation.

Direct OpenAI Chat Completions API. Suitable for the replication path when
reviewers want to use GPT-4o-mini, GPT-4o, or a compatible current model.

Notes on quirks handled here:
- Reasoning models (the `o1*` / `o3*` family and `gpt-5*-thinking` variants)
  reject the legacy `max_tokens` parameter — they want `max_completion_tokens`
  instead and silently ignore `temperature`. We detect this from the model
  name and translate.
- The optional `organization` and `project` headers are forwarded from
  `LLMConfig.extra` when set.

Environment:
    OPENAI_API_KEY   - Your OpenAI API key from https://platform.openai.com/api-keys
    OPENAI_ORG       - (optional) Organization ID, forwarded to the SDK.
    OPENAI_PROJECT   - (optional) Project ID, forwarded to the SDK.
"""

from __future__ import annotations

import os
import time
from typing import Any

from .base import (
    AuthenticationError,
    LLMBackend,
    LLMConfig,
    LLMError,
    LLMResponse,
    ModelNotFoundError,
    RateLimitError,
)

OPENAI_BASE_URL = "https://api.openai.com/v1"

# Informational metadata only — any model name accepted by the API will work.
OPENAI_MODELS = {
    "gpt-4o-mini": {
        "context": 128_000,
        "description": "GPT-4o mini — cheap, fast, recommended for replication smoke tests",
    },
    "gpt-4o": {
        "context": 128_000,
        "description": "GPT-4o — balanced quality / speed",
    },
    "o1-mini": {
        "context": 128_000,
        "description": "o1-mini reasoning model (uses max_completion_tokens, ignores temperature)",
    },
    "o3-mini": {
        "context": 200_000,
        "description": "o3-mini reasoning model (uses max_completion_tokens, ignores temperature)",
    },
}


def _is_reasoning_model(model: str) -> bool:
    """Heuristic for OpenAI reasoning-family models with the alternate API surface."""
    lower = model.lower()
    return (
        lower.startswith("o1")
        or lower.startswith("o3")
        or lower.startswith("o4")
        or "thinking" in lower
    )


class OpenAIBackend(LLMBackend):
    """OpenAI Chat Completions backend.

    Example:
        config = LLMConfig(
            model="gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
            max_tokens=4096,
            temperature=0.0,
        )
        backend = OpenAIBackend(config)

        response = backend.generate(
            system="You are a careful, security-conscious code generator.",
            messages=[{"role": "user", "content": "Write a Python hello world."}],
        )
        print(response.content)
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)

        self.api_key = config.api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise AuthenticationError(
                "OpenAI API key not provided. Set OPENAI_API_KEY environment "
                "variable or pass api_key in LLMConfig."
            )

        self.base_url = config.base_url or OPENAI_BASE_URL
        self.organization = config.extra.get("organization") or os.getenv("OPENAI_ORG")
        self.project = config.extra.get("project") or os.getenv("OPENAI_PROJECT")

        self._client = None

    @property
    def client(self):
        """Lazy-load the OpenAI SDK client."""
        if self._client is None:
            try:
                from openai import OpenAI  # type: ignore
            except ImportError:
                raise LLMError(
                    "openai package not installed. Run: uv sync  (or pip install openai)"
                )

            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "timeout": self.config.timeout,
                "max_retries": self.config.max_retries,
            }
            if self.organization:
                kwargs["organization"] = self.organization
            if self.project:
                kwargs["project"] = self.project

            self._client = OpenAI(**kwargs)
        return self._client

    @property
    def provider_name(self) -> str:
        return "OpenAI"

    def is_available(self) -> bool:
        """Check if the OpenAI API is reachable with the configured credentials."""
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
        """Generate a response via the OpenAI Chat Completions API.

        Args:
            system: System prompt (string, or list of content blocks which we
                flatten into a single string for the SDK message contract).
            messages: List of {"role": ..., "content": ...} dicts.
            **kwargs: Optional overrides: `temperature`, `max_tokens`,
                `top_p`, `stop`, etc.

        Returns:
            LLMResponse with content, token counts, and latency.
        """
        start_time = time.perf_counter()

        # Flatten list-of-blocks system messages into a single string.
        if isinstance(system, list):
            system_text = "\n".join(
                block.get("text", "")
                for block in system
                if isinstance(block, dict) and "text" in block
            )
        else:
            system_text = system or ""

        all_messages: list[dict] = []
        if system_text:
            all_messages.append({"role": "system", "content": system_text})
        all_messages.extend(messages)

        is_reasoning = _is_reasoning_model(self.config.model)

        request_params: dict[str, Any] = {
            "model": self.config.model,
            "messages": all_messages,
        }

        # Reasoning models use max_completion_tokens and reject `temperature`.
        if is_reasoning:
            request_params["max_completion_tokens"] = kwargs.get(
                "max_tokens", self.config.max_tokens
            )
        else:
            request_params["max_tokens"] = kwargs.get("max_tokens", self.config.max_tokens)
            request_params["temperature"] = kwargs.get("temperature", self.config.temperature)

        # Pass-through optional knobs
        for opt in ("top_p", "stop", "presence_penalty", "frequency_penalty", "seed"):
            if opt in kwargs:
                request_params[opt] = kwargs[opt]

        try:
            response = self.client.chat.completions.create(**request_params)

            latency_ms = (time.perf_counter() - start_time) * 1000

            choice = response.choices[0]
            content = choice.message.content or ""

            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0

            return LLMResponse(
                content=content,
                model=response.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                finish_reason=choice.finish_reason or "stop",
                raw_response=response,
            )

        except Exception as e:
            try:
                import openai  # type: ignore
            except ImportError:
                openai = None  # type: ignore

            if openai is not None:
                if isinstance(e, openai.RateLimitError):
                    raise RateLimitError(f"OpenAI rate limit exceeded: {e}")
                if isinstance(e, openai.AuthenticationError):
                    raise AuthenticationError(f"OpenAI authentication failed: {e}")
                if isinstance(e, openai.NotFoundError):
                    raise ModelNotFoundError(
                        f"OpenAI model {self.config.model} not available: {e}"
                    )

            error_str = str(e).lower()
            if "rate limit" in error_str or "429" in error_str:
                raise RateLimitError(f"OpenAI rate limit exceeded: {e}")
            if "authentication" in error_str or "401" in error_str:
                raise AuthenticationError(f"OpenAI authentication failed: {e}")
            if "not_found" in error_str or "404" in error_str:
                raise ModelNotFoundError(f"OpenAI model not found: {e}")
            raise LLMError(f"OpenAI API error: {e}")

    def list_models(self) -> list[str]:
        """List models visible to the configured API key."""
        try:
            models = self.client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            raise LLMError(f"Failed to list OpenAI models: {e}")


def create_openai_backend(
    model: str = "gpt-4o-mini",
    **kwargs: Any,
) -> OpenAIBackend:
    """Build an OpenAI backend from an :class:`LLMConfig`."""
    config = LLMConfig(model=model, **kwargs)
    return OpenAIBackend(config)
