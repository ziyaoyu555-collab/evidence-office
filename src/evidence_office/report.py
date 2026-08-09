"""Stable JSON, text, and standalone HTML representations of validation results."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .model import AuditReport, ProjectManifest, ValidationReport


def report_to_dict(report: ValidationReport) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "0.3",
        "report_type": "drift_audit" if isinstance(report, AuditReport) else "validation",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project": report.project,
        "status": report.status,
        "claims_checked": report.claims_checked,
        "claims": [
            {
                "id": claim.id,
                "statement": claim.statement,
                "status": claim.status,
                "note": claim.note,
                "sources": [
                    {"path": ref.path, "anchor": ref.anchor, "note": ref.note}
                    for ref in claim.sources
                ],
            }
            for claim in report.claims
        ],
        "summary": {
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "sources_indexed": len(report.sources),
        },
        "issues": [asdict(issue) for issue in report.issues],
        "sources": [
            {
                "path": source.path,
                "kind": source.kind,
                "sha256": source.sha256,
                "size_bytes": source.size_bytes,
                "anchors": sorted(source.anchors),
                "metadata": dict(source.metadata),
            }
            for source in report.sources
        ],
    }
    if isinstance(report, AuditReport):
        payload["audit"] = {
            "baseline_sources": [
                {
                    "path": source.path,
                    "kind": source.kind,
                    "sha256": source.sha256,
                    "size_bytes": source.size_bytes,
                }
                for source in report.baseline_sources
            ],
            "current_sources": len(report.current_sources),
        }
    return payload


def render_json(report: ValidationReport) -> str:
    return json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n"


def render_text(report: ValidationReport) -> str:
    lines = [
        f"Project: {report.project or '(unnamed)'}",
        f"Status: {report.status}",
        f"Claims checked: {report.claims_checked}",
        f"Sources indexed: {len(report.sources)}",
        f"Errors: {len(report.errors)} | Warnings: {len(report.warnings)}",
    ]
    if isinstance(report, AuditReport):
        lines.append(f"Baseline sources: {len(report.baseline_sources)}")
    if report.issues:
        lines.append("Issues:")
        for issue in report.issues:
            location = ""
            if issue.claim_id:
                location += f" claim={issue.claim_id}"
            if issue.path:
                location += f" path={issue.path}"
            if issue.anchor:
                location += f" anchor={issue.anchor}"
            lines.append(f"- [{issue.severity}] {issue.code}:{location} {issue.message}")
    else:
        lines.append("No issues.")
    if report.claims:
        lines.append("Claims:")
        for claim in report.claims:
            references = ", ".join(
                f"{ref.path}#{ref.anchor}" if ref.anchor else ref.path
                for ref in claim.sources
            ) or "(no evidence references)"
            lines.append(f"- [{claim.status}] {claim.id}: {claim.statement} — {references}")
    return "\n".join(lines) + "\n"


def render_markdown(report: ValidationReport) -> str:
    data = report_to_dict(report)
    lines = [
        f"# Evidence map — {report.project or 'Unnamed project'}",
        "",
        f"- Status: **{report.status}**",
        f"- Claims checked: **{report.claims_checked}**",
        f"- Sources indexed: **{len(report.sources)}**",
        f"- Blocking errors: **{len(report.errors)}**",
        f"- Review warnings: **{len(report.warnings)}**",
        "",
        "## Claim ledger",
        "",
        "| ID | Status | Statement | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    if data["claims"]:
        for claim in data["claims"]:
            evidence = "<br>".join(
                f"`{ref['path']}#{ref['anchor']}`" if ref["anchor"] else f"`{ref['path']}`"
                for ref in claim["sources"]
            ) or "_none_"
            statement = claim["statement"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{claim['id']}` | `{claim['status']}` | {statement} | {evidence} |")
    else:
        lines.append("| — | — | No claims declared. | — |")
    lines.extend(["", "## Issues", ""])
    if report.issues:
        lines.extend([
            "| Severity | Code | Message | Claim | Location |",
            "| --- | --- | --- | --- | --- |",
        ])
        for issue in report.issues:
            location = " ".join(part for part in [issue.path, issue.anchor] if part) or "—"
            message = issue.message.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{issue.severity}` | `{issue.code}` | {message} | `{issue.claim_id or '—'}` | `{location}` |")
    else:
        lines.append("No issues.")
    lines.extend(["", "## Source fingerprints", "", "| Path | Kind | SHA-256 | Bytes | Anchors |", "| --- | --- | --- | ---: | ---: |"])
    for source in data["sources"]:
        lines.append(f"| `{source['path']}` | `{source['kind']}` | `{source['sha256']}` | {source['size_bytes']} | {len(source['anchors'])} |")
    if not data["sources"]:
        lines.append("| — | — | — | 0 | 0 |")
    lines.extend(["", "> A passed report means only that this version's deterministic checks passed; it is not a substitute for domain review.", ""])
    return "\n".join(lines)


def render_html(report: ValidationReport) -> str:
    data = report_to_dict(report)
    status_class = "ok" if report.status == "passed" else "warn" if report.status == "passed_with_warnings" else "fail"
    issue_rows = "".join(
        "<tr>"
        f"<td><span class='badge {html.escape(issue.severity)}'>{html.escape(issue.severity)}</span></td>"
        f"<td><code>{html.escape(issue.code)}</code></td>"
        f"<td>{html.escape(issue.message)}</td>"
        f"<td>{html.escape(issue.claim_id or '')}</td>"
        f"<td>{html.escape(issue.path or '')}{(' · ' + html.escape(issue.anchor)) if issue.anchor else ''}</td>"
        "</tr>"
        for issue in report.issues
    )
    source_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(source['path'])}</code></td>"
        f"<td>{html.escape(source['kind'])}</td>"
        f"<td>{source['size_bytes']}</td>"
        f"<td><code>{html.escape(source['sha256'][:16])}…</code></td>"
        f"<td>{len(source['anchors'])}</td>"
        "</tr>"
        for source in data["sources"]
    )
    claim_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(claim['id'])}</code></td>"
        f"<td><span class='badge claim-{html.escape(claim['status'])}'>{html.escape(claim['status'])}</span></td>"
        f"<td>{html.escape(claim['statement'])}</td>"
        f"<td>{'<br>'.join('<code>' + html.escape(ref['path']) + ('#' + html.escape(ref['anchor']) if ref['anchor'] else '') + '</code>' for ref in claim['sources']) or '<span class=\"muted\">none</span>'}</td>"
        "</tr>"
        for claim in data["claims"]
    )
    issues_block = (
        "<p class='muted'>No issues. Every checked rule passed.</p>"
        if not report.issues
        else f"<table><thead><tr><th>Level</th><th>Code</th><th>Message</th><th>Claim</th><th>Location</th></tr></thead><tbody>{issue_rows}</tbody></table>"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evidence report — {html.escape(report.project or 'unnamed')}</title>
<style>
:root {{ color-scheme: light dark; --bg:#0b1020; --panel:#141b2d; --text:#edf2ff; --muted:#aeb9d2; --line:#2b3858; --ok:#53d39b; --warn:#f2c96d; --fail:#ff7e89; }}
* {{ box-sizing:border-box; }} body {{ margin:0; font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }}
main {{ max-width:1120px; margin:0 auto; padding:48px 24px 72px; }} h1 {{ margin:0 0 8px; font-size:34px; }} h2 {{ margin:36px 0 14px; font-size:20px; }} .muted {{ color:var(--muted); }}
.hero {{ display:flex; gap:16px; align-items:center; justify-content:space-between; margin-bottom:28px; }} .status {{ border:1px solid var(--line); border-radius:999px; padding:8px 14px; font-weight:700; }} .status.ok {{ color:var(--ok); }} .status.warn {{ color:var(--warn); }} .status.fail {{ color:var(--fail); }}
.cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }} .card {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:16px; }} .card b {{ display:block; font-size:26px; }} .card span {{ color:var(--muted); }}
table {{ width:100%; border-collapse:collapse; overflow:hidden; background:var(--panel); border:1px solid var(--line); border-radius:14px; }} th,td {{ padding:11px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }} tr:last-child td {{ border-bottom:0; }} code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:#c5d4ff; }} .badge {{ display:inline-block; border-radius:999px; padding:2px 8px; font-size:12px; font-weight:700; }} .badge.error, .badge.claim-verified {{ color:#24090d; background:var(--fail); }} .badge.warning, .badge.claim-assumption, .badge.claim-unverified {{ color:#2a2005; background:var(--warn); }} .badge.info {{ color:#06291b; background:var(--ok); }}
@media(max-width:720px) {{ .hero {{ align-items:flex-start; flex-direction:column; }} .cards {{ grid-template-columns:repeat(2,1fr); }} table {{ display:block; overflow:auto; white-space:nowrap; }} }}
</style></head><body><main>
<div class="hero"><div><h1>Evidence report</h1><div class="muted">{html.escape(report.project or 'Unnamed project')}</div></div><div class="status {status_class}">{html.escape(report.status)}</div></div>
<section class="cards"><div class="card"><b>{report.claims_checked}</b><span>claims checked</span></div><div class="card"><b>{len(report.sources)}</b><span>sources indexed</span></div><div class="card"><b>{len(report.errors)}</b><span>blocking errors</span></div><div class="card"><b>{len(report.warnings)}</b><span>review warnings</span></div></section>
<h2>Claim ledger</h2><table><thead><tr><th>ID</th><th>Status</th><th>Statement</th><th>Evidence</th></tr></thead><tbody>{claim_rows or '<tr><td colspan="4" class="muted">No claims declared.</td></tr>'}</tbody></table>
<h2>Issues</h2>{issues_block}
<h2>Source fingerprints</h2><table><thead><tr><th>Path</th><th>Kind</th><th>Bytes</th><th>SHA-256</th><th>Anchors</th></tr></thead><tbody>{source_rows or '<tr><td colspan="5" class="muted">No existing declared sources.</td></tr>'}</tbody></table>
<p class="muted" style="margin-top:28px">Generated by evidence-office {html.escape(__version__)}. A passed report means only that the deterministic checks in this version passed; it is not a substitute for domain review.</p>
</main></body></html>\n"""


def write_package(report: ValidationReport, manifest: ProjectManifest, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "evidence-report.json"
    html_path = out_dir / "evidence-report.html"
    markdown_path = out_dir / "evidence-map.md"
    source_index_path = out_dir / "source-index.json"
    json_path.write_text(render_json(report), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    source_index_path.write_text(json.dumps({
        "schema_version": "0.3",
        "sources": report_to_dict(report)["sources"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if manifest.manifest_path and manifest.manifest_path.is_file():
        (out_dir / "manifest.snapshot.json").write_bytes(manifest.manifest_path.read_bytes())
    return json_path, html_path
