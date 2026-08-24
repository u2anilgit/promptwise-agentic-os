from pathlib import Path

from core.index.models import CodeLocation
from core.index.parser import parse_file


def test_code_location_requires_all_fields():
    loc = CodeLocation(file="a.py", line=3, symbol="foo", kind="function")
    assert loc.file == "a.py"
    assert loc.line == 3
    assert loc.symbol == "foo"
    assert loc.kind == "function"


def test_parse_file_extracts_python_function_and_class(tmp_path):
    source = (
        "def foo(x):\n"
        "    return x\n"
        "\n"
        "class Bar:\n"
        "    def method_a(self):\n"
        "        pass\n"
    )
    py_file = tmp_path / "sample.py"
    py_file.write_text(source, encoding="utf-8")

    locations = parse_file(py_file)
    by_symbol = {loc.symbol: loc for loc in locations}

    assert by_symbol["foo"].kind == "function"
    assert by_symbol["foo"].line == 1  # 1-indexed, tree-sitter rows are 0-indexed
    assert by_symbol["Bar"].kind == "class"
    assert by_symbol["Bar"].line == 4
    assert by_symbol["method_a"].kind == "method"  # nested inside class Bar
    assert by_symbol["method_a"].line == 5
    assert str(py_file) == by_symbol["foo"].file


def test_parse_file_unknown_extension_returns_empty(tmp_path):
    unknown = tmp_path / "notes.txt"
    unknown.write_text("hello", encoding="utf-8")
    assert parse_file(unknown) == []


def test_parse_file_tolerates_a_syntax_error(tmp_path):
    # tree-sitter's error recovery should still find `foo` even though the
    # file overall doesn't parse cleanly.
    source = "def foo(x):\n    return x\n\ndef broken(:\n"
    py_file = tmp_path / "broken.py"
    py_file.write_text(source, encoding="utf-8")

    locations = parse_file(py_file)
    symbols = {loc.symbol for loc in locations}
    assert "foo" in symbols
