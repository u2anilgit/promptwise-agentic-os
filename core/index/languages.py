# core/index/languages.py
from dataclasses import dataclass

import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
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

_TS_LANG = Language(tstypescript.language_typescript())
_TS_QUERY = Query(
    _TS_LANG,
    """
    (function_declaration name: (identifier) @func.name) @func.def
    (class_declaration name: (type_identifier) @class.name) @class.def
    (method_definition name: (property_identifier) @method.name) @method.def
    """,
)

_TSX_LANG = Language(tstypescript.language_tsx())
_TSX_QUERY = Query(
    _TSX_LANG,
    """
    (function_declaration name: (identifier) @func.name) @func.def
    (class_declaration name: (type_identifier) @class.name) @class.def
    (method_definition name: (property_identifier) @method.name) @method.def
    """,
)

_JS_LANG = Language(tsjavascript.language())
_JS_QUERY = Query(
    _JS_LANG,
    """
    (function_declaration name: (identifier) @func.name) @func.def
    (class_declaration name: (identifier) @class.name) @class.def
    (method_definition name: (property_identifier) @method.name) @method.def
    """,
)

LANGUAGES: dict[str, LanguageSpec] = {
    ".py": LanguageSpec(_PY_LANG, _PY_QUERY),
    ".ts": LanguageSpec(_TS_LANG, _TS_QUERY),
    ".tsx": LanguageSpec(_TSX_LANG, _TSX_QUERY),
    ".js": LanguageSpec(_JS_LANG, _JS_QUERY),
}
