"""Command-line interface for the public evidence-office workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .demo import create_demo
from .report import render_html, render_json, render_text, write_package
from .source_index import index_file
from .validator import load_manifest, validate_manifest
from .workflow import add_claim, create_workspace, intake_sources


def _root_for(manifest_path: Path, explicit: Path | None) -> Path:
    return (explicit or manifest_path.parent).resolve()


def _write_or_print(content: str, out: Path | None) -> None:
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(out.resolve())
    else:
        print(content, end="")


def _validate_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    report = validate_manifest(manifest, _root_for(manifest_path, args.root))
    if args.format == "json":
        content = render_json(report)
    elif args.format == "html":
        content = render_html(report)
    else:
        content = render_text(report)
    _write_or_print(content, args.out)
    return 1 if report.status == "failed" or (args.strict and report.warnings) else 0


def _build_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    report = validate_manifest(manifest, _root_for(manifest_path, args.root))
    json_path, html_path = write_package(report, manifest, args.out.resolve())
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print(f"Status: {report.status}")
    return 1 if report.status == "failed" or (args.strict and report.warnings) else 0


def _inspect_command(args: argparse.Namespace) -> int:
    snapshot = index_file(args.root.resolve(), args.path)
    if snapshot is None:
        print(f"Source does not exist: {args.path}", file=sys.stderr)
        return 1
    import json
    print(json.dumps({
        "path": snapshot.path,
        "kind": snapshot.kind,
        "sha256": snapshot.sha256,
        "size_bytes": snapshot.size_bytes,
        "anchors": sorted(snapshot.anchors),
        "metadata": dict(snapshot.metadata),
    }, ensure_ascii=False, indent=2))
    return 0


def _init_command(args: argparse.Namespace) -> int:
    manifest_path = create_workspace(args.out, args.project, args.description)
    print(manifest_path)
    return 0


def _intake_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    root = (args.root or manifest_path.parent).resolve()
    added = intake_sources(manifest_path, root, args.source_paths)
    print(f"Registered sources: {added}")
    return 0


def _claim_add_command(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    root = (args.root or manifest_path.parent).resolve()
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
    validate.add_argument("--format", choices=("text", "json", "html"), default="text")
    validate.add_argument("--out", type=Path, help="Write the report to a file instead of stdout.")
    validate.add_argument("--strict", action="store_true", help="Treat review warnings as a blocking exit code.")
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
    inspect.set_defaults(handler=_inspect_command)

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
    except (FileExistsError, FileNotFoundError, IsADirectoryError, NotADirectoryError, PermissionError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
