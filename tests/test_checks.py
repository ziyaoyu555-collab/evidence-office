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


if __name__ == "__main__":
    unittest.main()
