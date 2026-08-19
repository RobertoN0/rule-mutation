#!/usr/bin/env python3
"""Audit and structurally sanitize selected Phase-3 chromosomes.

The original search artifacts are never edited. For every candidate that fails
the strict safe-zone contract, this script writes a versioned override directory
whose frontmatter, fenced blocks, and prose inline-code multiset exactly match
the corresponding original CodeGuard rules. Candidate prose and rule ordering
are retained wherever they are outside those protected regions.

This is a post-hoc repair utility, not a replay of the adaptive search. Its JSON
manifest deliberately links raw and sanitized hashes so the two treatments
cannot be confused.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
from collections import Counter
from functools import lru_cache
from pathlib import Path


FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
FENCE_RE = re.compile(r"```[^\n]*\n.*?```[ \t]*(?:\n|$)", re.DOTALL)
# Tolerate the observed malformed `````## next-header`` close when repairing.
RELAXED_FENCE_RE = re.compile(r"```[^\n]*\n.*?```[ \t]*\n?", re.DOTALL)
INLINE_RE = re.compile(r"`[^`\n]+`")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def corpus_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.md")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    return match.group(0) if match else ""


def split_fences(text: str, *, relaxed: bool = False) -> tuple[str, list[str]]:
    pattern = RELAXED_FENCE_RE if relaxed else FENCE_RE
    blocks: list[str] = []

    def replace(match: re.Match[str]) -> str:
        marker = f"__FENCE_SLOT_{len(blocks):04d}__"
        blocks.append(match.group(0))
        return marker

    return pattern.sub(replace, text), blocks


def restore_fences(text: str, blocks: list[str]) -> str:
    for index, block in enumerate(blocks):
        text = text.replace(f"__FENCE_SLOT_{index:04d}__", block, 1)
    return text


def protected_signature(text: str) -> dict:
    prose, fences = split_fences(text)
    return {
        "frontmatter": frontmatter(text),
        "fences": Counter(fences),
        "inline": Counter(INLINE_RE.findall(prose)),
        "triple_ticks": text.count("```"),
    }


def signature_delta(original: str, candidate: str) -> dict:
    before = protected_signature(original)
    after = protected_signature(candidate)
    return {
        "frontmatter_equal": before["frontmatter"] == after["frontmatter"],
        "missing_fences": sum((before["fences"] - after["fences"]).values()),
        "added_fences": sum((after["fences"] - before["fences"]).values()),
        "missing_inline": list((before["inline"] - after["inline"]).elements()),
        "added_inline": list((after["inline"] - before["inline"]).elements()),
        "original_triple_ticks": before["triple_ticks"],
        "candidate_triple_ticks": after["triple_ticks"],
    }


def is_valid(delta: dict) -> bool:
    return (
        delta["frontmatter_equal"]
        and delta["missing_fences"] == 0
        and delta["added_fences"] == 0
        and not delta["missing_inline"]
        and not delta["added_inline"]
        and delta["original_triple_ticks"] == delta["candidate_triple_ticks"]
    )


def normalized_fence(block: str) -> str:
    lines = block.strip().splitlines()
    if len(lines) >= 2:
        lines = lines[1:-1]
    return "\n".join(lines).lower()


def repair_fences(original: str, candidate: str) -> tuple[str, list[str]]:
    original_prose, original_blocks = split_fences(original, relaxed=True)
    del original_prose
    candidate_slots, candidate_blocks = split_fences(candidate, relaxed=True)
    if len(original_blocks) != len(candidate_blocks):
        raise ValueError(
            "cannot safely pair fenced blocks: "
            f"original={len(original_blocks)} candidate={len(candidate_blocks)}"
        )
    if not original_blocks:
        return candidate, []

    # Pair by content similarity rather than position because section reordering
    # can legitimately move a complete fenced block with its containing section.
    scores = [
        [
            difflib.SequenceMatcher(
                None,
                normalized_fence(candidate_block),
                normalized_fence(original_block),
            ).ratio()
            for original_block in original_blocks
        ]
        for candidate_block in candidate_blocks
    ]

    @lru_cache(maxsize=None)
    def best_assignment(candidate_index: int, used_mask: int) -> tuple[float, tuple[int, ...]]:
        if candidate_index == len(candidate_blocks):
            return 0.0, ()
        options: list[tuple[float, tuple[int, ...]]] = []
        for original_index in range(len(original_blocks)):
            if used_mask & (1 << original_index):
                continue
            tail_score, tail = best_assignment(
                candidate_index + 1, used_mask | (1 << original_index)
            )
            options.append(
                (
                    scores[candidate_index][original_index] + tail_score,
                    (original_index,) + tail,
                )
            )
        return max(options, key=lambda item: item[0])

    _, assignment = best_assignment(0, 0)
    replacement_by_candidate: dict[int, str] = {}
    notes: list[str] = []
    for candidate_index, (candidate_block, original_index) in enumerate(
        zip(candidate_blocks, assignment)
    ):
        score = scores[candidate_index][original_index]
        replacement = original_blocks[original_index]
        replacement_by_candidate[candidate_index] = replacement
        if candidate_block != replacement:
            notes.append(
                f"fence[{candidate_index}]<-original[{original_index}] "
                f"similarity={score:.4f}"
            )

    repaired_blocks = [
        replacement_by_candidate[index] for index in range(len(candidate_blocks))
    ]
    return restore_fences(candidate_slots, repaired_blocks), notes


def _similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left.lower(), right.lower()).ratio()


def repair_inline(original: str, candidate: str, rule_id: str) -> tuple[str, list[str]]:
    original_prose, _ = split_fences(original)
    candidate_prose, candidate_fences = split_fences(candidate)
    notes: list[str] = []

    # Some LLM outputs converted Markdown inline spans to double-backtick spans.
    candidate_prose, normalized = re.subn(
        r"``([^`\n]+)``", r"`\1`", candidate_prose
    )
    if normalized:
        notes.append(f"normalized_double_backticks={normalized}")

    required = Counter(INLINE_RE.findall(original_prose))
    available = required.copy()
    candidate_spans = list(INLINE_RE.finditer(candidate_prose))
    replacements: list[tuple[int, int, str]] = []

    for match in candidate_spans:
        token = match.group(0)
        if available[token] > 0:
            available[token] -= 1
            continue

        unmatched = list(available.elements())
        best_token = None
        best_score = 0.0
        for wanted in unmatched:
            score = _similarity(token, wanted)
            if score > best_score:
                best_score = score
                best_token = wanted

        # Fuzzy restoration is restricted to substantial, clearly corresponding
        # spans. Short added formatting such as `postMessage` is unwrapped.
        if best_token is not None and min(len(token), len(best_token)) >= 24 and best_score >= 0.72:
            replacements.append((match.start(), match.end(), best_token))
            available[best_token] -= 1
            notes.append(f"restored_inline_similarity={best_score:.4f}")
        else:
            replacements.append((match.start(), match.end(), token[1:-1]))
            notes.append(f"unwrapped_added_inline={token}")

    for start, end, replacement in reversed(replacements):
        candidate_prose = candidate_prose[:start] + replacement + candidate_prose[end:]

    # Two observed LLM outputs deleted the protected token together with nearby
    # prose. Reinsert it into the corresponding mutated directive explicitly.
    missing = Counter(INLINE_RE.findall(original_prose)) - Counter(
        INLINE_RE.findall(candidate_prose)
    )
    password_token = '`<input type="password">`'
    cap_drop_token = "`--cap-drop all`"
    if missing[password_token]:
        pattern = re.compile(r"(?m)^(- Support for .*?paste.*)$")
        candidate_prose, count = pattern.subn(
            rf"\1 Include {password_token}.", candidate_prose, count=1
        )
        if count != 1:
            raise ValueError(f"could not reinsert {password_token} in {rule_id}")
        notes.append(f"reinserted_inline={password_token}")
    if missing[cap_drop_token]:
        pattern = re.compile(r"(?m)^(- Capabilities[^\n]*)$")

        def insert_cap_drop(match: re.Match[str]) -> str:
            line = match.group(1)
            return line.replace("Capabilities", f"Capabilities ({cap_drop_token})", 1)

        candidate_prose, count = pattern.subn(insert_cap_drop, candidate_prose, count=1)
        if count != 1:
            raise ValueError(f"could not reinsert {cap_drop_token} in {rule_id}")
        notes.append(f"reinserted_inline={cap_drop_token}")

    repaired = restore_fences(candidate_prose, candidate_fences)
    return repaired, notes


def sanitize_rule(original: str, candidate: str, rule_id: str) -> tuple[str, list[str]]:
    original_frontmatter = frontmatter(original)
    candidate_frontmatter = frontmatter(candidate)
    notes: list[str] = []
    if candidate_frontmatter != original_frontmatter:
        candidate = original_frontmatter + candidate[len(candidate_frontmatter):]
        notes.append("restored_frontmatter")

    candidate, fence_notes = repair_fences(original, candidate)
    notes.extend(fence_notes)
    candidate, inline_notes = repair_inline(original, candidate, rule_id)
    notes.extend(inline_notes)

    delta = signature_delta(original, candidate)
    if not is_valid(delta):
        raise ValueError(
            f"sanitization did not satisfy strict contract for {rule_id}: {delta}"
        )
    return candidate, notes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--original-rules", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--write", action="store_true", help="write sanitized candidates"
    )
    args = parser.parse_args()

    selected = json.loads(args.selection_manifest.read_text(encoding="utf-8"))["maps"]
    report: dict = {
        "artifact_type": "phase3_safe_zone_sanitization",
        "contract": (
            "exact frontmatter and exact fenced/inline-code multisets; protected "
            "positions may move only with pre-existing section/rule reordering"
        ),
        "selection_manifest": str(args.selection_manifest.resolve()),
        "original_rules": str(args.original_rules.resolve()),
        "candidates": [],
    }

    if args.write:
        args.output_root.mkdir(parents=True, exist_ok=True)

    for item in selected:
        raw_dir = Path(item["override_dir"])
        candidate_name = (
            f"{item['stratum']}_r{item['rank']}_s{item['seed']}_{item['cid']}"
        )
        output_dir = args.output_root / candidate_name
        files: list[dict] = []
        invalid = False

        for raw_path in sorted(raw_dir.glob("*.md")):
            rule_id = "codeguard-" + raw_path.stem[3:]
            original_path = args.original_rules / f"{rule_id}.md"
            original_text = original_path.read_text(encoding="utf-8")
            raw_text = raw_path.read_text(encoding="utf-8")
            before = signature_delta(original_text, raw_text)
            invalid = invalid or not is_valid(before)
            files.append(
                {
                    "rule_id": rule_id,
                    "raw_path": str(raw_path.resolve()),
                    "raw_sha256": sha256_bytes(raw_text.encode("utf-8")),
                    "pre_repair": before,
                }
            )

        if args.write and invalid:
            if output_dir.exists():
                shutil.rmtree(output_dir)
            output_dir.mkdir(parents=True)
            for file_record in files:
                raw_path = Path(file_record["raw_path"])
                rule_id = file_record["rule_id"]
                original_path = args.original_rules / f"{rule_id}.md"
                raw_text = raw_path.read_text(encoding="utf-8")
                if is_valid(file_record["pre_repair"]):
                    sanitized = raw_text
                    notes = ["unchanged_valid_rule"]
                else:
                    sanitized, notes = sanitize_rule(
                        original_path.read_text(encoding="utf-8"),
                        raw_text,
                        rule_id,
                    )
                destination = output_dir / raw_path.name
                destination.write_text(sanitized, encoding="utf-8")
                file_record["sanitized_path"] = str(destination.resolve())
                file_record["sanitized_sha256"] = sha256_bytes(
                    sanitized.encode("utf-8")
                )
                file_record["repair_notes"] = notes
                file_record["post_repair"] = signature_delta(
                    original_path.read_text(encoding="utf-8"), sanitized
                )

        record = {
            **item,
            "candidate_name": candidate_name,
            "raw_override_dir": str(raw_dir.resolve()),
            "raw_corpus_sha256": corpus_sha256(raw_dir),
            "strict_safe_zone_valid": not invalid,
            "sanitized_override_dir": (
                str(output_dir.resolve()) if args.write and invalid else None
            ),
            "sanitized_corpus_sha256": (
                corpus_sha256(output_dir) if args.write and invalid else None
            ),
            "files": files,
        }
        report["candidates"].append(record)
        print(
            f"{'INVALID' if invalid else 'valid':7s} {item['stratum']:13s} "
            f"r{item['rank']} {item['cid'][:8]}"
        )

    report["n_candidates"] = len(report["candidates"])
    report["n_invalid"] = sum(
        not record["strict_safe_zone_valid"] for record in report["candidates"]
    )
    if args.write:
        manifest_path = args.output_root / "manifest.json"
        manifest_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {manifest_path}")
    print(f"invalid candidates: {report['n_invalid']}/{report['n_candidates']}")


if __name__ == "__main__":
    main()
