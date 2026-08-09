"""Command-line interface for the public evidence-office workflow."""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .audit import audit_package
from .demo import create_demo
from .model import ProjectManifest, ValidationReport, anchor_sort_key
from .report import (
    PACKAGE_FILES,
    render_html,
    render_json,
    render_text,
    safe_line,
    write_package,
)
from .source_index import index_file
from .storage import json_text, write_text_atomic
from .validator import load_manifest, validate_manifest
from .workflow import add_claim, create_workspace, intake_sources


def _root_for(manifest_path: Path, explicit: Path | None) -> Path:
    return (explicit or manifest_path.parent).resolve()


def _manifest_inputs(manifest_path: Path, manifest: ProjectManifest, root: Path) -> list[Path]:
    inputs = [manifest_path]
    for source in manifest.sources:
        if source.path:
            with contextlib.suppress(OSError, ValueError):
                inputs.append((root / source.path).resolve())
    return inputs


def _protect_outputs(outputs: list[Path], inputs: list[Path]) -> None:
    protected = {path.resolve() for path in inputs}
    for output in outputs:
        resolved = output.resolve()
        if resolved in protected:
            raise ValueError(f"Output matches a protected input; refusing to overwrite input: {resolved}")


def _write_or_print(content: str, out: Path | None) -> None:
    if out:
        print(write_text_atomic(out.resolve(), content))
    else:
        print(content, end="")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return number


_REPORT_RENDERERS: dict[str, Callable[[ValidationReport], str]] = {
    "text": render_text,
    "json": render_json,
    "html": render_html,
}


def _emit_report(report: ValidationReport, format_name: str, out: Path | None, strict: bool) -> int:
    _write_or_print(_REPORT_RENDERERS[format_name](report), out)
    return report.exit_code(strict)


def _add_report_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=tuple(_REPORT_RENDERERS), default="text")
    parser.add_argument("--out", type=Path, help="Write the report to a file instead of stdout.")
    parser.add_argument("--strict", action="store_true", help="Treat review warnings as a blocking exit code.")


def _validate_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    root = _root_for(manifest_path, args.root)
    _protect_outputs([args.out] if args.out else [], _manifest_inputs(manifest_path, manifest, root))
    report = validate_manifest(manifest, root)
    return _emit_report(report, args.format, args.out, args.strict)


def _build_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    root = _root_for(manifest_path, args.root)
    out_dir = args.out.resolve()
    _protect_outputs(
        [out_dir / name for name in PACKAGE_FILES],
        _manifest_inputs(manifest_path, manifest, root),
    )
    report = validate_manifest(manifest, root)
    json_path, html_path = write_package(report, manifest, out_dir)
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print(f"Status: {report.status}")
    return report.exit_code(args.strict)


def _inspect_command(args: argparse.Namespace) -> int:
    snapshot = index_file(args.root.resolve(), args.path)
    if snapshot is None:
        print(f"Source does not exist: {safe_line(args.path)}", file=sys.stderr)
        return 1
    status = (
        "changed_during_index"
        if snapshot.metadata.get("integrity") == "changed"
        else "parse_unavailable"
        if snapshot.metadata.get("parse") == "unavailable"
        else "indexed"
    )
    all_anchors = sorted(snapshot.anchors, key=anchor_sort_key)
    matched_anchors = (
        [
            anchor for anchor in all_anchors
            if any(anchor.startswith(prefix) for prefix in args.anchor_prefix)
        ]
        if args.anchor_prefix else all_anchors
    )
    anchors = matched_anchors[:args.limit] if args.limit else matched_anchors
    print(json_text({
        "status": status,
        "path": snapshot.path,
        "kind": snapshot.kind,
        "sha256": snapshot.sha256,
        "size_bytes": snapshot.size_bytes,
        "anchor_count": len(all_anchors),
        "matched_anchor_count": len(matched_anchors),
        "anchors_truncated": len(anchors) < len(matched_anchors),
        "anchors": anchors,
        "metadata": dict(snapshot.metadata),
    }), end="")
    return 0 if status == "indexed" else 1


