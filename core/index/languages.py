# core/index/languages.py
from dataclasses import dataclass

import tree_sitter_python as tspython
from tree_sitter import Language, Query


@dataclass(frozen=True)
class LanguageSpec:
    language: Language
    query: Query


_PY_LANG = Language(tspython.language())
_PY_QUERY = Query(
    _PY_LANG,
    """
    (function_definition name: (identifier) @func.name) @func.def
    (class_definition name: (identifier) @class.name) @class.def
    """,
)

LANGUAGES: dict[str, LanguageSpec] = {
    ".py": LanguageSpec(_PY_LANG, _PY_QUERY),
}
