# core/verify/output.py
"""Shared head+tail output truncation for verify tool runners (Fix 5 —
unbounded subprocess output must never be returned verbatim, since the MCP
path dumps it straight into an agent's context). Keeps the first and last
slice of the output so both the start of an error and its final summary
line survive, with a marker in between naming how much was omitted.
"""
from __future__ import annotations


def truncate_output(output: str, max_output_chars: int = 4000) -> str:
    if len(output) <= max_output_chars:
        return output

    half = max_output_chars // 2
    head = output[:half]
    tail = output[-half:]
    omitted = len(output) - len(head) - len(tail)
    return f"{head}\n...[truncated, {omitted} chars omitted]...\n{tail}"
