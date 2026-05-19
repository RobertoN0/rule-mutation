#!/usr/bin/env python3
"""
Validate the Anthropic Claude backend end-to-end.

This script is the replication-package smoke test: it verifies that the
ClaudeBackend can authenticate, send a request, and parse the response. It is
intentionally tiny (one generation, a few hundred tokens) so it is cheap to
run from any machine with an ANTHROPIC_API_KEY.

Usage:
    # Default (claude-haiku-4-5)
    uv run python scripts/validation/validate_claude.py

    # Pick a different model
    uv run python scripts/validation/validate_claude.py --model claude-sonnet-4-6

    # Echo the full response body
    uv run python scripts/validation/validate_claude.py --show-response

The script exits 0 on success, non-zero on any error. CI / Dockerfile health
checks can rely on the exit code.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _resolve_project_root() -> Path:
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.llm_backends.base import (  # noqa: E402
    AuthenticationError,
    LLMConfig,
    LLMError,
    ModelNotFoundError,
    RateLimitError,
)
from src.llm_backends.claude_backend import ClaudeBackend  # noqa: E402


# A deliberately small prompt — we only care that the round-trip works.
DEFAULT_SYSTEM = (
    "You are a concise assistant. Reply in 1-2 sentences. "
    "If asked to write code, write minimal, idiomatic Python."
)
DEFAULT_USER = (
    "Write a Python one-liner that prints the SHA-256 of the string 'replication-check'."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Anthropic Claude backend.")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help="Anthropic model identifier (default: claude-haiku-4-5).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=256,
        help="Cap response length to keep the smoke test cheap (default: 256).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature (default: 0.0 for determinism).",
    )
    parser.add_argument(
        "--show-response",
        action="store_true",
        help="Print the generated content (off by default — only print pass/fail).",
    )
    args = parser.parse_args()

    # Load .env from project root if present (no error if absent)
    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY is not set.")
        print("   Copy .env.example to .env and fill in your key, or export it manually:")
        print("     export ANTHROPIC_API_KEY=sk-ant-...")
        return 2

    print("=" * 70)
    print("🔎 Claude backend smoke test")
    print("=" * 70)
    print(f"   Model:        {args.model}")
    print(f"   Max tokens:   {args.max_tokens}")
    print(f"   Temperature:  {args.temperature}")
    print()

    config = LLMConfig(
        model=args.model,
        api_key=api_key,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    try:
        backend = ClaudeBackend(config)
    except AuthenticationError as e:
        print(f"❌ Auth error during backend init: {e}")
        return 2

    if not backend.is_available():
        print("❌ Backend reports not available (no API key)")
        return 2

    print("📡 Sending one generation request…")
    try:
        response = backend.generate(
            system=DEFAULT_SYSTEM,
            messages=[{"role": "user", "content": DEFAULT_USER}],
        )
    except AuthenticationError as e:
        print(f"❌ Authentication failed: {e}")
        return 2
    except ModelNotFoundError as e:
        print(f"❌ Model not found: {e}")
        print(f"   Check that '{args.model}' is a valid Anthropic model ID.")
        return 3
    except RateLimitError as e:
        print(f"❌ Rate-limited / overloaded: {e}")
        return 4
    except LLMError as e:
        print(f"❌ Backend error: {e}")
        return 5
    except Exception as e:  # noqa: BLE001
        print(f"❌ Unexpected error: {type(e).__name__}: {e}")
        return 6

    print()
    print("✅ Request succeeded.")
    print(f"   Model reported: {response.model}")
    print(f"   Input tokens:   {response.input_tokens}")
    print(f"   Output tokens:  {response.output_tokens}")
    print(f"   Total tokens:   {response.total_tokens}")
    print(f"   Latency:        {response.latency_ms:.0f} ms")
    print(f"   Finish reason:  {response.finish_reason}")

    if args.show_response:
        print()
        print("--- response content ---")
        print(response.content.strip())
        print("--- end response ---")

    if not response.content.strip():
        print()
        print("⚠️  Warning: response body was empty. The API call succeeded but no text was returned.")
        return 7

    print()
    print("🎉 Claude backend is wired up correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
