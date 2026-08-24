# core/memory/extract.py
"""Fact/decision extraction via a local model. route_request only picks
WHICH model to use (tier -> model_id); the actual generation call is
plain HTTP against Ollama's /api/generate, same handled-state-not-
exception convention as embed.py. An unreachable Ollama or a response
that isn't valid {"facts": [...]} JSON both fall back to treating the
whole input as one unclassified fact — never raises.
"""
from __future__ import annotations

import json
from typing import Any

from core.memory.embed import HttpPost, default_http_post
from core.routing.router import RouteRequest, route_request

_EXTRACTION_PROMPT = """Extract distinct facts, decisions, or stated \
preferences from the text below as JSON: {{"facts": [{{"text": "...", \
"category": "preference|decision|context"}}]}}. One idea per fact, \
concise. Respond with ONLY the JSON object, no other text.

Text:
{text}
"""


def extract_facts(text: str, config: dict[str, Any], http_post: HttpPost = default_http_post) -> list[dict[str, str]]:
    if not text.strip():
        return []

    memory_config = config.get("memory", {})
    base_url = memory_config.get("ollama_base_url", "http://127.0.0.1:11434")
    tier_hint = memory_config.get("extraction_tier_hint", "local-small")

    decision = route_request(RouteRequest(task_type="fact_extraction", preferred_tier=tier_hint), config=config)

    try:
        body = http_post(
            f"{base_url}/api/generate",
            {"model": decision.model_id, "prompt": _EXTRACTION_PROMPT.format(text=text), "format": "json", "stream": False},
        )
        parsed = json.loads(body["response"])
        facts = parsed["facts"]
        if not isinstance(facts, list):
            raise ValueError("facts is not a list")
        return [{"text": str(f["text"]), "category": str(f["category"])} for f in facts]
    except Exception:
        # covers: OSError/URLError (unreachable), KeyError/TypeError (missing
        # keys), json.JSONDecodeError (invalid JSON), ValueError (wrong shape)
        # — any of these is "the model didn't cooperate", a handled state.
        return [{"text": text.strip(), "category": "unclassified"}]
