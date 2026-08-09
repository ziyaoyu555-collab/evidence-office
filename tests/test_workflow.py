import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evidence_office.model import SCHEMA_VERSION
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
            self.assertTrue((workspace / "dist" / "package-index.json").is_file())
            report_json = json.loads((workspace / "dist" / "evidence-report.json").read_text(encoding="utf-8"))
            source_index = json.loads((workspace / "dist" / "source-index.json").read_text(encoding="utf-8"))
            package_index = json.loads((workspace / "dist" / "package-index.json").read_text(encoding="utf-8"))
            self.assertEqual(report_json["schema_version"], SCHEMA_VERSION)
            self.assertEqual(source_index["schema_version"], report_json["schema_version"])
            self.assertEqual(
                package_index["files"]["evidence-report.json"],
                hashlib.sha256((workspace / "dist" / "evidence-report.json").read_bytes()).hexdigest(),
            )
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

    def test_package_staging_failure_preserves_the_previous_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Atomic package", "Package")
            source = workspace / "source.txt"
            source.write_text("evidence\n", encoding="utf-8")
            intake_sources(manifest_path, workspace, ["source.txt"])
            manifest = load_manifest(manifest_path)
            report = validate_manifest(manifest, workspace)
            dist = workspace / "dist"
            dist.mkdir()
            names = (
                "evidence-report.json",
                "evidence-report.html",
                "evidence-map.md",
                "source-index.json",
                "manifest.snapshot.json",
                "package-index.json",
            )
            for name in names:
                (dist / name).write_text(f"previous:{name}", encoding="utf-8")

            original_write_text = Path.write_text

            def fail_during_staging(path: Path, data: str, *args: object, **kwargs: object) -> int:
                if "evidence-report.html" in path.name:
                    raise OSError("simulated staging failure")
                return original_write_text(path, data, *args, **kwargs)

            with mock.patch.object(Path, "write_text", autospec=True, side_effect=fail_during_staging):
                with self.assertRaisesRegex(OSError, "simulated staging failure"):
                    write_package(report, manifest, dist)

            for name in names:
                self.assertEqual((dist / name).read_text(encoding="utf-8"), f"previous:{name}")
            self.assertEqual({path.name for path in dist.iterdir()}, set(names))

    def test_package_commit_failure_rolls_back_every_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Rollback package", "Package")
            source = workspace / "source.txt"
            source.write_text("evidence\n", encoding="utf-8")
            intake_sources(manifest_path, workspace, ["source.txt"])
            manifest = load_manifest(manifest_path)
            report = validate_manifest(manifest, workspace)
            dist = workspace / "dist"
            write_package(report, manifest, dist)
            previous = {path.name: path.read_bytes() for path in dist.iterdir()}
            original_replace = Path.replace

            def fail_one_commit(path: Path, target: Path, *args: object, **kwargs: object) -> Path:
                if ".stage." in path.name and target.name == "evidence-report.html":
                    raise OSError("simulated commit failure")
                return original_replace(path, target, *args, **kwargs)

            with mock.patch.object(Path, "replace", autospec=True, side_effect=fail_one_commit):
                with self.assertRaisesRegex(OSError, "simulated commit failure"):
                    write_package(report, manifest, dist)

            self.assertEqual({path.name: path.read_bytes() for path in dist.iterdir()}, previous)

    def test_atomic_package_writes_disable_platform_newline_translation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            manifest_path = create_workspace(workspace, "Portable package", "Package")
            source = workspace / "source.txt"
            source.write_text("evidence\n", encoding="utf-8")
            intake_sources(manifest_path, workspace, ["source.txt"])
            manifest = load_manifest(manifest_path)
            report = validate_manifest(manifest, workspace)
            original_write_text = Path.write_text
            newline_arguments: list[object] = []

            def record_newline(path: Path, data: str, *args: object, **kwargs: object) -> int:
                newline_arguments.append(kwargs.get("newline"))
                return original_write_text(path, data, *args, **kwargs)

            with mock.patch.object(Path, "write_text", autospec=True, side_effect=record_newline):
                write_package(report, manifest, workspace / "dist")

            self.assertTrue(newline_arguments)
            self.assertEqual(set(newline_arguments), {""})

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
