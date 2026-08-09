"""Detect source-file drift after a review package has been built."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .model import AuditReport, Issue, ProjectManifest, SCHEMA_VERSION, SourceSnapshot, SourceSpec
from .validator import validate_manifest


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_SOURCE_INDEX_SCHEMAS = frozenset({"0.3", SCHEMA_VERSION})


def _baseline_error(path: Path, message: str) -> Issue:
    return Issue("error", "AUDIT_BASELINE_INVALID", message, path=str(path))


def _read_json(path: Path) -> tuple[Any | None, list[Issue]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        return None, [_baseline_error(path, f"Could not read baseline: {exc}")]


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
    try:
        normalized_path = SourceSpec.from_mapping({"path": path}).path
    except ValueError:
        return None
    return SourceSnapshot(
        path=normalized_path,
        kind=kind,
        sha256=sha256,
        size_bytes=size_bytes,
        anchors=frozenset(anchors),
        metadata=dict(metadata),
    )


def _load_baseline(package_dir: Path) -> tuple[tuple[SourceSnapshot, ...], list[Issue]]:
    path = package_dir / "source-index.json"
    raw, read_issues = _read_json(path)
    if read_issues:
        return (), read_issues
    if not isinstance(raw, Mapping) or not isinstance(raw.get("sources"), list):
        return (), [_baseline_error(path, "Source index must contain a sources array.")]
    if raw.get("schema_version") not in _SUPPORTED_SOURCE_INDEX_SCHEMAS:
        return (), [_baseline_error(path, f"Unsupported source-index schema: {raw.get('schema_version')!r}.")]

    snapshots: list[SourceSnapshot] = []
    issues: list[Issue] = []
    seen: set[str] = set()
    for index, item in enumerate(raw["sources"]):
        snapshot = _baseline_source(item)
        if snapshot is None:
            issues.append(_baseline_error(path, f"Invalid source entry at index {index}."))
            continue
        if snapshot.path in seen:
            issues.append(_baseline_error(path, f"Duplicate source entry: {snapshot.path}"))
            continue
        seen.add(snapshot.path)
        snapshots.append(snapshot)
    return tuple(snapshots), issues


def _load_manifest_baseline(package_dir: Path) -> tuple[dict[str, object] | None, list[Issue]]:
    path = package_dir / "manifest.snapshot.json"
    raw, read_issues = _read_json(path)
    if read_issues:
        return None, read_issues
    if not isinstance(raw, Mapping):
        return None, [_baseline_error(path, "Manifest snapshot must be a JSON object.")]
    try:
        return ProjectManifest.from_mapping(raw).to_mapping(), []
    except ValueError as exc:
        return None, [_baseline_error(path, f"Invalid manifest snapshot: {exc}")]


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
    baseline, source_baseline_issues = _load_baseline(package_dir)
    manifest_baseline, manifest_baseline_issues = _load_manifest_baseline(package_dir)
    issues = list(validation.issues)
    issues.extend(source_baseline_issues)
    issues.extend(manifest_baseline_issues)
    if not source_baseline_issues:
        issues.extend(_drift_issues(baseline, validation.sources))
    if not manifest_baseline_issues and manifest_baseline != manifest.to_mapping():
        issues.append(Issue(
            "error",
            "MANIFEST_DRIFTED",
            "Manifest content changed since the package was built.",
            path=str(manifest.manifest_path) if manifest.manifest_path else None,
        ))
    return AuditReport(
        project=manifest.project,
        issues=tuple(issues),
        sources=validation.sources,
        claims=manifest.claims,
        baseline_sources=baseline,
    )
