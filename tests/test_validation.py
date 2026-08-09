import csv
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from evidence_office.model import ProjectManifest
from evidence_office.report import render_html, render_markdown, render_text, report_to_dict
from evidence_office.source_index import index_file
from evidence_office.validator import validate_manifest


class ValidationBehaviourTests(unittest.TestCase):
    def test_valid_csv_evidence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "results.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
                writer.writeheader()
                writer.writerow({"metric": "efficiency", "value": "0.91"})
            manifest = ProjectManifest.from_mapping(
                {
                    "project": "Demo",
                    "sources": [{"path": "results.csv"}],
                    "claims": [{
                        "id": "C-001",
                        "statement": "Efficiency is 0.91.",
                        "status": "verified",
                        "sources": [{"path": "results.csv", "anchor": "row:1/field:value"}],
                    }],
                }
            )

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed")
            self.assertEqual(report.errors, ())

            payload = report_to_dict(report)
            self.assertEqual(payload["claims"][0]["id"], "C-001")
            self.assertEqual(payload["claims"][0]["sources"][0]["anchor"], "row:1/field:value")
            html = render_html(report)
            self.assertIn("Efficiency is 0.91.", html)
            self.assertIn("row:1/field:value", html)
            self.assertIn(".badge.claim-verified { color:#06291b; background:var(--ok); }", html)

    def test_null_manifest_fields_are_missing_not_literal_strings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = ProjectManifest.from_mapping({
                "project": None,
                "sources": [{"path": None}],
                "claims": [{
                    "id": None,
                    "statement": None,
                    "status": "verified",
                    "sources": [{"path": None, "anchor": "line:1"}],
                }],
            })

            report = validate_manifest(manifest, root)
            codes = {issue.code for issue in report.errors}

            self.assertIn("PROJECT_NAME_MISSING", codes)
            self.assertIn("SOURCE_PATH_MISSING", codes)
            self.assertIn("CLAIM_ID_MISSING", codes)
            self.assertIn("CLAIM_STATEMENT_MISSING", codes)
            self.assertIn("EVIDENCE_PATH_MISSING", codes)

    def test_markdown_report_escapes_html_and_table_delimiters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_name = "a|b`c.txt"
            (root / source_name).write_text("evidence\n", encoding="utf-8")
            manifest = ProjectManifest.from_mapping({
                "project": "<Unsafe | project>",
                "sources": [{"path": source_name}],
                "claims": [{
                    "id": "C|`1",
                    "statement": "<script>alert(1)</script> | result",
                    "status": "verified",
                    "sources": [{"path": source_name, "anchor": "line:1"}],
                }],
            })

            markdown = render_markdown(validate_manifest(manifest, root))

            self.assertNotIn("<script>", markdown)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; \\| result", markdown)
            self.assertIn("a\\|b`c.txt#line:1", markdown)

    def test_human_reports_include_claim_and_evidence_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text("evidence\n", encoding="utf-8")
            manifest = ProjectManifest.from_mapping({
                "project": "Review notes",
                "sources": [{"path": "source.txt"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "Evidence exists.",
                    "status": "verified",
                    "note": "Review <before release>",
                    "sources": [{
                        "path": "source.txt",
                        "anchor": "line:1",
                        "note": "Exact | supporting line",
                    }],
                }],
            })
            report = validate_manifest(manifest, root)

            text_report = render_text(report)
            markdown = render_markdown(report)
            html_report = render_html(report)

            self.assertIn("Review <before release>", text_report)
            self.assertIn("Exact | supporting line", text_report)
            self.assertIn("Review &lt;before release&gt;", markdown)
            self.assertIn("Exact \\| supporting line", markdown)
            self.assertIn("Review &lt;before release&gt;", html_report)
            self.assertIn("Exact | supporting line", html_report)

    def test_nested_json_pointer_anchor_can_be_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results.json").write_text(
                '{"metrics": {"efficiency": 0.91, "runs": [{"id": 1}]}}',
                encoding="utf-8",
            )
            manifest = ProjectManifest.from_mapping({
                "project": "Nested JSON demo",
                "sources": [{"path": "results.json"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "Efficiency is 0.91.",
                    "status": "verified",
                    "sources": [{"path": "results.json", "anchor": "json:/metrics/efficiency"}],
                }],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed")

    def test_json_source_with_invalid_unicode_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "invalid.json").write_text('{"value":"\\ud800"}', encoding="utf-8")
            manifest = ProjectManifest.from_mapping({
                "project": "Invalid source Unicode",
                "sources": [{"path": "invalid.json"}],
                "claims": [],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("SOURCE_PARSE_UNAVAILABLE", {issue.code for issue in report.errors})

    def test_index_file_does_not_read_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "root"
            root.mkdir()
            (parent / "outside.json").write_text('{"secret": true}', encoding="utf-8")

            snapshot = index_file(root, "../outside.json")

            self.assertIsNone(snapshot)

    def test_verified_claim_cannot_use_only_a_file_level_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes.txt").write_text("A result exists.\n", encoding="utf-8")
            manifest = ProjectManifest.from_mapping({
                "project": "Generic anchor demo",
                "sources": [{"path": "notes.txt"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "The result is verified.",
                    "status": "verified",
                    "sources": [{"path": "notes.txt", "anchor": "file"}],
                }],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("VERIFIED_EVIDENCE_ANCHOR_NOT_PRECISE", {issue.code for issue in report.errors})

    def test_missing_declared_source_is_a_blocking_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = ProjectManifest.from_mapping(
                {
                    "project": "Demo",
                    "sources": [{"path": "missing.csv"}],
                    "claims": [],
                }
            )

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("SOURCE_MISSING", {issue.code for issue in report.errors})

    def test_unverified_claim_is_visible_as_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes.txt").write_text("working hypothesis\n", encoding="utf-8")
            manifest = ProjectManifest.from_mapping(
                {
                    "project": "Demo",
                    "sources": [{"path": "notes.txt"}],
                    "claims": [{
                        "id": "A-001",
                        "statement": "This is a working hypothesis.",
                        "status": "unverified",
                        "sources": [{"path": "notes.txt", "anchor": "line:1"}],
                    }],
                }
            )

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed_with_warnings")
            self.assertIn("CLAIM_UNVERIFIED", {issue.code for issue in report.warnings})

    def test_xlsx_cell_anchor_can_be_verified_without_third_party_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "results.xlsx"
            with zipfile.ZipFile(workbook, "w") as archive:
                archive.writestr("xl/workbook.xml", """<?xml version='1.0' encoding='UTF-8'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Results' sheetId='1' r:id='rId1'/></sheets></workbook>""")
                archive.writestr("xl/_rels/workbook.xml.rels", """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='worksheets/sheet1.xml' Type='worksheet'/></Relationships>""")
                archive.writestr("xl/worksheets/sheet1.xml", """<?xml version='1.0' encoding='UTF-8'?>
<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData><row r='2'><c r='B2' t='n'><v>91</v></c></row></sheetData></worksheet>""")
            manifest = ProjectManifest.from_mapping(
                {
                    "project": "XLSX demo",
                    "sources": [{"path": "results.xlsx"}],
                    "claims": [{
                        "id": "C-001",
                        "statement": "The measured value is 91.",
                        "status": "verified",
                        "sources": [{"path": "results.xlsx", "anchor": "sheet:Results/cell:B2"}],
                    }],
                }
            )

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed")

    def test_xlsx_missing_worksheet_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "broken.xlsx", "w") as archive:
                archive.writestr("xl/workbook.xml", """<?xml version='1.0' encoding='UTF-8'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Results' sheetId='1' r:id='rId1'/></sheets></workbook>""")
                archive.writestr("xl/_rels/workbook.xml.rels", """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='worksheet' Target='worksheets/missing.xml'/></Relationships>""")
            manifest = ProjectManifest.from_mapping({
                "project": "Broken workbook",
                "sources": [{"path": "broken.xlsx"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "The Results sheet exists.",
                    "status": "verified",
                    "sources": [{"path": "broken.xlsx", "anchor": "sheet:Results"}],
                }],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("SOURCE_PARSE_UNAVAILABLE", {issue.code for issue in report.errors})

    def test_source_outside_root_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            manifest = ProjectManifest.from_mapping(
                {
                    "project": "Unsafe path demo",
                    "sources": [{"path": "../outside.csv"}],
                    "claims": [],
                }
            )

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("SOURCE_OUTSIDE_ROOT", {issue.code for issue in report.errors})

    def test_invalid_source_path_fails_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = ProjectManifest.from_mapping({
                "project": "Invalid path",
                "sources": [{"path": "bad\x00name.txt"}],
                "claims": [],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("SOURCE_PATH_INVALID", {issue.code for issue in report.errors})

    def test_source_fingerprint_io_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.txt").write_text("evidence\n", encoding="utf-8")
            manifest = ProjectManifest.from_mapping({
                "project": "Read failure",
                "sources": [{"path": "source.txt"}],
                "claims": [],
            })

            with mock.patch("evidence_office.source_index._sha256", side_effect=OSError("read failed")):
                report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("SOURCE_READ_UNAVAILABLE", {issue.code for issue in report.errors})

    def test_equivalent_manual_paths_resolve_to_one_declared_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results.txt").write_text("evidence\n", encoding="utf-8")
            manifest = ProjectManifest.from_mapping({
                "project": "Canonical paths",
                "sources": [{"path": "./folder/../results.txt"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "Evidence exists.",
                    "status": "verified",
                    "sources": [{"path": "results.txt", "anchor": "line:1"}],
                }],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed")
            self.assertEqual(manifest.sources[0].path, "results.txt")

    def test_docx_paragraph_anchor_can_be_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "report.docx", "w") as archive:
                archive.writestr("word/document.xml", """<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>Evidence</w:t></w:r></w:p></w:body></w:document>""")
            manifest = ProjectManifest.from_mapping({
                "project": "DOCX demo",
                "sources": [{"path": "report.docx"}],
                "claims": [{"id": "C-001", "statement": "Evidence exists.", "status": "verified", "sources": [{"path": "report.docx", "anchor": "paragraph:1"}]}],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed")

    def test_pptx_slide_anchor_can_be_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "deck.pptx", "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", """<?xml version='1.0' encoding='UTF-8'?>
<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Evidence</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>""")
            manifest = ProjectManifest.from_mapping({
                "project": "PPTX demo",
                "sources": [{"path": "deck.pptx"}],
                "claims": [{"id": "C-001", "statement": "The deck has a first slide.", "status": "verified", "sources": [{"path": "deck.pptx", "anchor": "slide:1/text"}]}],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed")

    def test_blank_pptx_slide_has_no_text_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "blank.pptx", "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", """<?xml version='1.0' encoding='UTF-8'?>
<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree/></p:cSld></p:sld>""")
            manifest = ProjectManifest.from_mapping({
                "project": "Blank PPTX",
                "sources": [{"path": "blank.pptx"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "The blank slide contains supporting text.",
                    "status": "verified",
                    "sources": [{"path": "blank.pptx", "anchor": "slide:1/text"}],
                }],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("EVIDENCE_ANCHOR_NOT_FOUND", {issue.code for issue in report.errors})

    def test_pptx_anchors_follow_presentation_order_after_reordering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "reordered.pptx", "w") as archive:
                archive.writestr("ppt/presentation.xml", """<?xml version='1.0' encoding='UTF-8'?>
<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><p:sldIdLst><p:sldId id='257' r:id='rId2'/><p:sldId id='256' r:id='rId1'/></p:sldIdLst></p:presentation>""")
                archive.writestr("ppt/_rels/presentation.xml.rels", """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='slide' Target='slides/slide1.xml'/><Relationship Id='rId2' Type='slide' Target='slides/slide2.xml'/></Relationships>""")
                archive.writestr("ppt/slides/slide1.xml", """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree/></p:cSld></p:sld>""")
                archive.writestr("ppt/slides/slide2.xml", """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree><a:t>Evidence</a:t></p:spTree></p:cSld></p:sld>""")

            snapshot = index_file(root, "reordered.pptx")

            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertIn("slide:1/text", snapshot.anchors)
            self.assertNotIn("slide:2/text", snapshot.anchors)

    def test_malformed_declared_source_fails_even_when_uncited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.docx").write_bytes(b"not a docx")
            (root / "valid.txt").write_text("evidence\n", encoding="utf-8")
            manifest = ProjectManifest.from_mapping({
                "project": "Fail closed",
                "sources": [{"path": "broken.docx"}, {"path": "valid.txt"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "Valid text exists.",
                    "status": "verified",
                    "sources": [{"path": "valid.txt", "anchor": "line:1"}],
                }],
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "failed")
            self.assertIn("SOURCE_PARSE_UNAVAILABLE", {issue.code for issue in report.errors})


if __name__ == "__main__":
    unittest.main()
