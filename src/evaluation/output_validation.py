"""Select and validate the target-language program in a model response."""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass, field
from functools import lru_cache


LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python",
    "python": "python",
    "python3": "python",
    "js": "javascript",
    "javascript": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "java": "java",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "c++": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "cs": "csharp",
    "csharp": "csharp",
    "c#": "csharp",
    "sh": "bash",
    "shell": "bash",
    "bash": "bash",
    "html": "html",
    "css": "css",
    "sql": "sql",
    "php": "php",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "ruby": "ruby",
    "kotlin": "kotlin",
    "scala": "scala",
}

SUPPORTED_ANALYSIS_LANGUAGES = frozenset({"python", "java"})

_FENCE_OPEN_RE = re.compile(r"^\s*```\s*(?P<tag>[A-Za-z0-9_+#.\-]*)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")
_ABNORMAL_FINISH_REASONS = frozenset(
    {
        "length",
        "max_tokens",
        "max_output_tokens",
        "content_filter",
        "refusal",
        "tool_calls",
        "function_call",
        "error",
        "cancelled",
        "canceled",
        "timeout",
    }
)


def normalize_language(language: str | None) -> str | None:
    if language is None:
        return None
    value = language.strip().lower()
    return LANGUAGE_ALIASES.get(value, value or None)


