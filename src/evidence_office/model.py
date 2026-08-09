"""Public data model for evidence-office manifests and validation results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


VALID_STATUSES = frozenset({"verified", "unverified", "assumption"})


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    anchor: str | None = None
    note: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidenceRef":
        path = str(raw.get("path", "")).strip()
        anchor_raw = raw.get("anchor")
        note_raw = raw.get("note")
        return cls(
            path=path,
            anchor=(str(anchor_raw).strip() if anchor_raw is not None else None),
            note=(str(note_raw).strip() if note_raw is not None else None),
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
        sources_raw = raw.get("sources", [])
        if not isinstance(sources_raw, list):
            sources_raw = []
        note_raw = raw.get("note")
        return cls(
            id=str(raw.get("id", "")).strip(),
            statement=str(raw.get("statement", "")).strip(),
            status=str(raw.get("status", "")).strip().lower(),
            sources=tuple(EvidenceRef.from_mapping(item) for item in sources_raw if isinstance(item, Mapping)),
            note=(str(note_raw).strip() if note_raw is not None else None),
        )


@dataclass(frozen=True)
class SourceSpec:
    path: str
    label: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SourceSpec":
        label_raw = raw.get("label")
        return cls(
            path=str(raw.get("path", "")).strip(),
            label=(str(label_raw).strip() if label_raw is not None else None),
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
        sources_raw = raw.get("sources", [])
        claims_raw = raw.get("claims", [])
        if not isinstance(sources_raw, list):
            sources_raw = []
        if not isinstance(claims_raw, list):
            claims_raw = []
        return cls(
            project=str(raw.get("project", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            sources=tuple(SourceSpec.from_mapping(item) for item in sources_raw if isinstance(item, Mapping)),
            claims=tuple(Claim.from_mapping(item) for item in claims_raw if isinstance(item, Mapping)),
            manifest_path=manifest_path,
        )


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
    status: str
    issues: tuple[Issue, ...]
    sources: tuple[SourceSnapshot, ...]
    claims_checked: int

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

