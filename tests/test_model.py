import unittest

from evidence_office.model import ProjectManifest


class ModelTests(unittest.TestCase):
    def test_manifest_exposes_a_small_public_model(self) -> None:
        manifest = ProjectManifest.from_mapping(
            {
                "project": "Demo",
                "description": "A deterministic evidence package.",
                "sources": [{"path": "results.csv", "label": "Results"}],
                "claims": [
                    {
                        "id": "C-001",
                        "statement": "The result is reproducible.",
                        "status": "verified",
                        "sources": [{"path": "results.csv", "anchor": "row:2"}],
                    }
                ],
            }
        )

        self.assertEqual(manifest.project, "Demo")
        self.assertEqual(manifest.sources[0].path, "results.csv")
        self.assertEqual(manifest.claims[0].sources[0].anchor, "row:2")
