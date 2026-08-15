"""Configurable cross-artifact checks for real delivery packages.

The checks in this module deliberately operate on declared manifest rules.  The
engine knows how to compare artifacts, but it does not know that one particular
course, vehicle, or CAD project has a particular correct number.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from .model import (
    Issue,
    ProjectManifest,
    ResolvedArtifact,
    SourceSnapshot,
    ValueProbe,
)

_MAX_RULE_TEXT_BYTES = 64 * 1024 * 1024
_TEXT_SUFFIXES = frozenset({".c", ".cpp", ".csv", ".ipynb", ".java", ".js", ".json", ".m", ".md", ".py", ".r", ".txt", ".xml"})
_OFFICE_SUFFIXES = frozenset({".docm", ".docx", ".pptm", ".pptx", ".xlsm", ".xlsx"})
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_ARCHIVE_ENTRIES = 10_000


def _safe_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_RULE_TEXT_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _office_text(path: Path) -> str | None:
    """Extract visible XML text without requiring python-docx/openpyxl."""

    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            members = [info for info in archive.infolist() if info.filename.endswith(".xml")]
            if sum(info.file_size for info in members) > _MAX_RULE_TEXT_BYTES:
                return None
            for info in members:
                raw = archive.read(info)
                if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
                    return None
                root = ElementTree.fromstring(raw)
                text = " ".join(part.strip() for part in root.itertext() if part and part.strip())
                if text:
                    chunks.append(text)
    except (OSError, ValueError, ElementTree.ParseError, zipfile.BadZipFile):
        return None
    return "\n".join(chunks)


def read_rule_text(root: Path, relative_path: str) -> str | None:
    """Read searchable text for a declared source, or return None for binary-only files."""

    try:
        path = (root / relative_path).resolve()
        path.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if not path.is_file():
        return None
    if path.suffix.lower() in _OFFICE_SUFFIXES:
        return _office_text(path)
    if path.suffix.lower() in _TEXT_SUFFIXES or path.suffix.lower() == ".yaml":
        return _safe_text(path)
    return None


def _severity(rule_severity: str, default: str = "error") -> str:
    return rule_severity if rule_severity in {"error", "warning"} else default


def _issue(
    rule_id: str,
    severity: str,
    code: str,
    message: str,
    path: str | None = None,
    anchor: str | None = None,
) -> Issue:
    return Issue(severity, code, f"[{rule_id}] {message}", path=path, anchor=anchor)


def _content_checks(manifest: ProjectManifest, root: Path) -> list[Issue]:
    issues: list[Issue] = []
    declared = {source.path for source in manifest.sources}
    for rule in manifest.checks.content:
        if not rule.id:
            issues.append(_issue("(unnamed)", "error", "CHECK_ID_MISSING", "Content check id must not be empty."))
            continue
        if not rule.patterns:
            issues.append(_issue(rule.id, "error", "CHECK_PATTERNS_EMPTY", "Content check must declare at least one regex pattern."))
            continue
        sources = rule.sources or tuple(sorted(declared))
        missing = sorted(set(sources) - declared)
        for path in missing:
            issues.append(_issue(rule.id, "error", "CHECK_SOURCE_UNDECLARED", f"Check references an undeclared source: {path}", path))
        texts: list[tuple[str, str]] = []
        for path in sources:
            if path not in declared:
                continue
            text = read_rule_text(root, path)
            if text is None:
                issues.append(_issue(rule.id, "error", "CHECK_SOURCE_UNREADABLE", f"Source cannot be searched as text: {path}", path))
            else:
                texts.append((path, text))
        if missing or not texts:
            continue
        found: list[tuple[str, str]] = []
        invalid = False
        for pattern in rule.patterns:
            try:
                expression = re.compile(pattern)
            except re.error as exc:
                issues.append(_issue(rule.id, "error", "CHECK_PATTERN_INVALID", f"Invalid regex {pattern!r}: {exc}"))
                invalid = True
                continue
            for path, text in texts:
                if expression.search(text):
                    found.append((path, pattern))
        if invalid:
            continue
        severity = _severity(rule.severity)
        if rule.mode == "none" and found:
            path, pattern = found[0]
            issues.append(_issue(rule.id, severity, "CONTENT_FORBIDDEN_MATCH", f"Forbidden content matched regex {pattern!r}.", path))
        elif rule.mode == "all":
            missing_patterns = [pattern for pattern in rule.patterns if not any(found_pattern == pattern for _, found_pattern in found)]
            if missing_patterns:
                issues.append(_issue(rule.id, severity, "CONTENT_REQUIRED_MISSING", f"Required content was not found: {missing_patterns!r}."))
        elif rule.mode == "any" and not found:
            issues.append(_issue(rule.id, severity, "CONTENT_ANY_MISSING", "None of the configured content patterns was found."))
    return issues


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not _NUMBER_RE.fullmatch(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _probe_value(root: Path, probe: ValueProbe) -> tuple[str | None, str | None]:
    text = read_rule_text(root, probe.path)
    if text is None:
        return None, "source cannot be searched as text"
    try:
        matches = list(re.finditer(probe.pattern, text))
    except re.error as exc:
        return None, f"invalid regex {probe.pattern!r}: {exc}"
    if len(matches) != 1:
        return None, f"expected exactly one regex match, found {len(matches)}"
    match = matches[0]
    try:
        return match.group(probe.group).strip(), None
    except (IndexError, AttributeError):
        return None, f"regex has no capture group {probe.group}"


def _consistency_checks(manifest: ProjectManifest, root: Path) -> list[Issue]:
    issues: list[Issue] = []
    declared = {source.path for source in manifest.sources}
    for rule in manifest.checks.consistency:
        if not rule.id:
            issues.append(_issue("(unnamed)", "error", "CHECK_ID_MISSING", "Consistency check id must not be empty."))
            continue
        if len(rule.values) < 1:
            issues.append(_issue(rule.id, "error", "CONSISTENCY_PROBES_EMPTY", "Consistency check must declare at least one value probe."))
            continue
        if rule.expected is None and len(rule.values) < 2:
            issues.append(_issue(rule.id, "error", "CONSISTENCY_EXPECTED_MISSING", "A single value probe requires an expected baseline."))
            continue
        severity = _severity(rule.severity)
        extracted: list[tuple[ValueProbe, str]] = []
        for probe in rule.values:
            if probe.path not in declared:
                issues.append(_issue(rule.id, "error", "CHECK_SOURCE_UNDECLARED", f"Check references an undeclared source: {probe.path}", probe.path))
                continue
            if not probe.pattern:
                issues.append(_issue(rule.id, "error", "CONSISTENCY_PATTERN_EMPTY", "Value probe regex must not be empty.", probe.path))
                continue
            value, error = _probe_value(root, probe)
            if error:
                issues.append(_issue(rule.id, severity, "CONSISTENCY_VALUE_UNAVAILABLE", f"{error}.", probe.path))
            elif value is not None:
                extracted.append((probe, value))
        if len(extracted) != len(rule.values):
            continue
        expected_decimal = _as_decimal(rule.expected)
        if rule.expected is not None and expected_decimal is None and not isinstance(rule.expected, str):
            issues.append(_issue(rule.id, "error", "CONSISTENCY_EXPECTED_INVALID", "Expected baseline is not numeric or text."))
            continue
        reference = expected_decimal if rule.expected is not None else _as_decimal(extracted[0][1])
        if reference is None:
            expected_text = str(rule.expected).strip() if rule.expected is not None else extracted[0][1]
            mismatches = [(probe, value) for probe, value in extracted if value.strip() != expected_text]
        else:
            mismatches = [
                (probe, value)
                for probe, value in extracted
                if (candidate := _as_decimal(value)) is None or abs(candidate - reference) > Decimal(str(rule.tolerance))
            ]
        if mismatches:
            locations = ", ".join(f"{probe.path}={value!r}" for probe, value in mismatches)
            expected = rule.expected if rule.expected is not None else extracted[0][1]
            issues.append(_issue(rule.id, severity, "CONSISTENCY_MISMATCH", f"Expected {expected!r}; mismatching values: {locations}."))
    return issues


def _runtime_checks(manifest: ProjectManifest) -> list[Issue]:
    issues: list[Issue] = []
    declared = {source.path for source in manifest.sources}
    for rule in manifest.checks.runtime:
        missing = sorted(set(rule.sources) - declared)
        for path in missing:
            issues.append(_issue(rule.id or "(unnamed)", "error", "CHECK_SOURCE_UNDECLARED", f"Runtime check references an undeclared source: {path}", path))
        if missing:
            continue
        if rule.status != "verified":
            severity = _severity(rule.severity, "warning")
            detail = rule.note or "The configured runtime has not been verified; static indexing is not execution."
            issues.append(_issue(rule.id or "(unnamed)", severity, "RUNTIME_NOT_VERIFIED", detail))
    return issues


def run_review_checks(manifest: ProjectManifest, root: Path) -> tuple[Issue, ...]:
    """Run all optional v0.9 checks and return ordinary report issues."""

    return tuple(_content_checks(manifest, root) + _consistency_checks(manifest, root) + _runtime_checks(manifest))


def _member_sha256(archive: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    with archive.open(member) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_submission(
    manifest: ProjectManifest,
    root: Path,
    snapshots: tuple[SourceSnapshot, ...],
) -> tuple[tuple[Issue, ...], tuple[ResolvedArtifact, ...]]:
    """Validate a submitted ZIP and resolve validated sources to final members.

    The archive is the delivery boundary.  A consistency check over unpacked
    workspace sources is not enough if the final ZIP contains a stale copy, so
    every configured final artifact is located and compared byte-for-byte with
    the source that was actually checked.
    """

    submission = manifest.submission
    if submission is None:
        return (), ()
    snapshot = next((item for item in snapshots if item.path == submission.path), None)
    if snapshot is None:
        return (
            (_issue("submission", "error", "SUBMISSION_SOURCE_MISSING", f"Submission archive is not a declared readable source: {submission.path}", submission.path),),
            (),
        )
    issues: list[Issue] = []
    resolved_artifacts: list[ResolvedArtifact] = []
    if submission.sha256 and not _SHA256_RE.fullmatch(submission.sha256):
        issues.append(_issue("submission", "error", "SUBMISSION_SHA256_INVALID", "Configured SHA-256 must contain exactly 64 hexadecimal characters.", submission.path))
    elif submission.sha256 and snapshot.sha256.lower() != submission.sha256.lower():
        issues.append(_issue("submission", "error", "SUBMISSION_SHA256_MISMATCH", f"Expected {submission.sha256}; found {snapshot.sha256}.", submission.path))
    path = (root / submission.path).resolve()
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) > _MAX_ARCHIVE_ENTRIES:
                issues.append(_issue("submission", "error", "SUBMISSION_TOO_MANY_MEMBERS", f"Archive contains more than {_MAX_ARCHIVE_ENTRIES} members.", submission.path))
            if len(names) != len(set(names)):
                issues.append(_issue("submission", "error", "SUBMISSION_DUPLICATE_MEMBER", "Archive contains duplicate member names.", submission.path))
            unsafe = [name for name in names if name.startswith("/") or name == ".." or name.startswith("../") or "/../" in name]
            if unsafe:
                issues.append(_issue("submission", "error", "SUBMISSION_UNSAFE_MEMBER", f"Archive contains path-traversal members: {unsafe[:3]!r}.", submission.path))
            if archive.testzip() is not None:
                issues.append(_issue("submission", "error", "SUBMISSION_CORRUPT", "Archive failed CRC integrity testing.", submission.path))
            name_set = set(names)
            for member in submission.required_members:
                if member not in name_set:
                    issues.append(_issue("submission", "error", "SUBMISSION_MEMBER_MISSING", f"Required archive member is missing: {member}.", submission.path))
            if submission.single_root:
                roots = {name.split("/", 1)[0] for name in names if name and not name.startswith("/")}
                if len(roots) != 1:
                    issues.append(_issue("submission", "error", "SUBMISSION_ROOT_AMBIGUOUS", f"Expected one archive root directory; found {sorted(roots)!r}.", submission.path))

            declared = {source.path for source in manifest.sources}
            snapshots_by_path = {item.path: item for item in snapshots}
            seen_artifact_ids: set[str] = set()
            for artifact in submission.artifacts:
                if not artifact.id:
                    issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_ID_MISSING", "Final artifact id must not be empty.", submission.path))
                    continue
                if artifact.id in seen_artifact_ids:
                    issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_ID_DUPLICATE", f"Final artifact id is duplicated: {artifact.id}.", submission.path))
                    continue
                seen_artifact_ids.add(artifact.id)
                if artifact.source not in declared:
                    issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_SOURCE_UNDECLARED", f"Final artifact source is not declared: {artifact.source}.", artifact.source))
                    continue
                if artifact.source == submission.path:
                    issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_SOURCE_IS_ARCHIVE", "A final artifact source cannot be the submission archive itself.", artifact.source))
                    continue
                if not artifact.member_pattern:
                    issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_PATTERN_EMPTY", f"Final artifact pattern is empty: {artifact.id}.", submission.path))
                    continue
                try:
                    expression = re.compile(artifact.member_pattern)
                except re.error as exc:
                    issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_PATTERN_INVALID", f"Invalid final artifact pattern for {artifact.id}: {exc}.", submission.path))
                    continue
                matches = [name for name in names if name and not name.endswith("/") and expression.search(name)]
                severity = "error" if artifact.required else "warning"
                if not matches:
                    if artifact.required:
                        issues.append(_issue("submission", severity, "SUBMISSION_ARTIFACT_MISSING", f"Final artifact was not found in the archive: {artifact.id} ({artifact.member_pattern!r}).", submission.path))
                    continue
                if artifact.unique and len(matches) != 1:
                    issues.append(_issue("submission", severity, "SUBMISSION_ARTIFACT_AMBIGUOUS", f"Final artifact must resolve to exactly one archive member; found {matches!r}: {artifact.id}.", submission.path))
                    continue
                source_snapshot = snapshots_by_path.get(artifact.source)
                if source_snapshot is None:
                    issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_SOURCE_UNAVAILABLE", f"Validated source snapshot is unavailable: {artifact.source}.", artifact.source))
                    continue
                for member in matches:
                    try:
                        archive_sha256 = _member_sha256(archive, member)
                    except (OSError, KeyError, RuntimeError, ValueError) as exc:
                        issues.append(_issue("submission", "error", "SUBMISSION_ARTIFACT_UNREADABLE", f"Final artifact member could not be read: {member}: {exc}.", submission.path, anchor=member))
                        continue
                    if archive_sha256 != source_snapshot.sha256:
                        issues.append(_issue(
                            "submission",
                            "error",
                            "SUBMISSION_ARTIFACT_DRIFTED",
                            f"Final artifact {artifact.id} does not match the validated source {artifact.source}: archive={archive_sha256}, source={source_snapshot.sha256}.",
                            submission.path,
                            anchor=member,
                        ))
                    else:
                        resolved_artifacts.append(ResolvedArtifact(
                            id=artifact.id,
                            source=artifact.source,
                            member=member,
                            source_sha256=source_snapshot.sha256,
                            archive_sha256=archive_sha256,
                        ))
    except (OSError, zipfile.BadZipFile) as exc:
        issues.append(_issue("submission", "error", "SUBMISSION_NOT_ZIP", f"Submission archive is not a readable ZIP: {exc}.", submission.path))
    return tuple(issues), tuple(resolved_artifacts)


def validate_submission(manifest: ProjectManifest, root: Path, snapshots: tuple[SourceSnapshot, ...]) -> tuple[Issue, ...]:
    """Backward-compatible submission validation entry point."""

    issues, _resolved_artifacts = inspect_submission(manifest, root, snapshots)
    return issues
