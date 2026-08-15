import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evidence_office.audit import audit_package
from evidence_office.model import SCHEMA_VERSION
from evidence_office.report import PACKAGE_CONTENT_FILES, render_html
from evidence_office.validator import load_manifest
from evidence_office.workflow import create_workspace, intake_sources


class AuditBehaviourTests(unittest.TestCase):
    def _built_workspace(self, directory: str) -> tuple[Path, Path, Path]:
        workspace = Path(directory) / "package"
        manifest_path = create_workspace(workspace, "Audit review", "Drift audit")
        source_path = workspace / "sources" / "results.csv"
        source_path.write_text("metric,value\nefficiency,0.91\n", encoding="utf-8")
        intake_sources(manifest_path, workspace, ["sources/results.csv"])
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw["claims"] = [{
            "id": "C-001",
            "statement": "Efficiency is 0.91.",
            "status": "verified",
            "sources": [{"path": "sources/results.csv", "anchor": "row:1/field:value"}],
        }]
        manifest_path.write_text(json.dumps(raw), encoding="utf-8")
        manifest = load_manifest(manifest_path)
        from evidence_office.report import write_package
        from evidence_office.validator import validate_manifest
        report = validate_manifest(manifest, workspace)
        dist = workspace / "dist"
        write_package(report, manifest, dist)
        return workspace, manifest_path, dist

    def test_unchanged_package_passes_drift_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "passed")
            self.assertEqual(result.errors, ())
            self.assertEqual(result.baseline_sources[0].sha256, result.current_sources[0].sha256)
            self.assertIn("<h1>Source drift audit</h1>", render_html(result))

    def test_manifest_formatting_only_does_not_create_false_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_path.write_text(json.dumps(raw, sort_keys=True, indent=4), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "passed")

    def test_legacy_baseline_path_alias_does_not_create_false_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            source_index = json.loads((dist / "source-index.json").read_text(encoding="utf-8"))
            source_index["schema_version"] = "0.3"
            source_index["sources"][0]["path"] = "./sources/../sources/results.csv"
            (dist / "source-index.json").write_text(json.dumps(source_index), encoding="utf-8")
            (dist / "package-index.json").unlink()

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "passed")

    def test_v06_package_without_checksum_index_remains_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            source_index_path = dist / "source-index.json"
            source_index = json.loads(source_index_path.read_text(encoding="utf-8"))
            source_index["schema_version"] = "0.6"
            source_index_path.write_text(json.dumps(source_index), encoding="utf-8")
            (dist / "package-index.json").unlink()

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "passed")

    def test_v07_package_with_checksum_index_remains_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            source_index_path = dist / "source-index.json"
            source_index = json.loads(source_index_path.read_text(encoding="utf-8"))
            source_index["schema_version"] = "0.7"
            source_index_path.write_text(json.dumps(source_index), encoding="utf-8")
            package_index_path = dist / "package-index.json"
            package_index = json.loads(package_index_path.read_text(encoding="utf-8"))
            package_index["schema_version"] = "0.7"
            package_index["files"] = {
                name: hashlib.sha256((dist / name).read_bytes()).hexdigest()
                for name in PACKAGE_CONTENT_FILES
            }
            package_index_path.write_text(json.dumps(package_index), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "passed")

    def test_changed_source_fails_drift_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            (workspace / "sources" / "results.csv").write_text(
                "metric,value\nefficiency,0.92\n", encoding="utf-8"
            )

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("SOURCE_DRIFTED", {issue.code for issue in result.errors})

    def test_tampered_generated_report_fails_package_integrity_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            (dist / "evidence-map.md").write_text("tampered review map\n", encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("PACKAGE_FILE_DRIFTED", {issue.code for issue in result.errors})

    def test_missing_generated_report_fails_package_integrity_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            (dist / "evidence-report.html").unlink()

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("PACKAGE_FILE_MISSING", {issue.code for issue in result.errors})

    def test_invalid_baseline_fails_without_inventing_current_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            (dist / "source-index.json").write_text("{not-json", encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})
            self.assertEqual(result.current_sources[0].path, "sources/results.csv")

    def test_duplicate_baseline_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            source_index_path = dist / "source-index.json"
            content = source_index_path.read_text(encoding="utf-8")
            content = content.replace(
                f'"schema_version": "{SCHEMA_VERSION}"',
                f'"schema_version": "999",\n  "schema_version": "{SCHEMA_VERSION}"',
                1,
            )
            source_index_path.write_text(content, encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})

    def test_legacy_source_index_rejects_unknown_fields_and_duplicate_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            source_index_path = dist / "source-index.json"
            source_index = json.loads(source_index_path.read_text(encoding="utf-8"))
            source_index["schema_version"] = "0.3"
            source_index["sources"][0]["unexpected"] = True
            source_index["sources"][0]["anchors"].append(source_index["sources"][0]["anchors"][0])
            source_index_path.write_text(json.dumps(source_index), encoding="utf-8")
            (dist / "package-index.json").unlink()

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})

    def test_package_index_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            package_index_path = dist / "package-index.json"
            package_index = json.loads(package_index_path.read_text(encoding="utf-8"))
            package_index["trusted"] = True
            package_index_path.write_text(json.dumps(package_index), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})

    def test_deeply_nested_baseline_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            (dist / "manifest.snapshot.json").write_text("[]", encoding="utf-8")
            manifest = load_manifest(manifest_path)

            with mock.patch("evidence_office.storage.json.loads", side_effect=RecursionError("too deep")):
                result = audit_package(manifest, workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})

    def test_malformed_manifest_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            snapshot = json.loads((dist / "manifest.snapshot.json").read_text(encoding="utf-8"))
            snapshot["claims"].append(42)
            (dist / "manifest.snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})

    def test_unknown_source_index_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            source_index = json.loads((dist / "source-index.json").read_text(encoding="utf-8"))
            source_index["schema_version"] = "999"
            (dist / "source-index.json").write_text(json.dumps(source_index), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})

    def test_invalid_unicode_in_source_baseline_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            source_index = json.loads((dist / "source-index.json").read_text(encoding="utf-8"))
            source_index["sources"][0]["path"] = "bad\ud800path"
            (dist / "source-index.json").write_text(json.dumps(source_index), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("AUDIT_BASELINE_INVALID", {issue.code for issue in result.errors})

    def test_removed_source_is_reported_as_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            (workspace / "sources" / "results.csv").unlink()

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("SOURCE_MISSING_FROM_CURRENT", {issue.code for issue in result.errors})

    def test_new_declared_source_requires_a_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            extra = workspace / "sources" / "notes.txt"
            extra.write_text("new source\n", encoding="utf-8")
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw["sources"].append({"path": "sources/notes.txt"})
            manifest_path.write_text(json.dumps(raw), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("SOURCE_NOT_IN_BASELINE", {issue.code for issue in result.errors})

    def test_manifest_change_invalidates_the_built_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, manifest_path, dist = self._built_workspace(directory)
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw["claims"][0]["statement"] = "Efficiency is now described as 0.92."
            manifest_path.write_text(json.dumps(raw), encoding="utf-8")

            result = audit_package(load_manifest(manifest_path), workspace, dist)

            self.assertEqual(result.status, "failed")
            self.assertIn("MANIFEST_DRIFTED", {issue.code for issue in result.errors})


if __name__ == "__main__":
    unittest.main()
