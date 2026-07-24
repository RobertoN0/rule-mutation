"""
Safe-zone-aware parser for CodeGuard security rule documents.

CodeGuard rules are Markdown files with three categories of content that must
never be mutated:
  1. YAML frontmatter  — between the opening and closing --- delimiters
  2. Fenced code blocks — ```language ... ``` sections (Java, C, Python, etc.)
  3. Inline code spans  — `backtick-wrapped` terms (algorithm names, CWE IDs, etc.)

The parser splits a rule document into an ordered list of Block objects,
where only prose blocks (type="prose") are mutable.  Mutators call
``get_mutable_prose()`` to receive the text they are allowed to edit, then
call ``reconstruct()`` with their modified versions to reassemble the document.

Inline code protection within prose blocks is a separate concern handled by
the ``mask_inline_code`` / ``unmask_inline_code`` helpers, which mutators
should use before and after applying any word-level transformation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import yaml


# ---------------------------------------------------------------------------
# Compiled regexes
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

# Matches a fenced code block: ``` optionally followed by a language tag,
# then the block body, then a closing ```.  The trailing newline is optional
# so that blocks at end-of-file are also captured.
_CODE_BLOCK_RE = re.compile(r"(```[^\n]*\n.*?```[ \t]*\n?)", re.DOTALL)

# Matches inline code: a backtick span that does not span a newline.
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

# Matches a level-2 section header (## but NOT ###).
_H2_HEADER_RE = re.compile(r"^(## .+\n?)", re.MULTILINE)

# Matches a level-3 section header (### but NOT ####).
_H3_HEADER_RE = re.compile(r"^(### .+\n?)", re.MULTILINE)

# Matches any markdown section header (# through ####).
_ANY_HEADER_RE = re.compile(r"^(#{1,4}\s)", re.MULTILINE)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Block:
    """A contiguous segment of a rule document."""

    id: int
    """Stable numeric identifier within the containing ParsedRule."""

    type: Literal["prose", "code"]
    """
    prose — natural language text; may be passed to mutators.
    code  — fenced code block; must not be modified.
    """

    text: str
    """Raw text of the block, including any surrounding whitespace."""

    @property
    def mutable(self) -> bool:
        """True iff this block is safe to mutate."""
        return self.type == "prose"


@dataclass
class Section:
    """
    A top-level (##) section of the document body.

    Used by SectionReorderMutator to shuffle or degrade sections without
    affecting YAML frontmatter or fenced code blocks.
    """

    header: str
    """Full header line including '## ' prefix and trailing newline."""

    header_level: int
    """2 for ##, 3 for ###, etc."""

    body: str
    """
    Everything after the header up to (but not including) the next
    top-level section header.  May itself contain ### subsections and
    fenced code blocks — those must not be mutated.
    """

    @property
    def full_text(self) -> str:
        """Reconstruct the section's complete text."""
        return self.header + self.body


@dataclass
class ParsedRule:
    """
    Structured representation of a parsed CodeGuard rule document.

    Attributes
    ----------
    frontmatter_raw:
        The raw YAML frontmatter block including the ``---`` delimiters and
        the trailing newline.  Always immutable.
    frontmatter:
        Parsed YAML content as a Python dict (uses pyyaml).  Empty dict if
        no valid frontmatter was found.
    body_raw:
        The document body text after the frontmatter.
    body_blocks:
        Ordered list of Block objects.  The concatenation of all block texts
        equals ``body_raw`` exactly.
    raw:
        The complete original document text (frontmatter + body).
    """

    frontmatter_raw: str
    frontmatter: dict
    body_raw: str
    body_blocks: list[Block]
    raw: str

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> "ParsedRule":
        """Parse a rule document string into a ParsedRule.

        Parameters
        ----------
        text:
            Full content of a CodeGuard .md rule file.
        """
        # 1. Extract YAML frontmatter
        m = _FRONTMATTER_RE.match(text)
        if m:
            frontmatter_raw = m.group(0)
            try:
                frontmatter = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                frontmatter = {}
            body_raw = text[m.end():]
        else:
            frontmatter_raw = ""
            frontmatter = {}
            body_raw = text

        # 2. Split body into prose and fenced code blocks.
        #    re.split on a capturing group alternates: [prose, code, prose, …]
        raw_parts = _CODE_BLOCK_RE.split(body_raw)
        body_blocks: list[Block] = []
        block_id = 0
        for i, part in enumerate(raw_parts):
            if not part:
                continue
            block_type: Literal["prose", "code"] = "prose" if i % 2 == 0 else "code"
            body_blocks.append(Block(id=block_id, type=block_type, text=part))
            block_id += 1

        return cls(
            frontmatter_raw=frontmatter_raw,
            frontmatter=frontmatter,
            body_raw=body_raw,
            body_blocks=body_blocks,
            raw=text,
        )

    # ------------------------------------------------------------------
    # Mutable content access
    # ------------------------------------------------------------------

    def get_mutable_prose(self) -> list[tuple[int, str]]:
        """Return (block_id, text) pairs for all mutable prose blocks."""
        return [(b.id, b.text) for b in self.body_blocks if b.mutable]

    def reconstruct(self, mutations: dict[int, str]) -> str:
        """Reassemble the full document, substituting mutated prose blocks.

        Parameters
        ----------
        mutations:
            Mapping from block_id → new text.  Blocks whose ids are not in
            this mapping are reproduced verbatim.

        Returns
        -------
        str
            Complete document text with mutations applied.  The frontmatter
            and all code blocks are always reproduced unchanged.
        """
        parts: list[str] = [self.frontmatter_raw]
        for block in self.body_blocks:
            if block.mutable and block.id in mutations:
                parts.append(mutations[block.id])
            else:
                parts.append(block.text)
        return "".join(parts)

    # ------------------------------------------------------------------
    # Section-level view (for SectionReorderMutator)
    # ------------------------------------------------------------------

    @property
    def sections(self) -> list[Section]:
        """Split the body into reorderable sections.

        Auto-detects the appropriate header level:
        - If there are 2+ ``##`` headers  → split on ``##``  (codeguard-1-* rules)
        - If there is only 1 ``##`` header → split on ``###`` (codeguard-0-* rules,
          where the ``##`` line is a single top-level title and all meaningful
          subsections are ``###``)
        - If there are no headers at all   → entire body is a single preamble section

        The portion of the body before the first header at the chosen level is
        returned as a Section with header="" and header_level=0 (the "preamble").
        """
        h2_count = len(_H2_HEADER_RE.findall(self.body_raw))

        if h2_count >= 2:
            pattern = _H2_HEADER_RE
            level = 2
        else:
            # Fall through to ### level (covers single-## rules and no-## rules)
            pattern = _H3_HEADER_RE
            level = 3

        parts = pattern.split(self.body_raw)
        # parts layout: [pre_header, header1, body1, header2, body2, ...]
        result: list[Section] = []

        # Preamble (before first header at chosen level — keep it pinned first)
        preamble = parts[0]
        if preamble.strip():
            result.append(Section(header="", header_level=0, body=preamble))

        idx = 1
        while idx < len(parts) - 1:
            header = parts[idx]
            body = parts[idx + 1]
            result.append(Section(header=header, header_level=level, body=body))
            idx += 2

        return result

    def reconstruct_from_sections(self, sections: list[Section]) -> str:
        """Reassemble the full document from a (possibly reordered) section list.

        Only the body is reordered; the frontmatter is always prepended unchanged.
        """
        body = "".join(s.full_text for s in sections)
        return self.frontmatter_raw + body

    # ------------------------------------------------------------------
    # Inline code helpers (used by word-level mutators)
    # ------------------------------------------------------------------

    @staticmethod
    def get_inline_code_tokens(text: str) -> list[str]:
        """Return all backtick-wrapped tokens found in text."""
        return _INLINE_CODE_RE.findall(text)


# ---------------------------------------------------------------------------
# Inline code masking helpers (module-level; used by mutators)
# ---------------------------------------------------------------------------

def mask_inline_code(text: str) -> tuple[str, dict[str, str]]:
    """Replace inline code spans with stable unique placeholders.

    Mutators should call this before any word-level transformation, then call
    ``unmask_inline_code`` on the result to restore all inline code tokens.

    Returns
    -------
    masked_text:
        The text with all ``...`` spans replaced by ``__IC_0__``, ``__IC_1__``, etc.
    restore_map:
        Mapping placeholder → original token, for use with ``unmask_inline_code``.
    """
    restore_map: dict[str, str] = {}
    counter = [0]

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        token = m.group(0)
        placeholder = f"__IC_{counter[0]}__"
        restore_map[placeholder] = token
        counter[0] += 1
        return placeholder

    masked = _INLINE_CODE_RE.sub(_replace, text)
    return masked, restore_map


def unmask_inline_code(text: str, restore_map: dict[str, str]) -> str:
    """Restore placeholders inserted by ``mask_inline_code``."""
    for placeholder, original in restore_map.items():
        text = text.replace(placeholder, original)
    return text
