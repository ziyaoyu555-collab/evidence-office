import json
import tempfile
import unittest
from pathlib import Path

from evidence_office.report import write_package
from evidence_office.validator import load_manifest, validate_manifest
from evidence_office.workflow import add_claim, create_workspace, intake_sources


class WorkflowBehaviourTests(unittest.TestCase):
    def test_init_creates_a_ready_to_use_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"

            manifest_path = create_workspace(workspace, "Energy review", "Review package")

            self.assertTrue((workspace / "sources").is_dir())
            self.assertTrue((workspace / "WORKFLOW.md").is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["project"], "Energy review")
            self.assertEqual(manifest["claims"], [])

    def test_intake_adds_sources_without_destroying_existing_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Energy review", "Review package")
            source_path = workspace / "sources" / "results.csv"
            source_path.write_text("metric,value\nefficiency,0.91\n", encoding="utf-8")
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw["claims"] = [{
                "id": "C-001",
                "statement": "Efficiency is 0.91.",
                "status": "verified",
                "sources": [{"path": "sources/results.csv", "anchor": "row:1/field:value"}],
            }]
            manifest_path.write_text(json.dumps(raw), encoding="utf-8")

            added = intake_sources(manifest_path, workspace, ["sources/results.csv"])

            self.assertEqual(added, 1)
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(updated["sources"]), 1)
            self.assertEqual(updated["claims"][0]["id"], "C-001")
            report = validate_manifest(load_manifest(manifest_path), workspace)
            self.assertEqual(report.status, "passed")
            self.assertEqual(report.claims[0].id, "C-001")

    def test_intake_normalizes_equivalent_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Review", "Package")
            source_path = workspace / "sources" / "results.csv"
            source_path.write_text("metric,value\nefficiency,0.91\n", encoding="utf-8")

            added = intake_sources(
                manifest_path,
                workspace,
                ["./sources/results.csv", "sources/../sources/results.csv"],
            )

            self.assertEqual(added, 1)
            manifest = load_manifest(manifest_path)
            self.assertEqual([source.path for source in manifest.sources], ["sources/results.csv"])

    def test_review_package_contains_markdown_and_source_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Review", "Package")
            source_path = workspace / "source.csv"
            source_path.write_text("metric,value\nefficiency,0.91\n", encoding="utf-8")
            manifest_path.write_text(json.dumps({
                "project": "Review",
                "description": "Package",
                "sources": [{"path": "source.csv"}],
                "claims": [{"id": "C-001", "statement": "Efficiency is 0.91.", "status": "verified", "sources": [{"path": "source.csv", "anchor": "row:1/field:value"}]}],
            }), encoding="utf-8")
            manifest = load_manifest(manifest_path)
            report = validate_manifest(manifest, workspace)

            write_package(report, manifest, workspace / "dist")

            self.assertTrue((workspace / "dist" / "evidence-map.md").is_file())
            self.assertTrue((workspace / "dist" / "source-index.json").is_file())
            report_json = json.loads((workspace / "dist" / "evidence-report.json").read_text(encoding="utf-8"))
            source_index = json.loads((workspace / "dist" / "source-index.json").read_text(encoding="utf-8"))
            self.assertEqual(report_json["schema_version"], "0.6")
            self.assertEqual(source_index["schema_version"], report_json["schema_version"])
            evidence_map = (workspace / "dist" / "evidence-map.md").read_text(encoding="utf-8")
            self.assertIn("Efficiency is 0.91.", evidence_map)
            self.assertIn("source.csv#row:1/field:value", evidence_map)

    def test_package_snapshot_matches_the_validated_manifest_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Original", "Package")
            source = workspace / "source.csv"
            source.write_text("metric,value\nefficiency,0.91\n", encoding="utf-8")
            intake_sources(manifest_path, workspace, ["source.csv"])
            manifest = load_manifest(manifest_path)
            report = validate_manifest(manifest, workspace)

            changed = json.loads(manifest_path.read_text(encoding="utf-8"))
            changed["project"] = "Changed after validation"
            manifest_path.write_text(json.dumps(changed), encoding="utf-8")
            dist = workspace / "dist"
            write_package(report, manifest, dist)

            snapshot = json.loads((dist / "manifest.snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["project"], "Original")

    def test_add_claim_creates_a_valid_claim_without_manual_json_editing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Review", "Package")
            source_path = workspace / "results.csv"
            source_path.write_text("metric,value\nefficiency,0.91\n", encoding="utf-8")
            intake_sources(manifest_path, workspace, ["results.csv"])

            add_claim(
                manifest_path,
                workspace,
                claim_id="C-001",
                statement="Efficiency is 0.91.",
                status="verified",
                source_path="results.csv",
                anchor="row:1/field:value",
            )

            report = validate_manifest(load_manifest(manifest_path), workspace)
            self.assertEqual(report.status, "passed")

    def test_add_claim_rejects_a_source_that_cannot_be_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Review", "Package")
            source = workspace / "sources" / "broken.docx"
            source.write_bytes(b"not a docx")

            with self.assertRaisesRegex(ValueError, "indexed safely"):
                add_claim(
                    manifest_path,
                    workspace,
                    claim_id="C-001",
                    statement="The document supports this claim.",
                    status="verified",
                    source_path="sources/broken.docx",
                    anchor="paragraph:1",
                )

            manifest = load_manifest(manifest_path)
            self.assertEqual(manifest.sources, ())
            self.assertEqual(manifest.claims, ())


if __name__ == "__main__":
    unittest.main()
