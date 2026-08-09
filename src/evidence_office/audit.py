"""Detect source-file drift after a review package has been built."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .model import AuditReport, Issue, ProjectManifest, SourceSnapshot
from .source_index import index_manifest_sources
from .validator import validate_manifest


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _baseline_source(raw: Any) -> SourceSnapshot | None:
    if not isinstance(raw, Mapping):
        return None
    path = raw.get("path")
    kind = raw.get("kind")
    sha256 = raw.get("sha256")
    size_bytes = raw.get("size_bytes")
    anchors = raw.get("anchors", [])
    metadata = raw.get("metadata", {})
    if (
        not isinstance(path, str)
        or not path.strip()
        or not isinstance(kind, str)
        or not isinstance(sha256, str)
        or not _SHA256_RE.fullmatch(sha256)
        or isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
        or not isinstance(anchors, list)
        or not all(isinstance(anchor, str) for anchor in anchors)
        or not isinstance(metadata, Mapping)
    ):
        return None
    return SourceSnapshot(
        path=path.strip(),
        kind=kind,
        sha256=sha256,
        size_bytes=size_bytes,
        anchors=frozenset(anchors),
        metadata=dict(metadata),
    )


def _load_baseline(package_dir: Path) -> tuple[tuple[SourceSnapshot, ...], list[Issue]]:
    path = package_dir / "source-index.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return (), [Issue("error", "AUDIT_BASELINE_INVALID", f"Could not read source index: {exc}", path=str(path))]
    if not isinstance(raw, Mapping) or not isinstance(raw.get("sources"), list):
        return (), [Issue("error", "AUDIT_BASELINE_INVALID", "Source index must contain a sources array.", path=str(path))]

    snapshots: list[SourceSnapshot] = []
    issues: list[Issue] = []
    seen: set[str] = set()
    for index, item in enumerate(raw["sources"]):
        snapshot = _baseline_source(item)
        if snapshot is None:
            issues.append(Issue("error", "AUDIT_BASELINE_INVALID", f"Invalid source entry at index {index}.", path=str(path)))
            continue
        if snapshot.path in seen:
            issues.append(Issue("error", "AUDIT_BASELINE_INVALID", f"Duplicate source entry: {snapshot.path}", path=str(path)))
            continue
        seen.add(snapshot.path)
        snapshots.append(snapshot)
    return tuple(snapshots), issues


def _drift_issues(
    baseline: tuple[SourceSnapshot, ...],
    current: tuple[SourceSnapshot, ...],
) -> list[Issue]:
    baseline_by_path = {source.path: source for source in baseline}
    current_by_path = {source.path: source for source in current}
    issues: list[Issue] = []
    for path in sorted(baseline_by_path.keys() - current_by_path.keys()):
        issues.append(Issue("error", "SOURCE_MISSING_FROM_CURRENT", "Source recorded in the package is missing now.", path=path))
    for path in sorted(current_by_path.keys() - baseline_by_path.keys()):
        issues.append(Issue("error", "SOURCE_NOT_IN_BASELINE", "Current declared source was not present when the package was built.", path=path))
    for path in sorted(baseline_by_path.keys() & current_by_path.keys()):
        before = baseline_by_path[path]
        after = current_by_path[path]
        changes: list[str] = []
        if before.sha256 != after.sha256:
            changes.append("sha256")
        if before.size_bytes != after.size_bytes:
            changes.append("size_bytes")
        if before.kind != after.kind:
            changes.append("kind")
        if changes:
            issues.append(Issue(
                "error",
                "SOURCE_DRIFTED",
                f"Source changed since the package was built ({', '.join(changes)}).",
                path=path,
            ))
    return issues


def audit_package(manifest: ProjectManifest, root: Path, package_dir: Path) -> AuditReport:
    """Compare current declared sources with ``source-index.json`` in a build package."""

    root = root.resolve()
    package_dir = package_dir.resolve()
    validation = validate_manifest(manifest, root)
    current = validation.sources
    baseline, baseline_issues = _load_baseline(package_dir)
    issues = list(validation.issues)
    issues.extend(baseline_issues)
    if not baseline_issues:
        issues.extend(_drift_issues(baseline, current))
    status = "failed" if any(issue.severity == "error" for issue in issues) else (
        "passed_with_warnings" if any(issue.severity == "warning" for issue in issues) else "passed"
    )
    return AuditReport(
        project=manifest.project,
        status=status,
        issues=tuple(issues),
        current_sources=current,
        baseline_sources=baseline,
        claims=manifest.claims,
        claims_checked=len(manifest.claims),
    )
