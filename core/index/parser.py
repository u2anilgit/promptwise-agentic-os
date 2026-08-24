# core/index/parser.py
"""tree-sitter-backed definition extraction — one Query per language,
run once per file. Error-tolerant by construction: tree-sitter itself
recovers from syntax errors and still yields ERROR nodes around the
broken region rather than failing the whole parse, so this module never
needs special-case exception handling for malformed source.
"""
from __future__ import annotations

from pathlib import Path

from tree_sitter import Parser, QueryCursor

from core.index.languages import LANGUAGES
from core.index.models import CodeLocation


def _is_inside_class(node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "class_definition":
            return True
        parent = parent.parent
    return False


def _name_for(def_node, name_nodes) -> str | None:
    # the query's name capture can pick up identifiers from nested/sibling
    # definitions too (e.g. a nested function's name) — narrow to the name
    # node that actually falls inside this def_node's own span. Uses >=,
    # not >: a method_definition node (TS/TSX/JS) starts at its own name
    # token directly (no keyword prefix like def/function/class precedes
    # it), so the name node's start_byte equals def_node's start_byte
    # exactly, not strictly after it — hand-verified against the real
    # grammar output before writing this, not guessed.
    match = next(
        (n for n in name_nodes if n.start_byte >= def_node.start_byte and n.end_byte <= def_node.end_byte),
        None,
    )
    return match.text.decode("utf-8") if match is not None else None


def parse_file(path: Path) -> list[CodeLocation]:
    spec = LANGUAGES.get(path.suffix)
    if spec is None:
        return []

    try:
        source = path.read_bytes()
    except OSError:
        # permission-denied, a broken symlink, or the file vanishing
        # between the walk's stat() and this read — a handled state, not
        # an exception; see the module docstring's error-tolerance note.
        return []
    parser = Parser(spec.language)
    tree = parser.parse(source)
    cursor = QueryCursor(spec.query)
    matches = cursor.matches(tree.root_node)

    locations: list[CodeLocation] = []
    for _pattern_index, captures in matches:
        for def_node in captures.get("func.def", []):
            name = _name_for(def_node, captures.get("func.name", []))
            if name is None:
                continue
            # Python has no distinct "method" node — a function_definition
            # nested inside a class body is a method; every other grammar
            # this module supports has a separate method_definition node
            # (below), so this ancestor check only ever fires for Python.
            kind = "method" if _is_inside_class(def_node) else "function"
            locations.append(
                CodeLocation(file=str(path), line=def_node.start_point[0] + 1, symbol=name, kind=kind)
            )
        for def_node in captures.get("class.def", []):
            name = _name_for(def_node, captures.get("class.name", []))
            if name is None:
                continue
            locations.append(
                CodeLocation(file=str(path), line=def_node.start_point[0] + 1, symbol=name, kind="class")
            )
        for def_node in captures.get("method.def", []):
            name = _name_for(def_node, captures.get("method.name", []))
            if name is None:
                continue
            locations.append(
                CodeLocation(file=str(path), line=def_node.start_point[0] + 1, symbol=name, kind="method")
            )

    return locations
