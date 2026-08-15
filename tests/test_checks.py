import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from evidence_office.model import ProjectManifest
from evidence_office.validator import validate_manifest


class ReviewCheckTests(unittest.TestCase):
    def _manifest(self, root: Path, raw: dict) -> ProjectManifest:
        path = root / "manifest.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        from evidence_office.validator import load_manifest

        return load_manifest(path)

    def test_content_and_consistency_checks_block_a_stale_notebook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "code.py").write_text("mass_kg = 1580\n", encoding="utf-8")
            (root / "report.md").write_text("Full mass: 18000 kg\n", encoding="utf-8")
            notebook = {"cells": [{"cell_type": "code", "source": ["mass_kg = 1580\n"]}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
            (root / "model.ipynb").write_text(json.dumps(notebook), encoding="utf-8")
            (root / "results.txt").write_text("Need revise: bearing life is too low\n", encoding="utf-8")
            manifest = self._manifest(root, {
                "project": "generic regression",
                "description": "notebook mismatch",
                "sources": [{"path": name} for name in ("code.py", "report.md", "model.ipynb", "results.txt")],
                "claims": [],
                "checks": {
                    "content": [{
                        "id": "no-failure-output",
                        "sources": ["results.txt"],
                        "patterns": ["Need revise", "bearing life"],
                        "mode": "none",
                    }],
                    "consistency": [{
                        "id": "full-mass",
                        "expected": 18000,
                        "values": [
                            {"path": "code.py", "pattern": r"mass_kg\s*=\s*(\d+(?:\.\d+)?)"},
                            {"path": "report.md", "pattern": r"Full mass:\s*(\d+(?:\.\d+)?)"},
                            {"path": "model.ipynb", "pattern": r"mass_kg\s*=\s*(\d+(?:\.\d+)?)"},
                        ],
                    }],
                },
            })

            report = validate_manifest(manifest, root)
            codes = {issue.code for issue in report.errors}
            self.assertIn("CONTENT_FORBIDDEN_MATCH", codes)
            self.assertIn("CONSISTENCY_MISMATCH", codes)

    def test_notebook_is_indexed_and_runtime_boundary_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notebook = {"cells": [{"cell_type": "code", "source": ["answer = 42\n"]}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
            (root / "model.ipynb").write_text(json.dumps(notebook), encoding="utf-8")
            manifest = self._manifest(root, {
                "project": "notebook review",
                "description": "static boundary",
                "sources": [{"path": "model.ipynb"}],
                "claims": [],
                "checks": {"runtime": [{
                    "id": "python-runtime",
                    "sources": ["model.ipynb"],
                    "status": "not_verified",
                    "note": "Notebook source was indexed but not executed.",
                }]},
            })

            report = validate_manifest(manifest, root)
            self.assertEqual(report.sources[0].kind, "ipynb")
            self.assertEqual(report.sources[0].metadata["top_level"], "object")
            self.assertIn("RUNTIME_NOT_VERIFIED", {issue.code for issue in report.warnings})

    def test_submission_hash_and_required_member_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "submission.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("submission/README.md", "review package")
                archive.writestr("submission/code.py", "answer = 42")
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            manifest = self._manifest(root, {
                "project": "archive review",
                "description": "archive identity",
                "sources": [{"path": "submission.zip"}],
                "claims": [],
                "submission": {
                    "path": "submission.zip",
                    "sha256": digest,
                    "required_members": ["submission/code.py"],
                    "single_root": True,
                },
            })

            report = validate_manifest(manifest, root)
            self.assertNotIn("SUBMISSION_SHA256_MISMATCH", {issue.code for issue in report.errors})
            self.assertNotIn("SUBMISSION_MEMBER_MISSING", {issue.code for issue in report.errors})
            self.assertNotIn("SUBMISSION_ROOT_AMBIGUOUS", {issue.code for issue in report.errors})

    def test_submission_path_traversal_member_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "unsafe.zip", "w") as archive:
                archive.writestr("../outside.txt", "must not be accepted")
            manifest = self._manifest(root, {
                "project": "unsafe archive",
                "description": "archive traversal regression",
                "sources": [{"path": "unsafe.zip"}],
                "claims": [],
                "submission": {"path": "unsafe.zip"},
            })

            report = validate_manifest(manifest, root)
            self.assertIn("SUBMISSION_UNSAFE_MEMBER", {issue.code for issue in report.errors})

    def test_final_artifacts_are_located_and_bound_to_validated_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "code.py").write_text("mass_kg = 18000\n", encoding="utf-8")
            (root / "report.md").write_text("Full mass: 18000 kg\n", encoding="utf-8")
            archive_path = root / "submission.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("final/code.py", (root / "code.py").read_bytes())
                archive.writestr("final/report.md", (root / "report.md").read_bytes())
            manifest = self._manifest(root, {
                "project": "final artifact locator",
                "description": "archive must contain the exact validated artifacts",
                "sources": [{"path": name} for name in ("submission.zip", "code.py", "report.md")],
                "claims": [],
                "submission": {
                    "path": "submission.zip",
                    "artifacts": [
                        {"id": "calculation", "source": "code.py", "member_pattern": r"^final/code\.py$"},
                        {"id": "report", "source": "report.md", "member_pattern": r"^final/report\.md$"},
                    ],
                },
            })

            report = validate_manifest(manifest, root)

            self.assertEqual(report.status, "passed_with_warnings")
            self.assertNotIn("SUBMISSION_ARTIFACT_MISSING", {issue.code for issue in report.errors})
            self.assertEqual(
                [(artifact.id, artifact.member, artifact.source) for artifact in report.delivery_artifacts],
                [
                    ("calculation", "final/code.py", "code.py"),
                    ("report", "final/report.md", "report.md"),
                ],
            )
            from evidence_office.report import report_to_dict

            payload = report_to_dict(report)
            self.assertEqual(
                [item["member"] for item in payload["delivery"]["final_artifacts"]],
                ["final/code.py", "final/report.md"],
            )

    def test_final_archive_with_a_stale_notebook_is_blocked_even_when_workspace_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "code.py").write_text("mass_kg = 18000\n", encoding="utf-8")
            (root / "report.md").write_text("Full mass: 18000 kg\n", encoding="utf-8")
            archive_path = root / "submission.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("final/code.py", "mass_kg = 1580\n")
                archive.writestr("final/report.md", (root / "report.md").read_bytes())
            manifest = self._manifest(root, {
                "project": "stale final artifact regression",
                "description": "the workspace was fixed but the final package was not",
                "sources": [{"path": name} for name in ("submission.zip", "code.py", "report.md")],
                "claims": [],
                "checks": {"consistency": [{
                    "id": "full-mass",
                    "expected": 18000,
                    "values": [
                        {"path": "code.py", "pattern": r"mass_kg\s*=\s*(\d+)"},
                        {"path": "report.md", "pattern": r"Full mass:\s*(\d+)"},
                    ],
                }]},
                "submission": {
                    "path": "submission.zip",
                    "artifacts": [
                        {"id": "calculation", "source": "code.py", "member_pattern": r"^final/code\.py$"},
                        {"id": "report", "source": "report.md", "member_pattern": r"^final/report\.md$"},
                    ],
                },
            })

            report = validate_manifest(manifest, root)

            self.assertIn("SUBMISSION_ARTIFACT_DRIFTED", {issue.code for issue in report.errors})
            self.assertEqual(report.status, "failed")

    def test_ambiguous_final_artifact_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.md").write_text("final report\n", encoding="utf-8")
            with zipfile.ZipFile(root / "submission.zip", "w") as archive:
                archive.writestr("final/report.md", "final report\n")
                archive.writestr("backup/report.md", "old report\n")
            manifest = self._manifest(root, {
                "project": "ambiguous final artifact",
                "description": "two report candidates must not be guessed",
                "sources": [{"path": name} for name in ("submission.zip", "report.md")],
                "claims": [],
                "submission": {
                    "path": "submission.zip",
                    "artifacts": [{
                        "id": "report",
                        "source": "report.md",
                        "member_pattern": r"report\.md$",
                    }],
                },
            })

            report = validate_manifest(manifest, root)

            self.assertIn("SUBMISSION_ARTIFACT_AMBIGUOUS", {issue.code for issue in report.errors})


if __name__ == "__main__":
    unittest.main()
