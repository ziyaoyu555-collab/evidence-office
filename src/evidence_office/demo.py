"""Create a small synthetic example that never pretends to be a real experiment."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def create_demo(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "simulation_results.csv"
    with data_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run", "tracking_error_m", "energy_kwh"])
        writer.writeheader()
        writer.writerows([
            {"run": "synthetic-01", "tracking_error_m": "0.18", "energy_kwh": "2.41"},
            {"run": "synthetic-02", "tracking_error_m": "0.16", "energy_kwh": "2.37"},
        ])
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps({
        "project": "Synthetic energy-control evidence demo",
        "description": "A reproducible example using synthetic values. It is not a claim about a real vehicle or simulation.",
        "sources": [{"path": data_path.name, "label": "Synthetic result table"}],
        "claims": [
            {
                "id": "C-001",
                "statement": "The synthetic-02 run has a tracking error of 0.16 m.",
                "status": "verified",
                "sources": [{"path": data_path.name, "anchor": "row:2/field:tracking_error_m"}],
            },
            {
                "id": "A-001",
                "statement": "The controller may be suitable for a future real-vehicle test.",
                "status": "assumption",
                "sources": [{"path": data_path.name, "anchor": "file"}],
                "note": "This must not be reported as a validated dynamic result.",
            },
        ],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path

