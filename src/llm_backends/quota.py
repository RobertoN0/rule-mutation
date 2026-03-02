"""
Quota tracking for LLM backends.

Tracks daily token and request usage to prevent hitting rate limits
mid-experiment. Provides pre-flight checks and warnings.

The tracker resets automatically at midnight UTC (matching Groq's reset).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LLMResponse


# Free tier rate limits per model (from https://console.groq.com/docs/rate-limits)
# Updated: March 2026
GROQ_FREE_TIER_LIMITS = {
    "llama-3.1-8b-instant": {
        "tpd": 500_000,   # tokens per day
        "rpd": 14_400,    # requests per day
        "tpm": 6_000,     # tokens per minute
        "rpm": 30,        # requests per minute
    },
    "llama-3.3-70b-versatile": {
        "tpd": 100_000,
        "rpd": 1_000,
        "tpm": 12_000,
        "rpm": 30,
    },
    "qwen/qwen3-32b": {
        "tpd": 500_000,
        "rpd": 1_000,
        "tpm": 6_000,
        "rpm": 60,
    },
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "tpd": 500_000,
        "rpd": 1_000,
        "tpm": 30_000,
        "rpm": 30,
    },
    "meta-llama/llama-4-maverick-17b-128e-instruct": {
        "tpd": 500_000,
        "rpd": 1_000,
        "tpm": 6_000,
        "rpm": 30,
    },
    # Conservative defaults for unknown models
    "_default": {
        "tpd": 100_000,
        "rpd": 1_000,
        "tpm": 6_000,
        "rpm": 30,
    },
}


@dataclass
class RateLimitInfo:
    """Rate limit information from API response headers.
    
    Extracted from Groq response headers:
    - x-ratelimit-limit-requests (RPD)
    - x-ratelimit-limit-tokens (TPM) 
    - x-ratelimit-remaining-requests (RPD remaining)
    - x-ratelimit-remaining-tokens (TPM remaining)
    """
    
    # Limits (from headers)
    limit_requests_per_day: int | None = None
    limit_tokens_per_minute: int | None = None
    
    # Remaining (from headers)
    remaining_requests_per_day: int | None = None
    remaining_tokens_per_minute: int | None = None
    
    # Reset times (from headers)
    reset_requests: str | None = None  # e.g., "2m59.56s"
    reset_tokens: str | None = None
    
    # Retry-after (only set on 429)
    retry_after_seconds: float | None = None
    
    @classmethod
    def from_headers(cls, headers: dict) -> "RateLimitInfo":
        """Parse rate limit info from HTTP response headers."""
        def safe_int(val: str | None) -> int | None:
            if val is None:
                return None
            try:
                return int(val)
            except ValueError:
                return None
        
        def safe_float(val: str | None) -> float | None:
            if val is None:
                return None
            try:
                return float(val)
            except ValueError:
                return None
        
        return cls(
            limit_requests_per_day=safe_int(headers.get("x-ratelimit-limit-requests")),
            limit_tokens_per_minute=safe_int(headers.get("x-ratelimit-limit-tokens")),
            remaining_requests_per_day=safe_int(headers.get("x-ratelimit-remaining-requests")),
            remaining_tokens_per_minute=safe_int(headers.get("x-ratelimit-remaining-tokens")),
            reset_requests=headers.get("x-ratelimit-reset-requests"),
            reset_tokens=headers.get("x-ratelimit-reset-tokens"),
            retry_after_seconds=safe_float(headers.get("retry-after")),
        )
    
    @property
    def has_data(self) -> bool:
        """Check if any rate limit data was extracted."""
        return any([
            self.limit_requests_per_day,
            self.remaining_requests_per_day,
            self.remaining_tokens_per_minute,
        ])


@dataclass
class QuotaUsage:
    """Current quota usage for a model."""
    
    model: str
    tokens_used_today: int = 0
    requests_used_today: int = 0
    last_reset_date: str = ""  # ISO date string (UTC)
    
    # Last known remaining values from API headers
    api_remaining_requests: int | None = None
    api_remaining_tokens_per_minute: int | None = None
    
    def get_limits(self) -> dict:
        """Get the rate limits for this model."""
        return GROQ_FREE_TIER_LIMITS.get(
            self.model, 
            GROQ_FREE_TIER_LIMITS["_default"]
        )
    
    @property
    def tokens_remaining_today(self) -> int:
        """Estimated tokens remaining for today."""
        limits = self.get_limits()
        return max(0, limits["tpd"] - self.tokens_used_today)
    
    @property
    def requests_remaining_today(self) -> int:
        """Estimated requests remaining for today."""
        limits = self.get_limits()
        return max(0, limits["rpd"] - self.requests_used_today)
    
    @property
    def usage_percent(self) -> float:
        """Percentage of daily quota used (based on tokens)."""
        limits = self.get_limits()
        return (self.tokens_used_today / limits["tpd"]) * 100


class QuotaTracker:
    """Tracks API quota usage across requests.
    
    Thread-safe tracker that:
    1. Accumulates token/request counts from each LLM call
    2. Updates with real remaining values from API headers
    3. Resets automatically at midnight UTC
    4. Provides pre-flight checks before experiments
    
    Usage:
        tracker = QuotaTracker()
        
        # After each LLM call
        tracker.record_usage(response)
        
        # Before an experiment
        if not tracker.check_quota("llama-3.1-8b-instant", 
                                   estimated_tokens=50000,
                                   estimated_requests=200):
            print("Warning: May exceed quota!")
        
        # Get current status
        usage = tracker.get_usage("llama-3.1-8b-instant")
        print(f"Used {usage.tokens_used_today:,} tokens today")
    """
    
    def __init__(self):
        self._usage: dict[str, QuotaUsage] = {}
        self._lock = threading.Lock()
    
    def _get_today(self) -> str:
        """Get today's date in UTC as ISO string."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    def _ensure_model(self, model: str) -> QuotaUsage:
        """Ensure a usage record exists for this model, resetting if new day."""
        today = self._get_today()
        
        if model not in self._usage:
            self._usage[model] = QuotaUsage(model=model, last_reset_date=today)
        
        usage = self._usage[model]
        
        # Auto-reset if it's a new day (midnight UTC)
        if usage.last_reset_date != today:
            usage.tokens_used_today = 0
            usage.requests_used_today = 0
            usage.last_reset_date = today
            usage.api_remaining_requests = None
            usage.api_remaining_tokens_per_minute = None
        
        return usage
    
    def record_usage(
        self,
        model: str,
        tokens_used: int,
        rate_limit_info: RateLimitInfo | None = None,
    ) -> QuotaUsage:
        """Record usage from an LLM response.
        
        Args:
            model: Model identifier
            tokens_used: Total tokens from the response
            rate_limit_info: Rate limit info from response headers
            
        Returns:
            Updated QuotaUsage for this model
        """
        with self._lock:
            usage = self._ensure_model(model)
            
            # Accumulate our tracked usage
            usage.tokens_used_today += tokens_used
            usage.requests_used_today += 1
            
            # Update with API-reported remaining values (more accurate)
            if rate_limit_info and rate_limit_info.has_data:
                if rate_limit_info.remaining_requests_per_day is not None:
                    usage.api_remaining_requests = rate_limit_info.remaining_requests_per_day
                if rate_limit_info.remaining_tokens_per_minute is not None:
                    usage.api_remaining_tokens_per_minute = rate_limit_info.remaining_tokens_per_minute
            
            return usage
    
    def get_usage(self, model: str) -> QuotaUsage:
        """Get current usage for a model."""
        with self._lock:
            return self._ensure_model(model)
    
    def check_quota(
        self,
        model: str,
        estimated_tokens: int,
        estimated_requests: int,
        warn_threshold: float = 0.8,
    ) -> tuple[bool, str]:
        """Pre-flight check: can we run an experiment without exceeding quota?
        
        Args:
            model: Model to check
            estimated_tokens: Estimated total tokens for the experiment
            estimated_requests: Estimated number of API calls
            warn_threshold: Warn if usage would exceed this fraction of limit (0.8 = 80%)
            
        Returns:
            Tuple of (is_safe, message)
            - is_safe: True if experiment can run without exceeding limits
            - message: Human-readable status/warning message
        """
        with self._lock:
            usage = self._ensure_model(model)
            limits = usage.get_limits()
            
            # Calculate projected usage
            projected_tokens = usage.tokens_used_today + estimated_tokens
            projected_requests = usage.requests_used_today + estimated_requests
            
            token_percent = (projected_tokens / limits["tpd"]) * 100
            request_percent = (projected_requests / limits["rpd"]) * 100
            
            # Check if we'd exceed limits
            if projected_tokens > limits["tpd"]:
                return False, (
                    f"❌ BLOCKED: Would exceed token limit!\n"
                    f"   Current: {usage.tokens_used_today:,} / {limits['tpd']:,} TPD\n"
                    f"   Requested: +{estimated_tokens:,} tokens\n"
                    f"   Projected: {projected_tokens:,} ({token_percent:.1f}% of limit)"
                )
            
            if projected_requests > limits["rpd"]:
                return False, (
                    f"❌ BLOCKED: Would exceed request limit!\n"
                    f"   Current: {usage.requests_used_today:,} / {limits['rpd']:,} RPD\n"
                    f"   Requested: +{estimated_requests:,} requests\n"
                    f"   Projected: {projected_requests:,} ({request_percent:.1f}% of limit)"
                )
            
            # Check if we'd hit warning threshold
            if token_percent >= warn_threshold * 100 or request_percent >= warn_threshold * 100:
                return True, (
                    f"⚠️  WARNING: Approaching quota limit\n"
                    f"   Tokens: {projected_tokens:,} / {limits['tpd']:,} ({token_percent:.1f}%)\n"
                    f"   Requests: {projected_requests:,} / {limits['rpd']:,} ({request_percent:.1f}%)"
                )
            
            return True, (
                f"✅ OK: Quota check passed\n"
                f"   Tokens: {projected_tokens:,} / {limits['tpd']:,} ({token_percent:.1f}%)\n"
                f"   Requests: {projected_requests:,} / {limits['rpd']:,} ({request_percent:.1f}%)"
            )
    
    def get_summary(self, model: str) -> str:
        """Get a human-readable summary of current usage."""
        usage = self.get_usage(model)
        limits = usage.get_limits()
        
        lines = [
            f"📊 Quota Status for {model}",
            f"   Date: {usage.last_reset_date} (UTC)",
            f"   Tokens: {usage.tokens_used_today:,} / {limits['tpd']:,} "
            f"({usage.usage_percent:.1f}%)",
            f"   Requests: {usage.requests_used_today:,} / {limits['rpd']:,}",
        ]
        
        if usage.api_remaining_requests is not None:
            lines.append(f"   API reports: {usage.api_remaining_requests:,} requests remaining today")
        
        return "\n".join(lines)
    
    def reset(self, model: str | None = None):
        """Reset usage tracking (for testing or manual reset).
        
        Args:
            model: Specific model to reset, or None to reset all
        """
        with self._lock:
            if model:
                if model in self._usage:
                    del self._usage[model]
            else:
                self._usage.clear()


# Global tracker instance for convenience
_global_tracker: QuotaTracker | None = None


def get_quota_tracker() -> QuotaTracker:
    """Get the global quota tracker instance."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = QuotaTracker()
    return _global_tracker
