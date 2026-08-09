import csv
import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from evidence_office.cli import main


class CliBehaviourTests(unittest.TestCase):
    def test_version_flag_is_available(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("evidence-office 0.3.0", stdout.getvalue())

    def test_build_writes_machine_and_human_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "results.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
                writer.writeheader()
                writer.writerow({"metric": "efficiency", "value": "0.91"})
            (root / "manifest.json").write_text(json.dumps({
                "project": "Build demo",
                "sources": [{"path": "results.csv"}],
                "claims": [{
                    "id": "C-001",
                    "statement": "Efficiency is 0.91.",
                    "status": "verified",
                    "sources": [{"path": "results.csv", "anchor": "row:1/field:value"}],
                }],
            }), encoding="utf-8")
            out_dir = root / "dist"

            exit_code = main(["build", str(root / "manifest.json"), "--out", str(out_dir)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((out_dir / "evidence-report.json").is_file())
            self.assertTrue((out_dir / "evidence-report.html").is_file())
            report = json.loads((out_dir / "evidence-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed")

    def test_cli_runs_init_intake_and_build_as_one_real_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "package"
            self.assertEqual(main(["init", "--out", str(workspace), "--project", "CLI workflow"]), 0)
            source = workspace / "sources" / "results.csv"
            source.write_text("metric,value\nefficiency,0.91\n", encoding="utf-8")
            manifest_path = workspace / "manifest.json"
            self.assertEqual(main(["intake", str(manifest_path), "--root", str(workspace), "sources/results.csv"]), 0)
            self.assertEqual(main([
                "claim", "add", str(manifest_path),
                "--id", "C-001",
                "--statement", "Efficiency is 0.91.",
                "--status", "verified",
                "--source", "sources/results.csv",
                "--anchor", "row:1/field:value",
                "--root", str(workspace),
            ]), 0)

            out_dir = workspace / "dist"
            self.assertEqual(main(["build", str(manifest_path), "--out", str(out_dir)]), 0)
            self.assertIn("C-001", (out_dir / "evidence-map.md").read_text(encoding="utf-8"))
            self.assertTrue((out_dir / "source-index.json").is_file())

    def test_demo_is_explicitly_synthetic_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out_dir = Path(directory) / "demo"
            self.assertEqual(main(["demo", "--out", str(out_dir)]), 0)
            manifest = out_dir / "manifest.json"
            self.assertTrue(manifest.is_file())
            dist_dir = out_dir / "dist"
            self.assertEqual(main(["build", str(manifest), "--out", str(dist_dir)]), 0)
            self.assertIn("synthetic", manifest.read_text(encoding="utf-8").lower())
            report = json.loads((dist_dir / "evidence-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed_with_warnings")
            self.assertGreaterEqual(report["summary"]["warnings"], 1)

    def test_malformed_manifest_returns_a_concise_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "broken.json"
            manifest.write_text("{not-json", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["validate", str(manifest)])

            self.assertEqual(exit_code, 2)
            self.assertIn("error:", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