def _compile_python_ast(code: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return compile(code, "<generated>", "exec", ast.PyCF_ONLY_AST)


@dataclass(frozen=True)
class FencedBlock:
    language: str | None
    code: str


@dataclass(frozen=True)
class ParsedOutput:
    blocks: tuple[FencedBlock, ...]
    outside_text: str
    has_fences: bool
    unterminated_fence: bool


@dataclass
class CodeValidation:
    """The selected target-language artifact and its qualification state."""

    code: str
    source_code: str
    expected_language: str
    detected_language: str | None
    finish_reason: str
    status: str = "valid"
    failure_reason: str | None = None
    syntax_error: str | None = None
    syntax_validation_method: str | None = None
    fence_languages: list[str | None] = field(default_factory=list)
    ignored_supplementary_languages: list[str] = field(default_factory=list)
    has_fences: bool = False
    outside_text_present: bool = False
    target_block_count: int = 0
    normalization: str = "none"
    analysis_line_map: list[int | None] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"


class BaselineOutputError(RuntimeError):
    """Raised when the origin cannot define a trustworthy per-task score."""


def parse_fenced_output(raw_output: str) -> ParsedOutput:
    """Parse complete Markdown fences without joining independent artifacts."""
    blocks: list[FencedBlock] = []
    outside: list[str] = []
    current: list[str] | None = None
    current_language: str | None = None
    has_fences = False

    for line in raw_output.splitlines():
        if current is None:
            match = _FENCE_OPEN_RE.match(line)
            if match:
                has_fences = True
                current = []
                current_language = normalize_language(match.group("tag"))
            else:
                outside.append(line)
        elif _FENCE_CLOSE_RE.match(line):
            blocks.append(FencedBlock(current_language, "\n".join(current).strip()))
            current = None
            current_language = None
        else:
            current.append(line)

    unterminated = current is not None
    if unterminated:
        blocks.append(FencedBlock(current_language, "\n".join(current or []).strip()))

    return ParsedOutput(
        blocks=tuple(blocks),
        outside_text="\n".join(outside).strip(),
        has_fences=has_fences,
        unterminated_fence=unterminated,
    )


def _looks_like_language(code: str) -> str | None:
    """Cheap deterministic drift detector; never used to change the stratum."""
    if not code.strip():
        return None
    signatures: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "java",
            (
                r"\bpublic\s+(?:final\s+)?class\s+\w+",
                r"^\s*(?:package|import)\s+[A-Za-z_]\w*(?:\.[A-Za-z_*]\w*)*\s*;",
                r"System\.out\.",
                r"public\s+static\s+void\s+main",
                r"Runtime\.getRuntime\(\)",
            ),
        ),
        (
            "javascript",
            (
                r"\b(?:const|let|var)\s+\w+\s*=",
                r"\brequire\s*\(",
                r"\bfunction\s+\w+\s*\(",
                r"=>",
                r"\bconsole\.log\s*\(",
            ),
        ),
        ("c", (r"^\s*#include\s*[<\"]", r"\bint\s+main\s*\(")),
        ("bash", (r"^\s*#!.*\b(?:ba)?sh\b",)),
        ("sql", (r"^\s*(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|TABLE)\b",)),
    )
    matches = [
        language
        for language, patterns in signatures
        if any(re.search(pattern, code, re.M | re.I) for pattern in patterns)
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return None
    try:
        tree = _compile_python_ast(code)
        if getattr(tree, "body", None):
            return "python"
    except (SyntaxError, ValueError, TypeError):
        pass
    return None


def _invalid(
    validation: CodeValidation,
    status: str,
    reason: str,
    *,
    syntax_error: str | None = None,
) -> CodeValidation:
    validation.status = status
    validation.failure_reason = reason
    validation.syntax_error = syntax_error
    return validation


def _python_node_is_substantive(node: ast.AST) -> bool:
    if isinstance(node, ast.Module):
        return any(_python_node_is_substantive(child) for child in node.body)
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
        return False
    if isinstance(node, ast.Expr) and isinstance(
        node.value, (ast.Constant, ast.Name, ast.Attribute)
    ):
        return False
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return any(_python_node_is_substantive(child) for child in node.body)
    return True


@lru_cache(maxsize=1)
def _java_parser():
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_java
    except ImportError as exc:  # pragma: no cover - required dependency
        raise RuntimeError("Java syntax validator is unavailable") from exc
    return Parser(Language(tree_sitter_java.language()))


def _java_parse_candidates(
    code: str,
) -> tuple[tuple[str, str, list[int | None]], ...]:
    """Build deterministic scanner inputs for Java units, members, and snippets."""
    prefix: list[str] = []
    body: list[str] = []
    prefix_line_numbers: list[int] = []
    body_line_numbers: list[int] = []
    in_leading_block_comment = False
    for line_number, line in enumerate(code.splitlines(), start=1):
        stripped = line.lstrip()
        is_prefix_line = (
            not body
            and (
                not stripped
                or stripped.startswith(("package ", "import ", "//"))
                or stripped.startswith("/*")
                or in_leading_block_comment
            )
        )
        if is_prefix_line:
            prefix.append(line)
            prefix_line_numbers.append(line_number)
            if stripped.startswith("/*") and "*/" not in stripped:
                in_leading_block_comment = True
            if in_leading_block_comment and "*/" in stripped:
                in_leading_block_comment = False
        else:
            body.append(line)
            body_line_numbers.append(line_number)

    source_lines = code.splitlines()
    compilation_unit = ("none", code, list(range(1, len(source_lines) + 1)))

    class_lines = [*prefix, "class __SemgrepGenerated__ {", *body, "}"]
    class_line_map: list[int | None] = [
        *prefix_line_numbers,
        None,
        *body_line_numbers,
        None,
    ]
    method_lines = [
        *prefix,
        "class __SemgrepGenerated__ {",
        "void __semgrepSnippet__() {",
        *body,
        "}",
        "}",
    ]
    method_line_map: list[int | None] = [
        *prefix_line_numbers,
        None,
        None,
        *body_line_numbers,
        None,
        None,
    ]
    return (
        compilation_unit,
        ("java_class_wrapper", "\n".join(class_lines), class_line_map),
        ("java_method_wrapper", "\n".join(method_lines), method_line_map),
    )


def _parse_java(code: str):
    """Return the first complete Java parse and its exact scanner representation."""
    parser = _java_parser()
    candidates = _java_parse_candidates(code)
    allowed_compilation_unit_children = {
        "package_declaration",
        "import_declaration",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
        "module_declaration",
        "line_comment",
        "block_comment",
    }
    first_root = None
    for normalization, candidate_code, line_map in candidates:
        root = parser.parse(candidate_code.encode("utf-8")).root_node
        if first_root is None:
            first_root = root
        raw_is_compilation_unit = normalization != "none" or all(
            child.type in allowed_compilation_unit_children
            for child in root.named_children
        )
        if not root.has_error and raw_is_compilation_unit:
            return root, None, candidate_code, normalization, line_map
    assert first_root is not None
    root = first_root
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            row, column = node.start_point
            return (
                None,
                f"tree-sitter error at line {row + 1}, column {column + 1}",
                code,
                "none",
                list(range(1, len(code.splitlines()) + 1)),
            )
        stack.extend(reversed(node.children))
    return (
        None,
        "tree-sitter reported an unspecified parse error",
        code,
        "none",
        list(range(1, len(code.splitlines()) + 1)),
    )


_JAVA_SUBSTANTIVE_NODES = frozenset(
    {
        "assignment_expression",
        "method_invocation",
        "object_creation_expression",
        "if_statement",
        "for_statement",
        "enhanced_for_statement",
        "while_statement",
        "do_statement",
        "switch_expression",
        "switch_statement",
        "throw_statement",
        "try_statement",
        "synchronized_statement",
        "assert_statement",
        "update_expression",
        "lambda_expression",
    }
)


def _java_tree_is_substantive(root) -> bool:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in _JAVA_SUBSTANTIVE_NODES:
            return True
        if node.type == "return_statement" and any(child.is_named for child in node.children):
            return True
        if node.type == "variable_declarator" and node.child_by_field_name("value") is not None:
            return True
        stack.extend(reversed(node.children))
    return False


def validate_generated_output(
    raw_output: str,
    *,
    expected_language: str,
    finish_reason: str | None,
) -> CodeValidation:
    """Select the primary artifact and qualify it for Python/Java Semgrep."""
    expected = normalize_language(expected_language)
    if expected not in SUPPORTED_ANALYSIS_LANGUAGES:
        raise ValueError(f"unsupported analysis language: {expected!r}")

    finish = (finish_reason or "unknown").strip().lower()
    parsed = parse_fenced_output(raw_output)
    blocks = list(parsed.blocks)
    target_block_indices = [
        idx
        for idx, block in enumerate(blocks)
        if block.code.strip() and block.language in {None, expected}
    ]
    if len(target_block_indices) == 1:
        primary_index = target_block_indices[0]
    else:
        primary_index = target_block_indices[0] if target_block_indices else 0
    primary_code = blocks[primary_index].code if blocks else raw_output.strip()
    tagged_language = blocks[primary_index].language if blocks else None
    detected = tagged_language or _looks_like_language(primary_code)
    validation = CodeValidation(
        code=primary_code,
        source_code=primary_code,
        expected_language=expected,
        detected_language=detected,
        finish_reason=finish,
        fence_languages=[block.language for block in blocks],
        has_fences=parsed.has_fences,
        outside_text_present=bool(parsed.outside_text),
        target_block_count=(
            len(target_block_indices) if blocks else int(bool(primary_code.strip()))
        ),
        analysis_line_map=list(range(1, len(primary_code.splitlines()) + 1)),
    )

    if finish in _ABNORMAL_FINISH_REASONS:
        return _invalid(
            validation,
            "generation_incomplete",
            f"generation ended with finish_reason={finish}",
        )
    if not raw_output.strip() or not primary_code.strip():
        return _invalid(validation, "empty_output", "generation contained no code")
    if parsed.unterminated_fence:
        return _invalid(validation, "malformed_output", "unterminated Markdown code fence")
    if tagged_language is not None and tagged_language != expected:
        return _invalid(
            validation,
            "language_drift",
            f"primary code block is {tagged_language}, expected {expected}",
        )
    if tagged_language is None and detected is not None and detected != expected:
        return _invalid(
            validation,
            "language_drift",
            f"generated code appears to be {detected}, expected {expected}",
        )

    if len(target_block_indices) > 1:
        return _invalid(
            validation,
            "multiple_target_blocks",
            "generation contains more than one target-language code artifact",
        )
    validation.ignored_supplementary_languages = [
        block.language
        for idx, block in enumerate(blocks)
        if idx != primary_index
        if block.code.strip() and block.language not in {None, expected}
    ]

    if expected == "python":
        validation.syntax_validation_method = "python_ast"
        try:
            tree = _compile_python_ast(primary_code)
        except (SyntaxError, ValueError, TypeError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            return _invalid(
                validation,
                "syntax_invalid",
                "Python AST parsing failed",
                syntax_error=detail,
            )
        if not _python_node_is_substantive(tree):
            return _invalid(
                validation,
                "vacuous_output",
                "Python AST contains no substantive implementation",
            )
    else:
        validation.syntax_validation_method = "java_tree_sitter"
        root, syntax_error, analyzed_code, normalization, line_map = _parse_java(primary_code)
        if syntax_error is not None:
            return _invalid(
                validation,
                "syntax_invalid",
                "Java tree-sitter parsing failed",
                syntax_error=syntax_error,
            )
        validation.code = analyzed_code
        validation.normalization = normalization
        validation.analysis_line_map = line_map
        if not _java_tree_is_substantive(root):
            return _invalid(
                validation,
                "vacuous_output",
                "Java syntax tree contains no substantive implementation",
            )

    return validation
