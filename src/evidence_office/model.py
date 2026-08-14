"""Public data model for evidence-office manifests and validation results."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_STATUSES = frozenset({"verified", "unverified", "assumption"})
SCHEMA_VERSION = "0.9"


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
        # Manifest shape errors are user-data validation failures, not API misuse.
        raise ValueError(f"Manifest field '{field_name}' must be an array.")  # noqa: TRY004
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
    def from_mapping(cls, raw: Mapping[str, Any]) -> EvidenceRef:
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
    def from_mapping(cls, raw: Mapping[str, Any]) -> Claim:
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
    def from_mapping(cls, raw: Mapping[str, Any]) -> SourceSpec:
        _reject_unknown(raw, {"path", "label"}, "source")
        return cls(
            path=_path_text(raw.get("path")),
            label=_optional_text(raw.get("label")),
        )


_CHECK_SEVERITIES = frozenset({"error", "warning"})
_CONTENT_MODES = frozenset({"all", "any", "none"})


@dataclass(frozen=True)
class ContentCheck:
    """A configurable regex presence/absence gate over declared source text."""

    id: str
    sources: tuple[str, ...]
    patterns: tuple[str, ...]
    mode: str = "all"
    severity: str = "error"
    note: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ContentCheck:
        _reject_unknown(raw, {"id", "sources", "patterns", "mode", "severity", "note"}, "content check")
        sources_raw = raw.get("sources", [])
        patterns_raw = raw.get("patterns", [])
        if not isinstance(sources_raw, list) or not all(isinstance(value, str) for value in sources_raw):
            raise ValueError("Content check sources must be an array of strings.")
        if not isinstance(patterns_raw, list) or not all(isinstance(value, str) for value in patterns_raw):
            raise ValueError("Content check patterns must be an array of strings.")
        sources = tuple(_path_text(value) for value in sources_raw)
        patterns = tuple(_text(value) for value in patterns_raw if _text(value))
        mode = _text(raw.get("mode") or "all").lower()
        severity = _text(raw.get("severity") or "error").lower()
        if mode not in _CONTENT_MODES:
            raise ValueError(f"Content check mode must be one of {sorted(_CONTENT_MODES)}.")
        if severity not in _CHECK_SEVERITIES:
            raise ValueError(f"Content check severity must be one of {sorted(_CHECK_SEVERITIES)}.")
        return cls(_text(raw.get("id")), sources, patterns, mode, severity, _optional_text(raw.get("note")))


@dataclass(frozen=True)
class ValueProbe:
    path: str
    pattern: str
    group: int = 1
    label: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ValueProbe:
        _reject_unknown(raw, {"path", "pattern", "group", "label"}, "value probe")
        group = raw.get("group", 1)
        if not isinstance(group, int) or group < 1:
            raise ValueError("Value probe group must be a positive integer.")
        return cls(
            path=_path_text(raw.get("path")),
            pattern=_text(raw.get("pattern")),
            group=group,
            label=_optional_text(raw.get("label")),
        )


@dataclass(frozen=True)
class ConsistencyCheck:
    """Compare extracted values across artifacts and, optionally, an expected baseline."""

    id: str
    values: tuple[ValueProbe, ...]
    expected: int | float | str | None = None
    tolerance: float = 0.0
    severity: str = "error"
    note: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ConsistencyCheck:
        _reject_unknown(raw, {"id", "values", "expected", "tolerance", "severity", "note"}, "consistency check")
        values_raw = _mapping_items(raw.get("values"), "consistency check.values")
        tolerance = raw.get("tolerance", 0.0)
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
            raise ValueError("Consistency check tolerance must be a non-negative number.")
        severity = _text(raw.get("severity") or "error").lower()
        if severity not in _CHECK_SEVERITIES:
            raise ValueError(f"Consistency check severity must be one of {sorted(_CHECK_SEVERITIES)}.")
        expected = raw.get("expected")
        if expected is not None and (isinstance(expected, bool) or not isinstance(expected, (int, float, str))):
            raise ValueError("Consistency check expected must be a number, string, or null.")
        return cls(
            id=_text(raw.get("id")),
            values=tuple(ValueProbe.from_mapping(item) for item in values_raw),
            expected=expected,
            tolerance=float(tolerance),
            severity=severity,
            note=_optional_text(raw.get("note")),
        )


@dataclass(frozen=True)
class RuntimeCheck:
    """Declare a runtime boundary without pretending static parsing is execution."""

    id: str
    sources: tuple[str, ...]
    status: str
    severity: str = "warning"
    note: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RuntimeCheck:
        _reject_unknown(raw, {"id", "sources", "status", "severity", "note"}, "runtime check")
        sources_raw = raw.get("sources", [])
        if not isinstance(sources_raw, list) or not all(isinstance(value, str) for value in sources_raw):
            raise ValueError("Runtime check sources must be an array of strings.")
        status = _text(raw.get("status")).lower()
        severity = _text(raw.get("severity") or "warning").lower()
        if status not in {"verified", "unverified", "not_verified"}:
            raise ValueError("Runtime check status must be verified, unverified, or not_verified.")
        if severity not in _CHECK_SEVERITIES:
            raise ValueError(f"Runtime check severity must be one of {sorted(_CHECK_SEVERITIES)}.")
        return cls(
            id=_text(raw.get("id")),
            sources=tuple(_path_text(value) for value in sources_raw),
            status=status,
            severity=severity,
            note=_optional_text(raw.get("note")),
        )


@dataclass(frozen=True)
class SubmissionSpec:
    """Optional identity and structure checks for the actual submitted archive."""

    path: str
    sha256: str | None = None
    required_members: tuple[str, ...] = ()
    single_root: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SubmissionSpec:
        _reject_unknown(raw, {"path", "sha256", "required_members", "single_root"}, "submission")
        members = raw.get("required_members", [])
        if not isinstance(members, list) or not all(isinstance(value, str) for value in members):
            raise ValueError("Submission required_members must be an array of strings.")
        single_root = raw.get("single_root", False)
        if not isinstance(single_root, bool):
            raise ValueError("Submission single_root must be boolean.")
        return cls(
            path=_path_text(raw.get("path")),
            sha256=_optional_text(raw.get("sha256")),
            required_members=tuple(_path_text(value) for value in members),
            single_root=single_root,
        )


@dataclass(frozen=True)
class ReviewChecks:
    content: tuple[ContentCheck, ...] = ()
    consistency: tuple[ConsistencyCheck, ...] = ()
    runtime: tuple[RuntimeCheck, ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> ReviewChecks:
        if raw is None:
            return cls()
        _reject_unknown(raw, {"content", "consistency", "runtime"}, "checks")
        return cls(
            content=tuple(ContentCheck.from_mapping(item) for item in _mapping_items(raw.get("content"), "checks.content")),
            consistency=tuple(ConsistencyCheck.from_mapping(item) for item in _mapping_items(raw.get("consistency"), "checks.consistency")),
            runtime=tuple(RuntimeCheck.from_mapping(item) for item in _mapping_items(raw.get("runtime"), "checks.runtime")),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "id": item.id,
                    "sources": list(item.sources),
                    "patterns": list(item.patterns),
                    "mode": item.mode,
                    "severity": item.severity,
                    **({"note": item.note} if item.note else {}),
                }
                for item in self.content
            ],
            "consistency": [
                {
                    "id": item.id,
                    "values": [
                        {
                            "path": value.path,
                            "pattern": value.pattern,
                            "group": value.group,
                            **({"label": value.label} if value.label else {}),
                        }
                        for value in item.values
                    ],
                    **({"expected": item.expected} if item.expected is not None else {}),
                    "tolerance": item.tolerance,
                    "severity": item.severity,
                    **({"note": item.note} if item.note else {}),
                }
                for item in self.consistency
            ],
            "runtime": [
                {
                    "id": item.id,
                    "sources": list(item.sources),
                    "status": item.status,
                    "severity": item.severity,
                    **({"note": item.note} if item.note else {}),
                }
                for item in self.runtime
            ],
        }


@dataclass(frozen=True)
class ProjectManifest:
    project: str
    description: str
    sources: tuple[SourceSpec, ...]
    claims: tuple[Claim, ...]
    checks: ReviewChecks = field(default_factory=ReviewChecks)
    submission: SubmissionSpec | None = None
    manifest_path: Path | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], manifest_path: Path | None = None) -> ProjectManifest:
        _reject_unknown(raw, {"project", "description", "sources", "claims", "checks", "submission"}, "manifest")
        sources_raw = _mapping_items(raw.get("sources"), "sources")
        claims_raw = _mapping_items(raw.get("claims"), "claims")
        return cls(
            project=_text(raw.get("project")),
            description=_text(raw.get("description")),
            sources=tuple(SourceSpec.from_mapping(item) for item in sources_raw),
            claims=tuple(Claim.from_mapping(item) for item in claims_raw),
            checks=ReviewChecks.from_mapping(raw.get("checks")),
            submission=SubmissionSpec.from_mapping(raw["submission"]) if raw.get("submission") is not None else None,
            manifest_path=manifest_path,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical, portable manifest representation."""

        mapping: dict[str, object] = {
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
        if self.checks != ReviewChecks():
            mapping["checks"] = self.checks.to_mapping()
        if self.submission is not None:
            mapping["submission"] = {
                "path": self.submission.path,
                **({"sha256": self.submission.sha256} if self.submission.sha256 else {}),
                **({"required_members": list(self.submission.required_members)} if self.submission.required_members else {}),
                **({"single_root": True} if self.submission.single_root else {}),
            }
        return mapping


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
