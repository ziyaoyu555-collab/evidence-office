import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from evidence_office.model import ProjectManifest
from evidence_office.report import render_html, report_to_dict
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


if __name__ == "__main__":
    unittest.main()
