from __future__ import annotations

import pytest

from src.evaluation.output_validation import validate_generated_output


def _validate(output: str, *, expected: str = "python", finish: str = "stop"):
    return validate_generated_output(
        output,
        expected_language=expected,
        finish_reason=finish,
    )


def test_primary_python_block_is_scanned_and_other_language_block_is_recorded() -> None:
    result = _validate(
        "```python\nfrom flask import Flask\napp = Flask(__name__)\n```\n"
        "```html\n<h1>Hello</h1>\n```"
    )
    assert result.is_valid
    assert result.code.startswith("from flask")
    assert "<h1>" not in result.code
    assert result.fence_languages == ["python", "html"]
    assert result.ignored_supplementary_languages == ["html"]


def test_single_target_block_is_selected_even_when_supplementary_block_comes_first() -> None:
    result = _validate(
        "```html\n<h1>Hello</h1>\n```\n"
        "```python\nprint('safe')\n```"
    )

    assert result.is_valid
    assert result.source_code == "print('safe')"
    assert result.ignored_supplementary_languages == ["html"]


@pytest.mark.parametrize(
    ("output", "status"),
    [
        ("```javascript\nconst x = 1;\n```", "language_drift"),
        ("```python\ndef broken(\n```", "syntax_invalid"),
        ("```python\nprint('x')", "malformed_output"),
        (
            "```python\nprint('a')\n```\n```python\nprint('b')\n```",
            "multiple_target_blocks",
        ),
        ("# comments only", "vacuous_output"),
        ("import os\npass", "vacuous_output"),
        ("def todo():\n    pass", "vacuous_output"),
        ("", "empty_output"),
    ],
)
def test_invalid_output_classes(output: str, status: str) -> None:
    result = _validate(output)
    assert not result.is_valid
    assert result.status == status


@pytest.mark.parametrize("finish", ["length", "max_tokens", "content_filter", "timeout"])
def test_abnormal_finish_reason_takes_precedence(finish: str) -> None:
    result = _validate("print('complete looking')", finish=finish)
    assert result.status == "generation_incomplete"


def test_unfenced_python_is_valid() -> None:
    result = _validate("def f(x):\n    return x + 1")
    assert result.is_valid
    assert result.detected_language == "python"


def test_fence_language_may_be_separated_by_whitespace() -> None:
    result = _validate("``` python\ndef f(x):\n    return x + 1\n```")
    assert result.is_valid
    assert result.code.startswith("def f")


def test_explanatory_text_around_a_valid_fenced_artifact_is_observational() -> None:
    result = _validate("Here is the code:\n```python\nprint('x')\n```\nDone.")
    assert result.is_valid
    assert result.code == "print('x')"
    assert result.outside_text_present


@pytest.mark.parametrize(
    ("code", "normalization"),
    [
        (
            "public class Demo { public static void main(String[] args) { System.out.println(1); } }",
            "none",
        ),
        ("public String value() { return \"ok\"; }", "java_class_wrapper"),
        ("System.out.println(\"ok\");", "java_method_wrapper"),
    ],
)
def test_java_tree_sitter_accepts_units_members_and_snippets(
    code: str,
    normalization: str,
) -> None:
    result = _validate(code, expected="java")
    assert result.is_valid
    assert result.syntax_validation_method == "java_tree_sitter"
    assert result.normalization == normalization
    assert result.source_code == code
    if normalization == "none":
        assert result.code == code
        assert result.analysis_line_map == [1]
    else:
        assert "class __SemgrepGenerated__" in result.code
        assert len(result.analysis_line_map) == len(result.code.splitlines())


def test_java_wrapper_keeps_imports_and_maps_body_lines_to_the_source() -> None:
    result = _validate(
        "import java.io.IOException;\n"
        "public String value() throws IOException {\n"
        "    return \"ok\";\n"
        "}",
        expected="java",
    )

    assert result.is_valid
    assert result.normalization == "java_class_wrapper"
    assert result.code.splitlines()[0] == "import java.io.IOException;"
    assert result.analysis_line_map == [1, None, 2, 3, 4, None]


def test_java_wrapper_accepts_blank_and_comment_lines_between_imports() -> None:
    result = _validate(
        "import java.io.IOException;\n"
        "\n"
        "// helper import\n"
        "import java.util.List;\n"
        "public String value() throws IOException {\n"
        "    return List.of(\"ok\").get(0);\n"
        "}",
        expected="java",
    )

    assert result.is_valid
    assert result.normalization == "java_class_wrapper"
    assert result.code.splitlines()[3] == "import java.util.List;"
    assert result.analysis_line_map[:5] == [1, 2, 3, 4, None]


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("public void broken(", "syntax_invalid"),
        ("public class Empty {}", "vacuous_output"),
        ("import java.util.List;", "vacuous_output"),
    ],
)
def test_java_rejects_malformed_or_vacuous_code(code: str, status: str) -> None:
    result = _validate(code, expected="java")
    assert result.status == status


def test_map_language_is_authoritative_for_unfenced_drift() -> None:
    result = _validate("const value = userInput => eval(userInput)")
    assert result.status == "language_drift"
    assert result.expected_language == "python"
    assert result.detected_language == "javascript"


def test_multiple_target_blocks_are_counted_but_never_combined() -> None:
    output = "```python\nprint('first')\n```\n```python\nprint('second')\n```"
    result = _validate(output)

    assert result.status == "multiple_target_blocks"
    assert result.target_block_count == 2
    assert result.source_code == "print('first')"
    assert result.code == result.source_code


def test_unsupported_study_language_fails_configuration() -> None:
    with pytest.raises(ValueError, match="unsupported analysis language"):
        _validate("int main() { return 0; }", expected="c")
