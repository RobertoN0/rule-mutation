"""
Anthropic Claude LLM backend implementation.

Uses the official `anthropic` Python SDK. Compared with the OpenAI and local
transformer backends, Anthropic's API has a few shape differences:

- The system prompt is a top-level `system=` kwarg, NOT a `{"role": "system"}`
  message.
- `max_tokens` is REQUIRED on every request.
- Response content is a list of typed content blocks; text comes from
  `response.content[i].text` for blocks of type "text".
- Token usage is `response.usage.input_tokens` / `output_tokens` (no
  `prompt_tokens` / `completion_tokens`).

Environment:
    ANTHROPIC_API_KEY - Your Anthropic API key from https://console.anthropic.com
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

# Default Anthropic API base URL (the SDK uses this automatically, but we
# expose it so LLMConfig.base_url can override for proxies / mocks).
ANTHROPIC_BASE_URL = "https://api.anthropic.com"

# Convenience metadata for the most common Claude models at the time of writing.
# This is informational only — any model name accepted by the API will work.
CLAUDE_MODELS = {
    "claude-haiku-4-5": {
        "context": 200_000,
        "description": "Claude Haiku 4.5 — cheapest, recommended for replication smoke tests",
    },
    "claude-sonnet-4-6": {
        "context": 200_000,
        "description": "Claude Sonnet 4.6 — balanced speed/quality",
    },
    "claude-opus-4-7": {
        "context": 200_000,
        "description": "Claude Opus 4.7 — highest quality",
    },
}


class ClaudeBackend(LLMBackend):
    """Anthropic Claude backend.

    Example:
        config = LLMConfig(
            model="claude-haiku-4-5",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_tokens=4096,
        )
        backend = ClaudeBackend(config)

        response = backend.generate(
            system="You are a careful, security-conscious code generator.",
            messages=[{"role": "user", "content": "Write a Python hello world."}],
        )
        print(response.content)
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)

        self.api_key = config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise AuthenticationError(
                "Anthropic API key not provided. Set ANTHROPIC_API_KEY environment "
                "variable or pass api_key in LLMConfig."
            )

        self.base_url = config.base_url or ANTHROPIC_BASE_URL
        self._client = None

    @property
    def client(self):
        """Lazy-load the Anthropic SDK client."""
        if self._client is None:
            try:
                from anthropic import Anthropic  # type: ignore
            except ImportError:
                raise LLMError(
                    "anthropic package not installed. Run: uv sync  (or pip install anthropic)"
                )

            self._client = Anthropic(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
            )
        return self._client

    @property
    def provider_name(self) -> str:
        return "Anthropic"

    def is_available(self) -> bool:
        """Check that an API key is configured.

        Anthropic does not expose a cheap unauthenticated "list models" call,
        so we do not make a network round-trip here — the first real
        `generate()` will surface auth/model errors via mapped exceptions.
        """
        return bool(self.api_key)

    def generate(
        self,
        system: str | list[dict],
        messages: list[dict],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response using the Anthropic Messages API.

        Args:
            system: System prompt. May be a plain string or a list of content
                blocks (the latter enables prompt caching via cache_control
                markers — passed through to the SDK as-is).
            messages: List of user/assistant message dicts in the standard
                {"role": ..., "content": ...} format. System messages MUST NOT
                appear here — pass them via the `system` argument.
            **kwargs: Optional overrides: `temperature`, `max_tokens`,
                `stop_sequences`, `top_p`, `top_k`, etc.

        Returns:
            LLMResponse with the generated text and token usage.
        """
        start_time = time.perf_counter()

        # Anthropic forbids system messages inside `messages`. If somebody
        # accidentally passes one, route it into `system` to be forgiving.
        cleaned_messages: list[dict] = []
        injected_system: list[str] = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    injected_system.append(content)
            else:
                cleaned_messages.append(msg)

        if isinstance(system, str):
            system_arg: Any = system
            if injected_system:
                system_arg = "\n".join([system, *injected_system]) if system else "\n".join(injected_system)
        else:
            # Already a list of content blocks — pass through; ignore any
            # accidental system messages from `messages` in this case.
            system_arg = system

        request_params: dict[str, Any] = {
            "model": self.config.model,
            "system": system_arg,
            "messages": cleaned_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
        }

        # Pass through any extra Anthropic-specific params explicitly listed
        for opt in ("top_p", "top_k", "stop_sequences", "metadata"):
            if opt in kwargs:
                request_params[opt] = kwargs[opt]

        try:
            response = self.client.messages.create(**request_params)

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Concatenate all text blocks (typically there is only one).
            text_parts = [
                getattr(block, "text", "")
                for block in response.content
                if getattr(block, "type", None) == "text"
            ]
            content = "".join(text_parts)

            usage = response.usage
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

            return LLMResponse(
                content=content,
                model=response.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                finish_reason=getattr(response, "stop_reason", "stop") or "stop",
                raw_response=response,
            )

        except Exception as e:
            # Defer-import so the module loads without anthropic installed
            try:
                import anthropic  # type: ignore
            except ImportError:
                anthropic = None  # type: ignore

            if anthropic is not None:
                if isinstance(e, anthropic.RateLimitError):
                    raise RateLimitError(f"Anthropic rate limit exceeded: {e}")
                if isinstance(e, anthropic.AuthenticationError):
                    raise AuthenticationError(f"Anthropic authentication failed: {e}")
                if isinstance(e, anthropic.NotFoundError):
                    raise ModelNotFoundError(
                        f"Anthropic model {self.config.model} not available: {e}"
                    )
                # Overloaded (529) is transient on Anthropic's side — surface as rate-limit
                # so the experiment runner's existing retry/exit logic handles it.
                if isinstance(e, anthropic.APIStatusError) and getattr(e, "status_code", None) == 529:
                    raise RateLimitError(f"Anthropic overloaded (529): {e}")

            # Fallback string matching for environments where the SDK class
            # hierarchy differs.
            error_str = str(e).lower()
            if "rate limit" in error_str or "429" in error_str:
                raise RateLimitError(f"Anthropic rate limit exceeded: {e}")
            if "authentication" in error_str or "401" in error_str:
                raise AuthenticationError(f"Anthropic authentication failed: {e}")
            if "not_found" in error_str or "404" in error_str:
                raise ModelNotFoundError(f"Anthropic model not found: {e}")
            raise LLMError(f"Anthropic API error: {e}")


def create_claude_backend(
    model: str = "claude-haiku-4-5",
    **kwargs: Any,
) -> ClaudeBackend:
    """Build a Claude backend from an :class:`LLMConfig`."""
    config = LLMConfig(model=model, **kwargs)
    return ClaudeBackend(config)