def _audit_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    root = _root_for(manifest_path, args.root)
    protected = _manifest_inputs(manifest_path, manifest, root)
    protected.extend(args.package.resolve() / name for name in PACKAGE_FILES)
    _protect_outputs([args.out] if args.out else [], protected)
    report = audit_package(manifest, root, args.package)
    return _emit_report(report, args.format, args.out, args.strict)


def _init_command(args: argparse.Namespace) -> int:
    manifest_path = create_workspace(args.out, args.project, args.description)
    print(manifest_path)
    return 0


def _intake_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    root = _root_for(manifest_path, args.root)
    added = intake_sources(manifest_path, root, args.source_paths)
    print(f"Registered sources: {added}")
    return 0


def _claim_add_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    root = _root_for(manifest_path, args.root)
    add_claim(
        manifest_path,
        root,
        claim_id=args.id,
        statement=args.statement,
        status=args.status,
        source_path=args.source,
        anchor=args.anchor,
        note=args.note,
    )
    print(f"Added claim: {args.id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidence-office", description="Validate evidence-linked engineering deliverables.")
    parser.add_argument("--version", action="version", version=f"evidence-office {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a JSON manifest and print a report.")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--root", type=Path, help="Root directory containing declared sources; defaults to the manifest directory.")
    _add_report_options(validate)
    validate.set_defaults(handler=_validate_command)

    build = subparsers.add_parser("build", help="Validate and write a portable report package.")
    build.add_argument("manifest", type=Path)
    build.add_argument("--root", type=Path)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--strict", action="store_true", help="Treat review warnings as a blocking exit code.")
    build.set_defaults(handler=_build_command)

    inspect = subparsers.add_parser("inspect", help="Inspect a source file and list deterministic anchors.")
    inspect.add_argument("path")
    inspect.add_argument("--root", type=Path, default=Path.cwd())
    inspect.add_argument(
        "--anchor-prefix",
        action="append",
        default=[],
        help="Return only anchors with this prefix; repeat to match multiple prefixes.",
    )
    inspect.add_argument("--limit", type=_positive_int, help="Return at most this many matching anchors.")
    inspect.set_defaults(handler=_inspect_command)

    audit = subparsers.add_parser("audit", help="Check whether sources still match a built review package.")
    audit.add_argument("manifest", type=Path)
    audit.add_argument("--package", type=Path, required=True, help="Build directory containing source-index.json.")
    audit.add_argument("--root", type=Path)
    _add_report_options(audit)
    audit.set_defaults(handler=_audit_command)

    demo = subparsers.add_parser("demo", help="Create a synthetic, self-contained example project.")
    demo.add_argument("--out", type=Path, required=True)
    demo.set_defaults(handler=lambda args: (print(create_demo(args.out.resolve())), 0)[1])

    init = subparsers.add_parser("init", help="Create a new evidence review workspace.")
    init.add_argument("--out", type=Path, required=True)
    init.add_argument("--project", required=True)
    init.add_argument("--description", default="")
    init.set_defaults(handler=_init_command)

    intake = subparsers.add_parser("intake", help="Register existing source files in a manifest.")
    intake.add_argument("manifest", type=Path)
    intake.add_argument("source_paths", nargs="+", help="Source paths relative to --root or absolute paths inside it.")
    intake.add_argument("--root", type=Path)
    intake.set_defaults(handler=_intake_command)

    claim = subparsers.add_parser("claim", help="Manage claims in a manifest.")
    claim_subparsers = claim.add_subparsers(dest="claim_command", required=True)
    claim_add = claim_subparsers.add_parser("add", help="Add one claim with optional evidence.")
    claim_add.add_argument("manifest", type=Path)
    claim_add.add_argument("--id", required=True)
    claim_add.add_argument("--statement", required=True)
    claim_add.add_argument("--status", choices=("verified", "unverified", "assumption"), required=True)
    claim_add.add_argument("--source")
    claim_add.add_argument("--anchor")
    claim_add.add_argument("--note")
    claim_add.add_argument("--root", type=Path)
    claim_add.set_defaults(handler=_claim_add_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError) as exc:
        print(f"error: {safe_line(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
