"""Validation rules: strict about broken evidence, explicit about uncertainty."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    VALID_STATUSES,
    Claim,
    Issue,
    ProjectManifest,
    ValidationReport,
)
from .source_index import index_manifest_sources


def load_manifest(path: Path) -> ProjectManifest:
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except RecursionError as exc:
        raise ValueError("Manifest JSON is too deeply nested.") from exc
    if not isinstance(raw, dict):
        raise ValueError("Manifest root must be a JSON object")
    return ProjectManifest.from_mapping(raw, manifest_path=path)


def _path_is_safe(root: Path, relative_path: str) -> bool:
    try:
        (root / relative_path).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _add_claim_issue(issues: list[Issue], severity: str, code: str, message: str, claim: Claim, **kwargs: Any) -> None:
    issues.append(Issue(severity, code, message, claim_id=claim.id or None, **kwargs))


def _is_generic_anchor(anchor: str) -> bool:
    return anchor == "file" or anchor.startswith("file:")


def validate_manifest(manifest: ProjectManifest, root: Path) -> ValidationReport:
    root = root.resolve()
    issues: list[Issue] = []
    declared = {spec.path for spec in manifest.sources if spec.path}
    snapshots = index_manifest_sources(root, manifest)
    by_path = {snapshot.path: snapshot for snapshot in snapshots}

    if not manifest.project:
        issues.append(Issue("error", "PROJECT_NAME_MISSING", "Manifest project name must not be empty."))
    if not manifest.sources:
        issues.append(Issue("error", "SOURCES_MISSING", "Manifest must declare at least one source file."))
    if not manifest.claims:
        issues.append(Issue("warning", "CLAIMS_EMPTY", "Manifest declares no claims; there is nothing to verify."))

    seen_sources: set[str] = set()
    for spec in manifest.sources:
        if not spec.path:
            issues.append(Issue("error", "SOURCE_PATH_MISSING", "Every source must have a non-empty path."))
            continue
        if spec.path in seen_sources:
            issues.append(Issue("error", "SOURCE_DUPLICATE", f"Source is declared more than once: {spec.path}", path=spec.path))
        seen_sources.add(spec.path)
        if "\x00" in spec.path:
            issues.append(Issue("error", "SOURCE_PATH_INVALID", "Source path contains an invalid NUL character.", path=spec.path))
        elif not _path_is_safe(root, spec.path):
            issues.append(Issue("error", "SOURCE_OUTSIDE_ROOT", f"Source escapes the selected root: {spec.path}", path=spec.path))
        elif spec.path not in by_path:
            try:
                source_exists = (root / spec.path).is_file()
            except OSError:
                source_exists = True
            code = "SOURCE_READ_UNAVAILABLE" if source_exists else "SOURCE_MISSING"
            message = (
                f"Declared source could not be read safely: {spec.path}"
                if source_exists else f"Declared source does not exist: {spec.path}"
            )
            issues.append(Issue("error", code, message, path=spec.path))
        elif by_path[spec.path].metadata.get("parse") == "unavailable":
            issues.append(Issue("error", "SOURCE_PARSE_UNAVAILABLE", f"Source could not be indexed safely: {spec.path}", path=spec.path))

    seen_claims: set[str] = set()
    for claim in manifest.claims:
        if not claim.id:
            _add_claim_issue(issues, "error", "CLAIM_ID_MISSING", "Every claim must have an id.", claim)
        elif claim.id in seen_claims:
            _add_claim_issue(issues, "error", "CLAIM_ID_DUPLICATE", f"Claim id is duplicated: {claim.id}", claim)
        seen_claims.add(claim.id)
        if not claim.statement:
            _add_claim_issue(issues, "error", "CLAIM_STATEMENT_MISSING", "Claim statement must not be empty.", claim)
        if claim.status not in VALID_STATUSES:
            _add_claim_issue(issues, "error", "CLAIM_STATUS_INVALID", f"Claim status must be one of {sorted(VALID_STATUSES)}.", claim)
        if claim.status == "verified" and not claim.sources:
            _add_claim_issue(issues, "error", "VERIFIED_CLAIM_UNSOURCED", "A verified claim must cite at least one source.", claim)
        if claim.status == "unverified":
            _add_claim_issue(issues, "warning", "CLAIM_UNVERIFIED", "Claim is explicitly marked unverified and must not be presented as fact.", claim)
        if claim.status == "assumption":
            _add_claim_issue(issues, "warning", "CLAIM_ASSUMPTION", "Claim is an assumption; downstream users must review it before relying on it.", claim)

        for ref in claim.sources:
            if not ref.path:
                _add_claim_issue(issues, "error", "EVIDENCE_PATH_MISSING", "Evidence reference must name a source path.", claim)
                continue
            if ref.path not in declared:
                _add_claim_issue(issues, "error", "EVIDENCE_SOURCE_UNDECLARED", f"Evidence points to an undeclared source: {ref.path}", claim, path=ref.path, anchor=ref.anchor)
                continue
            snapshot = by_path.get(ref.path)
            if snapshot is None:
                continue
            if snapshot.metadata.get("parse") == "unavailable":
                continue
            if claim.status == "verified" and not ref.anchor:
                _add_claim_issue(issues, "error", "VERIFIED_EVIDENCE_ANCHOR_MISSING", "A verified evidence reference must include a precise anchor.", claim, path=ref.path)
            elif claim.status == "verified" and ref.anchor and _is_generic_anchor(ref.anchor):
                _add_claim_issue(issues, "error", "VERIFIED_EVIDENCE_ANCHOR_NOT_PRECISE", "A verified claim cannot rely only on a file-level anchor; cite a paragraph, row, cell, slide, or line.", claim, path=ref.path, anchor=ref.anchor)
            elif ref.anchor and ref.anchor not in snapshot.anchors:
                _add_claim_issue(issues, "error", "EVIDENCE_ANCHOR_NOT_FOUND", f"Evidence anchor was not found in {ref.path}: {ref.anchor}", claim, path=ref.path, anchor=ref.anchor)

    return ValidationReport(manifest.project, tuple(issues), snapshots, manifest.claims)
