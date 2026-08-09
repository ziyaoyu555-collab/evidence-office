"""Strict JSON and crash-safe local persistence boundaries."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


_MAX_JSON_BYTES = 64 * 1024 * 1024


def _object_without_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key!r}.")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is not permitted: {value}.")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _reject_nonfinite(value)
    return parsed


def _require_valid_unicode(value: Any) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            try:
                current.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("JSON strings and object keys must contain valid Unicode.") from exc
        elif isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def loads_json(text: str) -> Any:
    """Parse standards-compliant JSON without ambiguous duplicate keys."""

    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonfinite,
            parse_float=_finite_float,
        )
        _require_valid_unicode(value)
        return value
    except RecursionError as exc:
        raise ValueError("JSON is too deeply nested.") from exc


def read_json(path: Path) -> Any:
    with path.open("rb") as handle:
        content = handle.read(_MAX_JSON_BYTES + 1)
    if len(content) > _MAX_JSON_BYTES:
        raise ValueError(f"JSON document exceeds the {_MAX_JSON_BYTES}-byte read limit.")
    return loads_json(content.decode("utf-8"))


def json_text(value: Any) -> str:
    """Serialize portable JSON; never emit NaN or Infinity."""

    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _temporary_sibling(target: Path, role: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.{role}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    return Path(name)


def write_texts_atomic(directory: Path, contents: Mapping[str, str]) -> dict[str, Path]:
    """Stage and replace a set of sibling files, rolling back commit failures."""

    directory.mkdir(parents=True, exist_ok=True)
    names = tuple(contents)
    if any(not name or Path(name).name != name for name in names):
        raise ValueError("Atomic bundle entries must be plain file names.")
    targets = {name: directory / name for name in names}
    for target in targets.values():
        if target.exists() and not target.is_file():
            raise IsADirectoryError(f"Output path is not a regular file: {target}")

    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    committed: set[str] = set()
    try:
        for name in names:
            temporary = _temporary_sibling(targets[name], "stage")
            staged[name] = temporary
            temporary.write_text(contents[name], encoding="utf-8", newline="")

        for name in names:
            target = targets[name]
            if target.exists():
                backup = _temporary_sibling(target, "backup")
                target.replace(backup)
                backups[name] = backup
            staged[name].replace(target)
            committed.add(name)
    except BaseException as failure:
        rollback_errors: list[OSError] = []
        for name in reversed(names):
            target = targets[name]
            backup = backups.get(name)
            try:
                if name in committed and target.exists():
                    target.unlink()
                if backup is not None and backup.exists():
                    backup.replace(target)
            except OSError as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise OSError(
                f"Atomic write failed and rollback was incomplete: {rollback_errors[0]}"
            ) from failure
        raise
    finally:
        for temporary in (*staged.values(), *backups.values()):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return targets


def write_text_atomic(path: Path, content: str) -> Path:
    return write_texts_atomic(path.parent, {path.name: content})[path.name]
