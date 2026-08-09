"""Project lifecycle helpers for the usable init → intake → build workflow."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .model import VALID_STATUSES, ProjectManifest
from .storage import json_text, write_text_atomic
from .validator import load_manifest, validate_manifest

_WORKFLOW_README = """# Evidence Office review workflow

1. Put source material under `sources/` or another path below this workspace.
2. Register it with `evidence-office intake manifest.json <path> ...`.
3. Add claims to `manifest.json`; every `verified` claim needs a precise source anchor.
4. Run `evidence-office validate manifest.json` while editing.
5. Run `evidence-office build manifest.json --out dist/` to create the review packet.
6. Run `evidence-office audit manifest.json --package dist/` before handing off a package.
7. Use `--strict` in CI when warnings must block delivery.

The generated packet is deterministic except for its report timestamp. It is a
validation aid, not a substitute for engineering or scientific review.
"""


def _relative_source(root: Path, raw_path: str) -> str:
    root = root.resolve()
    candidate = Path(raw_path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Source is outside the workspace root: {raw_path}") from exc


def _write_manifest(path: Path, data: dict[str, object]) -> None:
    write_text_atomic(path, json_text(data))


def create_workspace(out_dir: Path, project: str, description: str = "") -> Path:
    """Create a new project workspace without overwriting an existing one."""

    manifest = ProjectManifest.from_mapping({
        "project": project,
        "description": description,
        "sources": [],
        "claims": [],
    })
    if not manifest.project:
        raise ValueError("Project name must not be empty")
    out_dir = out_dir.resolve()
    if out_dir.exists() and not out_dir.is_dir():
        raise FileExistsError(f"Workspace path is not a directory: {out_dir}")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"Workspace is not empty; refusing to overwrite: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sources").mkdir(exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    _write_manifest(manifest_path, manifest.to_mapping())
    (out_dir / "WORKFLOW.md").write_text(_WORKFLOW_README, encoding="utf-8")
    return manifest_path


def intake_sources(manifest_path: Path, root: Path, source_paths: Iterable[str]) -> int:
    """Register existing source files, validating all paths before writing."""

    manifest_path = manifest_path.resolve()
    root = root.resolve()
    manifest = load_manifest(manifest_path)
    existing = {source.path for source in manifest.sources}
    normalized: list[str] = []
    for raw_path in source_paths:
        relative = _relative_source(root, raw_path)
        if not relative or relative in normalized:
            continue
        source_file = (root / relative).resolve()
        if not source_file.is_file():
            raise FileNotFoundError(f"Source does not exist: {relative}")
        normalized.append(relative)

    additions = [path for path in normalized if path not in existing]
    if not additions:
        return 0
    data = manifest.to_mapping()
    sources = list(data["sources"])
    sources.extend({"path": path} for path in additions)
    data["sources"] = sources
    candidate = ProjectManifest.from_mapping(data, manifest_path=manifest_path)
    _write_manifest(manifest_path, candidate.to_mapping())
    return len(additions)


def add_claim(
    manifest_path: Path,
    root: Path,
    *,
    claim_id: str,
    statement: str,
    status: str,
    source_path: str | None = None,
    anchor: str | None = None,
    note: str | None = None,
) -> None:
    """Add one claim through the workflow, refusing invalid evidence before writing."""

    manifest_path = manifest_path.resolve()
    root = root.resolve()
    manifest = load_manifest(manifest_path)
    claim_id = claim_id.strip()
    statement = statement.strip()
    status = status.strip().lower()
    if not claim_id:
        raise ValueError("Claim id must not be empty")
    if not statement:
        raise ValueError("Claim statement must not be empty")
    if status not in VALID_STATUSES:
        raise ValueError(f"Claim status must be one of {sorted(VALID_STATUSES)}")
    if any(claim.id == claim_id for claim in manifest.claims):
        raise ValueError(f"Claim id already exists: {claim_id}")
    if anchor and not source_path:
        raise ValueError("An evidence anchor requires --source")
    if status == "verified" and (not source_path or not anchor):
        raise ValueError("A verified claim requires both --source and --anchor")
    if status == "verified" and anchor and (anchor == "file" or anchor.startswith("file:")):
        raise ValueError("A verified claim requires a precise anchor, not a file-level anchor")

    data = manifest.to_mapping()
    sources = list(data["sources"])
    references: list[dict[str, str]] = []
    evidence_path: str | None = None
    if source_path:
        relative = _relative_source(root, source_path)
        evidence_path = relative
        source_file = (root / relative).resolve()
        if not source_file.is_file():
            raise FileNotFoundError(f"Source does not exist: {relative}")
        if relative not in {str(item["path"]) for item in sources}:
            sources.append({"path": relative})
        references.append({"path": relative, **({"anchor": anchor} if anchor else {})})
    data["sources"] = sources
    claims = list(data["claims"])
    claims.append({
        "id": claim_id,
        "statement": statement,
        "status": status,
        **({"note": note.strip()} if note and note.strip() else {}),
        "sources": references,
    })
    data["claims"] = claims
    candidate = ProjectManifest.from_mapping(data, manifest_path=manifest_path)
    report = validate_manifest(candidate, root)
    claim_errors = [
        issue for issue in report.errors
        if issue.claim_id == claim_id or (evidence_path is not None and issue.path == evidence_path)
    ]
    if claim_errors:
        raise ValueError("; ".join(issue.message for issue in claim_errors))
    _write_manifest(manifest_path, candidate.to_mapping())
