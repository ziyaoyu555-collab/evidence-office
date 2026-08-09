# Evidence Office

Evidence Office is a local-first, dependency-free validation layer for engineering and research Office deliverables.

It answers a question that ordinary AI document tools usually leave implicit:

> Which source supports this claim, can the source be found, and can another person audit the exact location?

The first release does not pretend to replace a domain expert. It creates a deterministic evidence manifest, indexes declared CSV/JSON/text/DOCX/XLSX/PPTX sources, checks claim-to-source links, and writes both a machine-readable JSON report and a standalone HTML report.

The report includes a claim ledger, so a reviewer can read every statement and its exact evidence references without reopening the manifest.

## Why this exists

Generic AI presentation generation is already crowded. Evidence Office focuses on the harder and more useful layer between engineering material and final delivery:

- claim → source → anchor traceability;
- blocking errors for missing or invalid evidence;
- explicit warnings for assumptions and unverified statements;
- SHA-256 fingerprints for the indexed inputs;
- no API key, network, or model provider required;
- reports that can be attached to a review, assignment, or release.

## Quick start

Python 3.10+ is the only runtime requirement.

```bash
cd evidence-office
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

evidence-office demo --out /tmp/evidence-office-demo
evidence-office build \
  /tmp/evidence-office-demo/manifest.json \
  --out /tmp/evidence-office-demo/dist
open /tmp/evidence-office-demo/dist/evidence-report.html
```

The demo intentionally contains synthetic values. Its assumption is visible as a warning; it is not a real vehicle or MATLAB/Simulink result.

Run the test suite without third-party test dependencies:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Manifest format

```json
{
  "project": "Energy control evidence package",
  "description": "What this package is for.",
  "sources": [
    {"path": "results.csv", "label": "Experiment results"}
  ],
  "claims": [
    {
      "id": "C-001",
      "statement": "The second run has a tracking error of 0.16 m.",
      "status": "verified",
      "sources": [
        {"path": "results.csv", "anchor": "row:2/field:tracking_error_m"}
      ]
    },
    {
      "id": "A-001",
      "statement": "This result may generalize to a future field test.",
      "status": "assumption",
      "sources": [{"path": "results.csv", "anchor": "file"}],
      "note": "Review before using this statement as a conclusion."
    }
  ]
}
```

Allowed claim statuses:

- `verified`: must have a declared source and a precise, existing anchor;
- `unverified`: allowed, but always reported as a warning;
- `assumption`: allowed, but always reported as a warning.

Common anchors:

| Source | Anchor examples |
| --- | --- |
| CSV | `row:1`, `row:1/field:value` |
| XLSX | `sheet:Results/cell:B2`, `sheet:Results/row:2` |
| DOCX | `paragraph:3`, `table:1/row:2/cell:1` |
| PPTX | `slide:4`, `slide:4/text` |
| JSON | `key:metrics`, `item:2` |
| Markdown/text | `line:12` |

For a `verified` claim, a generic file-level anchor such as `file` is intentionally rejected. It proves only that a file exists, not where the claim is supported.

## Commands

```bash
# Human-readable validation; exit code 1 means blocking errors.
evidence-office validate manifest.json --format text

# Machine-readable validation for CI.
evidence-office validate manifest.json --format json --out validation.json

# Standalone HTML report and JSON report package.
evidence-office build manifest.json --out dist/

# Inspect the anchors available in one source.
evidence-office inspect results.csv --root .
```

Exit codes:

- `0`: passed or passed with warnings;
- `1`: validation completed and found blocking errors;
- `2`: the command itself could not read or parse the requested input.

## Safety and honest limits

Evidence Office validates the evidence links that are declared in the manifest. It does not prove that a simulation is scientifically correct, that an experiment was performed correctly, or that an engineering conclusion is safe. A green report means that this version's deterministic checks passed.

The current package does not execute MATLAB, Simulink, SolidWorks, PowerPoint, WPS, or Windows-only workflows. Do not describe a static file scan as dynamic runtime acceptance. Those adapters belong to later releases with real target-runtime fixtures.

## Architecture

```text
manifest.json + declared files
        ↓
source_index.py  →  immutable fingerprints and anchors
        ↓
validator.py     →  blocking errors and visible warnings
        ↓
report.py        →  JSON + standalone HTML
        ↓
CI / review / downstream Office compiler
```

The core deliberately has no LLM dependency. AI-assisted manifest authoring can be added later, but the evidence gate must remain deterministic and model-independent.

## Roadmap

1. Add richer XLSX values and merged-cell metadata.
2. Add a normalized claim/evidence export for PPT Master and DOCX generators.
3. Add read-only `.slx` model inventory and explicit “static-only” labels.
4. Add render/readback adapters only when the target runtime is actually available in CI or on a declared acceptance machine.
5. Add signed evidence manifests after the schema is stable.

## Contributing

Please read [AGENTS.md](AGENTS.md) before changing validation rules. New behaviour needs a public-interface test and must preserve the fail-closed rules. See [CONTRIBUTING.md](CONTRIBUTING.md).
