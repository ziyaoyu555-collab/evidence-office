"""Public data model for evidence-office manifests and validation results."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


VALID_STATUSES = frozenset({"verified", "unverified", "assumption"})
SCHEMA_VERSION = "0.7"


def anchor_sort_key(anchor: str) -> tuple[tuple[int, int | str], ...]:
    """Sort numbered anchors for people: line:2 before line:10."""

    return tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in re.split(r"(\d+)", anchor)
    )


def _text(value: Any) -> str:
    """Return trimmed manifest text without coercing nulls or objects."""

    if not isinstance(value, str):
        return ""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Manifest text must contain valid Unicode.") from exc
    return value.strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _path_text(value: Any) -> str:
    text = _text(value).replace("\\", "/")
    return posixpath.normpath(text) if text else ""


def _mapping_items(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    """Require JSON-object entries instead of silently discarding bad shapes."""

    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"Manifest field '{field_name}' must be an array.")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"Every entry in manifest field '{field_name}' must be an object.")
    return tuple(value)


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(str(key) for key in raw.keys() - allowed)
    if unknown:
        noun = "field" if len(unknown) == 1 else "fields"
        raise ValueError(f"Unknown {context} {noun}: {', '.join(unknown)}.")


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    anchor: str | None = None
    note: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidenceRef":
        _reject_unknown(raw, {"path", "anchor", "note"}, "evidence reference")
        return cls(
            path=_path_text(raw.get("path")),
            anchor=_optional_text(raw.get("anchor")),
            note=_optional_text(raw.get("note")),
        )


@dataclass(frozen=True)
class Claim:
    id: str
    statement: str
    status: str
    sources: tuple[EvidenceRef, ...] = ()
    note: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Claim":
        _reject_unknown(raw, {"id", "statement", "status", "sources", "note"}, "claim")
        sources_raw = _mapping_items(raw.get("sources"), "claim.sources")
        return cls(
            id=_text(raw.get("id")),
            statement=_text(raw.get("statement")),
            status=_text(raw.get("status")).lower(),
            sources=tuple(EvidenceRef.from_mapping(item) for item in sources_raw),
            note=_optional_text(raw.get("note")),
        )


@dataclass(frozen=True)
class SourceSpec:
    path: str
    label: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SourceSpec":
        _reject_unknown(raw, {"path", "label"}, "source")
        return cls(
            path=_path_text(raw.get("path")),
            label=_optional_text(raw.get("label")),
        )


@dataclass(frozen=True)
class ProjectManifest:
    project: str
    description: str
    sources: tuple[SourceSpec, ...]
    claims: tuple[Claim, ...]
    manifest_path: Path | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], manifest_path: Path | None = None) -> "ProjectManifest":
        _reject_unknown(raw, {"project", "description", "sources", "claims"}, "manifest")
        sources_raw = _mapping_items(raw.get("sources"), "sources")
        claims_raw = _mapping_items(raw.get("claims"), "claims")
        return cls(
            project=_text(raw.get("project")),
            description=_text(raw.get("description")),
            sources=tuple(SourceSpec.from_mapping(item) for item in sources_raw),
            claims=tuple(Claim.from_mapping(item) for item in claims_raw),
            manifest_path=manifest_path,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical, portable manifest representation."""

        return {
            "project": self.project,
            "description": self.description,
            "sources": [
                {"path": source.path, **({"label": source.label} if source.label else {})}
                for source in self.sources
            ],
            "claims": [
                {
                    "id": claim.id,
                    "statement": claim.statement,
                    "status": claim.status,
                    **({"note": claim.note} if claim.note else {}),
                    "sources": [
                        {
                            "path": ref.path,
                            **({"anchor": ref.anchor} if ref.anchor else {}),
                            **({"note": ref.note} if ref.note else {}),
                        }
                        for ref in claim.sources
                    ],
                }
                for claim in self.claims
            ],
        }


@dataclass(frozen=True)
class SourceSnapshot:
    path: str
    kind: str
    sha256: str
    size_bytes: int
    anchors: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    claim_id: str | None = None
    path: str | None = None
    anchor: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    project: str
    issues: tuple[Issue, ...]
    sources: tuple[SourceSnapshot, ...]
    claims: tuple[Claim, ...]

    @property
    def status(self) -> str:
        if self.errors:
            return "failed"
        if self.warnings:
            return "passed_with_warnings"
        return "passed"

    @property
    def claims_checked(self) -> int:
        return len(self.claims)

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def exit_code(self, strict: bool = False) -> int:
        return 1 if self.errors or (strict and self.warnings) else 0


@dataclass(frozen=True)
class AuditReport(ValidationReport):
    """Result of comparing current sources with a previously built package."""

    baseline_sources: tuple[SourceSnapshot, ...]

    @property
    def current_sources(self) -> tuple[SourceSnapshot, ...]:
        """Keep the audit-specific name without duplicating stored state."""

        return self.sources
