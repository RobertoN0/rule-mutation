#!/usr/bin/env python3
"""
Spike: Validate Groq Free Tier for Iterative Testing

This script tests the Groq free tier to verify:
1. API connectivity works
2. Rate limits allow iterative hill climbing
3. Latency is acceptable for rapid iteration
4. Model outputs are suitable for code generation

Usage:
    export GROQ_API_KEY=gsk_...
    python scripts/validate_groq.py

    # Test specific model:
    python scripts/validate_groq.py --model llama-3.3-70b-versatile
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Free tier rate limits per model (from https://console.groq.com/docs/rate-limits)
# TPD = Tokens Per Day, RPD = Requests Per Day, TPM = Tokens Per Minute
GROQ_FREE_TIER_LIMITS = {
    "llama-3.1-8b-instant": {"tpd": 500_000, "rpd": 14_400, "tpm": 6_000},
    "llama-3.3-70b-versatile": {"tpd": 100_000, "rpd": 1_000, "tpm": 12_000},
    "qwen/qwen3-32b": {"tpd": 500_000, "rpd": 1_000, "tpm": 6_000},
    "meta-llama/llama-4-scout-17b-16e-instruct": {"tpd": 500_000, "rpd": 1_000, "tpm": 30_000},
    "meta-llama/llama-4-maverick-17b-128e-instruct": {"tpd": 500_000, "rpd": 1_000, "tpm": 6_000},
    # Default for unknown models (conservative estimate)
    "_default": {"tpd": 100_000, "rpd": 1_000, "tpm": 6_000},
}


def get_model_limits(model: str) -> dict:
    """Get rate limits for a model, falling back to conservative defaults."""
    return GROQ_FREE_TIER_LIMITS.get(model, GROQ_FREE_TIER_LIMITS["_default"])


def main():
    parser = argparse.ArgumentParser(description="Validate Groq free tier")
    parser.add_argument(
        "--model", "-m",
        default="llama-3.1-8b-instant",
        help="Model to test (default: llama-3.1-8b-instant)"
    )
    parser.add_argument(
        "--num-calls", "-n",
        type=int,
        default=5,
        help="Number of test API calls (default: 5)"
    )
    args = parser.parse_args()
    
    print("=" * 60)
    print("🧪 Groq Free Tier Validation")
    print("=" * 60)

    load_dotenv()
    
    # Check API key
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("\n❌ GROQ_API_KEY environment variable not set")
        print("   Get your key from: https://console.groq.com")
        return 1
    
    print(f"\n✅ API key found: {api_key[:8]}...")
    
    # Import backend
    try:
        from src.llm_backends import GroqBackend, LLMConfig
        from src.llm_backends.base import LLMError, RateLimitError
    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        return 1
    
    # Create backend
    print(f"\n🤖 Testing model: {args.model}")
    config = LLMConfig(
        model=args.model,
        api_key=api_key,
        temperature=0.0,
        max_tokens=256,
    )
    
    try:
        backend = GroqBackend(config)
    except Exception as e:
        print(f"❌ Failed to create backend: {e}")
        return 1
    
    # Test connectivity
    print("\n📡 Testing API connectivity...")
    try:
        if backend.is_available():
            print("   ✅ API connection successful")
        else:
            print("   ❌ API connection failed")
            return 1
    except Exception as e:
        print(f"   ❌ Connection error: {e}")
        return 1
    
    # List available models
    print("\n📋 Available models:")
    try:
        models = backend.list_models()
        for m in sorted(models)[:10]:  # Show first 10
            marker = "→" if args.model in m else " "
            print(f"   {marker} {m}")
        if len(models) > 10:
            print(f"   ... and {len(models) - 10} more")
    except Exception as e:
        print(f"   ⚠️  Could not list models: {e}")
    
    # Test generation
    print(f"\n🔄 Running {args.num_calls} test generations...")
    
    test_prompts = [
        "Write a Python function to add two numbers.",
        "Create a simple SQL query to select all users.",
        "Write a JavaScript function to reverse a string.",
        "Implement a Python class for a basic calculator.",
        "Write a bash script to list files in a directory.",
    ]
    
    latencies = []
    token_counts = []
    errors = []
    
    for i, prompt in enumerate(test_prompts[:args.num_calls]):
        print(f"\n   [{i+1}/{args.num_calls}] {prompt[:40]}...")
        
        try:
            start = time.perf_counter()
            response = backend.generate(
                system="You are a code generator. Output only code, no explanations.",
                messages=[{"role": "user", "content": prompt}],
            )
            latency = (time.perf_counter() - start) * 1000
            
            latencies.append(latency)
            token_counts.append(response.total_tokens)
            
            # Show snippet of output
            code_preview = response.content[:100].replace("\n", " ")
            print(f"       Latency: {latency:.0f}ms | Tokens: {response.total_tokens}")
            print(f"       Output: {code_preview}...")
            
        except RateLimitError as e:
            print(f"       ⚠️  Rate limited: {e}")
            errors.append(("rate_limit", str(e)))
            time.sleep(2)  # Wait before continuing
            
        except LLMError as e:
            print(f"       ❌ Error: {e}")
            errors.append(("error", str(e)))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 RESULTS SUMMARY")
    print("=" * 60)
    
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)
        avg_tokens = sum(token_counts) / len(token_counts)
        
        print(f"\nSuccessful calls: {len(latencies)}/{args.num_calls}")
        print(f"\nLatency:")
        print(f"  Average: {avg_latency:.0f}ms")
        print(f"  Min:     {min_latency:.0f}ms")
        print(f"  Max:     {max_latency:.0f}ms")
        print(f"\nTokens per call: ~{avg_tokens:.0f}")
        
        # Estimate capacity
        calls_per_minute = 60_000 / avg_latency
        print(f"\nEstimated capacity: ~{calls_per_minute:.0f} calls/minute (latency-limited)")
        
        # Get model-specific free tier limits
        limits = get_model_limits(args.model)
        tokens_per_day = limits["tpd"]
        requests_per_day = limits["rpd"]
        
        estimated_calls_by_tokens = tokens_per_day / avg_tokens
        # The actual limit is the minimum of token-based and request-based limits
        estimated_calls = min(estimated_calls_by_tokens, requests_per_day)
        
        print(f"\nFree tier limits for {args.model}:")
        print(f"  TPD (tokens/day):   {tokens_per_day:,}")
        print(f"  RPD (requests/day): {requests_per_day:,}")
        print(f"  TPM (tokens/min):   {limits['tpm']:,}")
        print(f"\nEstimated calls/day: ~{estimated_calls:.0f}")
        if estimated_calls == requests_per_day:
            print(f"  ⚠️  Limited by RPD ({requests_per_day:,}), not tokens")
    
    if errors:
        print(f"\n⚠️  Errors encountered: {len(errors)}")
        for err_type, err_msg in errors:
            print(f"   - {err_type}: {err_msg[:50]}...")
    
    # Verdict
    print("\n" + "-" * 60)
    if len(latencies) == args.num_calls and not errors:
        print("✅ Groq free tier is suitable for hill climbing!")
        print("   - Fast latency allows rapid iteration")
        print("   - Free tier provides enough tokens for MVP experiments")
        return 0
    elif len(latencies) > 0:
        print("⚠️  Groq works but with some issues")
        print("   - Check rate limits and adjust request frequency")
        return 0
    else:
        print("❌ Groq free tier has issues")
        return 1


if __name__ == "__main__":
    sys.exit(main())
