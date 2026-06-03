"""
Corpus-derived security keyword lexicon for CodeGuard rule mutation.

Builds a frequency-based lexicon from the prose text of all CodeGuard rule
.md files.  Stopwords are removed; the top-N most frequent tokens across the
corpus are returned as a frozenset and cached after the first build.

Two call sites:
  - quality.py  — keyword_retention gate in MutationQualityValidator
  - rule_based.py — security-keyword density scoring in SectionReorderMutator
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Common English function words excluded from the lexicon.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "not", "no", "nor", "so", "yet",
    "both", "either", "neither", "whether", "that", "this", "these", "those",
    "it", "its", "they", "them", "their", "you", "your", "we", "our",
    "he", "his", "she", "her", "who", "which", "what", "when", "where",
    "how", "than", "then", "as", "all", "any", "each", "more", "most",
    "only", "also", "such", "other", "same", "new", "one", "two",
    "into", "about", "up", "out", "over", "after", "before", "between",
    "during", "while", "well", "s", "t", "re", "ve",
})

# Curated lexicon — derived from the 23 CodeGuard .md files (top-60, min_doc_freq=2)
# then hand-curated: removed frontmatter artifacts (codeguard, rule_id) and generic
# tokens (code, use, using, string, set, via, side, size); added security-specific
# terms from the next frequency tier (api, client, credentials, disable, permissions,
# sql, strict, tls, unsafe, verify).
# To regenerate: call build_security_lexicon(rules_dir) and compare with this set.
_SECURITY_LEXICON: frozenset[str] = frozenset({
    "access", "allow", "always", "api", "authentication", "authorization",
    "avoid", "certificate", "checks", "client", "configure", "content",
    "controls", "credentials", "data", "database", "disable", "enable",
    "encryption", "enforce", "ensure", "file", "functions", "https",
    "implement", "injection", "input", "key", "keys", "limits", "log",
    "network", "never", "permissions", "prefer", "prevent", "privilege",
    "require", "required", "risk", "safe", "secrets", "secure", "security",
    "sensitive", "server", "services", "session", "sql", "storage", "store",
    "strict", "tests", "tls", "tokens", "unsafe", "user", "validate",
    "validation", "verify",
})

def build_security_lexicon(
    rules_dir: Path,
    top_n: int = 60,
    min_doc_freq: int = 2,
) -> frozenset[str]:
    """Build a frequency-based security keyword lexicon from CodeGuard rule prose.

    Reads all .md files in rules_dir, extracts prose blocks (skipping frontmatter
    and fenced code blocks via ParsedRule), tokenises to lowercase tokens of length
    > 2, removes stopwords, and returns the top_n tokens by corpus frequency that
    appear in at least min_doc_freq files.

    Parameters
    ----------
    rules_dir:
        Directory containing CodeGuard .md rule files.
    top_n:
        Maximum number of terms in the returned lexicon (default 60).
    min_doc_freq:
        Minimum number of files a term must appear in to be included (default 2).
    """
    from .rule_parser import ParsedRule  # local import avoids circular deps at module load

    corpus_freq: dict[str, int] = {}
    doc_freq: dict[str, int] = {}
    n_files = 0

    for md_file in sorted(rules_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("Skipping %s (read error): %s", md_file.name, exc)
            continue

        try:
            parsed = ParsedRule.parse(text)
        except Exception as exc:
            log.warning("Skipping %s (parse error): %s", md_file.name, exc)
            continue

        # Collect only prose blocks (type == "prose"); skip fenced code blocks.
        prose = " ".join(
            block.text for block in parsed.body_blocks if block.type == "prose"
        )

        tokens = [
            tok
            for tok in re.split(r"\W+", prose.lower())
            if len(tok) > 2 and tok not in _STOPWORDS
        ]

        seen_this_file: set[str] = set()
        for tok in tokens:
            corpus_freq[tok] = corpus_freq.get(tok, 0) + 1
            seen_this_file.add(tok)

        for tok in seen_this_file:
            doc_freq[tok] = doc_freq.get(tok, 0) + 1

        n_files += 1

    log.info("Security lexicon: scanned %d rule files", n_files)

    candidates = {
        tok: count
        for tok, count in corpus_freq.items()
        if doc_freq.get(tok, 0) >= min_doc_freq
    }
    top_tokens = sorted(candidates, key=lambda t: -candidates[t])[:top_n]
    lexicon = frozenset(top_tokens)

    log.info(
        "Security lexicon: %d terms selected (top_n=%d, min_doc_freq=%d)",
        len(lexicon), top_n, min_doc_freq,
    )
    return lexicon


def get_security_lexicon(rules_dir: Path | None = None) -> frozenset[str]:
    """Return the hardcoded curated security lexicon.

    ``rules_dir`` is accepted for backward compatibility but ignored — the
    lexicon is now a pinned literal so experiment results are reproducible
    even if the CodeGuard rule corpus changes.  To rebuild from the corpus,
    call :func:`build_security_lexicon` directly.
    """
    return _SECURITY_LEXICON
