"""Create a small synthetic example that never pretends to be a real experiment."""

from __future__ import annotations

import csv
from pathlib import Path

from .workflow import add_claim, create_workspace


def create_demo(out_dir: Path) -> Path:
    manifest_path = create_workspace(
        out_dir,
        "Synthetic energy-control evidence demo",
        "A reproducible example using synthetic values. It is not a claim about a real vehicle or simulation.",
    )
    workspace = manifest_path.parent
    data_path = workspace / "sources" / "simulation_results.csv"
    with data_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run", "tracking_error_m", "energy_kwh"])
        writer.writeheader()
        writer.writerows([
            {"run": "synthetic-01", "tracking_error_m": "0.18", "energy_kwh": "2.41"},
            {"run": "synthetic-02", "tracking_error_m": "0.16", "energy_kwh": "2.37"},
        ])
    source = "sources/simulation_results.csv"
    add_claim(
        manifest_path,
        workspace,
        claim_id="C-001",
        statement="The synthetic-02 run has a tracking error of 0.16 m.",
        status="verified",
        source_path=source,
        anchor="row:2/field:tracking_error_m",
    )
    add_claim(
        manifest_path,
        workspace,
        claim_id="A-001",
        statement="The controller may be suitable for a future real-vehicle test.",
        status="assumption",
        source_path=source,
        anchor="file",
        note="This must not be reported as a validated dynamic result.",
    )
    return manifest_path
