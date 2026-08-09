"""Stable JSON, text, and standalone HTML representations of validation results."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .model import AuditReport, ProjectManifest, SCHEMA_VERSION, SourceSnapshot, ValidationReport


Report = ValidationReport | AuditReport


def _source_to_dict(source: SourceSnapshot, include_details: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": source.path,
        "kind": source.kind,
        "sha256": source.sha256,
        "size_bytes": source.size_bytes,
    }
    if include_details:
        data.update(anchors=sorted(source.anchors), metadata=dict(source.metadata))
    return data


def _md_text(value: object) -> str:
    return html.escape(str(value), quote=False).replace("|", "\\|").replace("\n", " ")


def _md_code(value: object) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    content = f" {text} " if longest else text
    return f"{fence}{content}{fence}"


def _html_reference(ref: dict[str, Any]) -> str:
    location = ref["path"] + (f"#{ref['anchor']}" if ref["anchor"] else "")
    note = f" <span class='muted'>— {html.escape(ref['note'])}</span>" if ref["note"] else ""
    return f"<code>{html.escape(location)}</code>{note}"


def report_to_dict(report: Report) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
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
        "sources": [_source_to_dict(source) for source in report.sources],
    }
    if isinstance(report, AuditReport):
        payload["audit"] = {
            "baseline_sources": [_source_to_dict(source, include_details=False) for source in report.baseline_sources],
            "current_sources": len(report.current_sources),
        }
    return payload


def render_json(report: Report) -> str:
    return json.dumps(report_to_dict(report), ensure_ascii=False, indent=2) + "\n"


def render_text(report: Report) -> str:
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
                (f"{ref.path}#{ref.anchor}" if ref.anchor else ref.path)
                + (f" ({ref.note})" if ref.note else "")
                for ref in claim.sources
            ) or "(no evidence references)"
            note = f" | Note: {claim.note}" if claim.note else ""
            lines.append(f"- [{claim.status}] {claim.id}: {claim.statement} — {references}{note}")
    return "\n".join(lines) + "\n"


def render_markdown(report: Report) -> str:
    data = report_to_dict(report)
    lines = [
        f"# Evidence map — {_md_text(report.project or 'Unnamed project')}",
        "",
        f"- Status: **{report.status}**",
        f"- Claims checked: **{report.claims_checked}**",
        f"- Sources indexed: **{len(report.sources)}**",
        f"- Blocking errors: **{len(report.errors)}**",
        f"- Review warnings: **{len(report.warnings)}**",
        "",
        "## Claim ledger",
        "",
        "| ID | Status | Statement | Evidence | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    if data["claims"]:
        for claim in data["claims"]:
            evidence = "<br>".join(
                _md_code(f"{ref['path']}#{ref['anchor']}" if ref["anchor"] else ref["path"])
                + (f" — {_md_text(ref['note'])}" if ref["note"] else "")
                for ref in claim["sources"]
            ) or "_none_"
            lines.append(
                f"| {_md_code(claim['id'])} | {_md_code(claim['status'])} | "
                f"{_md_text(claim['statement'])} | {evidence} | {_md_text(claim['note'] or '—')} |"
            )
    else:
        lines.append("| — | — | No claims declared. | — | — |")
    lines.extend(["", "## Issues", ""])
    if report.issues:
        lines.extend([
            "| Severity | Code | Message | Claim | Location |",
            "| --- | --- | --- | --- | --- |",
        ])
        for issue in report.issues:
            location = " ".join(part for part in [issue.path, issue.anchor] if part) or "—"
            lines.append(
                f"| {_md_code(issue.severity)} | {_md_code(issue.code)} | {_md_text(issue.message)} | "
                f"{_md_code(issue.claim_id or '—')} | {_md_code(location)} |"
            )
    else:
        lines.append("No issues.")
    lines.extend(["", "## Source fingerprints", "", "| Path | Kind | SHA-256 | Bytes | Anchors |", "| --- | --- | --- | ---: | ---: |"])
    for source in data["sources"]:
        lines.append(
            f"| {_md_code(source['path'])} | {_md_code(source['kind'])} | {_md_code(source['sha256'])} | "
            f"{source['size_bytes']} | {len(source['anchors'])} |"
        )
    if not data["sources"]:
        lines.append("| — | — | — | 0 | 0 |")
    lines.extend(["", "> A passed report means only that this version's deterministic checks passed; it is not a substitute for domain review.", ""])
    return "\n".join(lines)


def render_html(report: Report) -> str:
    data = report_to_dict(report)
    is_audit = isinstance(report, AuditReport)
    report_name = "Source drift audit" if is_audit else "Evidence report"
    baseline_card = (
        f'<div class="card"><b>{len(report.baseline_sources)}</b><span>baseline sources</span></div>'
        if is_audit else ""
    )
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
        f"<td>{'<br>'.join(_html_reference(ref) for ref in claim['sources']) or '<span class=\"muted\">none</span>'}</td>"
        f"<td>{html.escape(claim['note'] or '')}</td>"
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
<title>{report_name} — {html.escape(report.project or 'unnamed')}</title>
<style>
:root {{ color-scheme: light dark; --bg:#0b1020; --panel:#141b2d; --text:#edf2ff; --muted:#aeb9d2; --line:#2b3858; --ok:#53d39b; --warn:#f2c96d; --fail:#ff7e89; }}
* {{ box-sizing:border-box; }} body {{ margin:0; font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }}
main {{ max-width:1120px; margin:0 auto; padding:48px 24px 72px; }} h1 {{ margin:0 0 8px; font-size:34px; }} h2 {{ margin:36px 0 14px; font-size:20px; }} .muted {{ color:var(--muted); }}
.hero {{ display:flex; gap:16px; align-items:center; justify-content:space-between; margin-bottom:28px; }} .status {{ border:1px solid var(--line); border-radius:999px; padding:8px 14px; font-weight:700; }} .status.ok {{ color:var(--ok); }} .status.warn {{ color:var(--warn); }} .status.fail {{ color:var(--fail); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }} .card {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:16px; }} .card b {{ display:block; font-size:26px; }} .card span {{ color:var(--muted); }}
table {{ width:100%; border-collapse:collapse; overflow:hidden; background:var(--panel); border:1px solid var(--line); border-radius:14px; }} th,td {{ padding:11px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }} tr:last-child td {{ border-bottom:0; }} code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:#c5d4ff; }} .badge {{ display:inline-block; border-radius:999px; padding:2px 8px; font-size:12px; font-weight:700; }} .badge.error {{ color:#24090d; background:var(--fail); }} .badge.warning, .badge.claim-assumption, .badge.claim-unverified {{ color:#2a2005; background:var(--warn); }} .badge.claim-verified {{ color:#06291b; background:var(--ok); }} .badge.info {{ color:#06291b; background:var(--ok); }}
@media(max-width:720px) {{ .hero {{ align-items:flex-start; flex-direction:column; }} .cards {{ grid-template-columns:repeat(2,1fr); }} table {{ display:block; overflow:auto; white-space:nowrap; }} }}
</style></head><body><main>
<div class="hero"><div><h1>{report_name}</h1><div class="muted">{html.escape(report.project or 'Unnamed project')}</div></div><div class="status {status_class}">{html.escape(report.status)}</div></div>
<section class="cards"><div class="card"><b>{report.claims_checked}</b><span>claims checked</span></div><div class="card"><b>{len(report.sources)}</b><span>sources indexed</span></div>{baseline_card}<div class="card"><b>{len(report.errors)}</b><span>blocking errors</span></div><div class="card"><b>{len(report.warnings)}</b><span>review warnings</span></div></section>
<h2>Claim ledger</h2><table><thead><tr><th>ID</th><th>Status</th><th>Statement</th><th>Evidence</th><th>Note</th></tr></thead><tbody>{claim_rows or '<tr><td colspan="5" class="muted">No claims declared.</td></tr>'}</tbody></table>
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
        "schema_version": SCHEMA_VERSION,
        "sources": [_source_to_dict(source) for source in report.sources],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "manifest.snapshot.json").write_text(
        json.dumps(manifest.to_mapping(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return json_path, html_path
