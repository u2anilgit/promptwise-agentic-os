# core/actions/fs.py
"""fs_write — the one governed filesystem action this phase ships.
docs/ARCHITECTURE.md §2's Action layer: policy-gated, audited, and
undo-buffered, in that order, on every call. This is the enforcement
point core/policy/engine.py's check_policy never had on its own —
check_policy only evaluates and returns a verdict; fs_write is what
actually honors it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.actions.models import FsWriteResult, UndoEntry
from core.audit.log import record_audit
from core.config.resolve import resolve_path
from core.policy.engine import check_policy


def _undo_buffer_path(config: dict[str, Any]) -> Path:
    return resolve_path(config, "actions.undo_buffer_path", ".promptwise/undo_buffer.json")


def _load_undo_buffer(config: dict[str, Any]) -> list[UndoEntry]:
    path = _undo_buffer_path(config)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return [UndoEntry(**item) for item in raw]
    except (json.JSONDecodeError, ValueError):
        return []


def _save_undo_buffer(config: dict[str, Any], buffer: list[UndoEntry]) -> None:
    path = _undo_buffer_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    max_size = config.get("actions", {}).get("undo_buffer_max", 50)
    # buffer[-max_size:] with max_size == 0 slices as [0:] (the whole
    # list) since Python has no distinct "negative zero" — trim to empty
    # explicitly instead of relying on the negative-index shortcut.
    trimmed = buffer[-max_size:] if max_size > 0 else []
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump([entry.model_dump() for entry in trimmed], f, indent=2)
    tmp_path.replace(path)


def fs_write(config: dict[str, Any], path: Path, content: str) -> FsWriteResult:
    path = Path(path)
    # The full path, not just the filename — a policy must be able to
    # distinguish workspace/hello.txt from secrets/hello.txt. as_posix()
    # keeps rule authoring portable across OSes (no backslash-escaping
    # needed in policy YAML).
    scope = f"fs.write.{path.as_posix()}"
    decision = check_policy(scope, config=config)

    if not decision.allowed:
        record_audit(config, actor="fs_write", action=scope, target=str(path), result="deny", detail={"reason": decision.reason})
        return FsWriteResult(path=str(path), allowed=False, written=False, reason=decision.reason)

    previous_content = path.read_text(encoding="utf-8") if path.exists() else None
    buffer = _load_undo_buffer(config)
    buffer.append(
        UndoEntry(path=str(path), previous_content=previous_content, timestamp=datetime.now(timezone.utc).isoformat())
    )
    _save_undo_buffer(config, buffer)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    record_audit(config, actor="fs_write", action=scope, target=str(path), result="allow")
    return FsWriteResult(path=str(path), allowed=True, written=True, reason=decision.reason)


def undo_last(config: dict[str, Any]) -> UndoEntry | None:
    buffer = _load_undo_buffer(config)
    if not buffer:
        return None

    entry = buffer.pop()
    _save_undo_buffer(config, buffer)

    target = Path(entry.path)
    if entry.previous_content is None:
        if target.exists():
            target.unlink()
    else:
        target.write_text(entry.previous_content, encoding="utf-8")

    return entry
