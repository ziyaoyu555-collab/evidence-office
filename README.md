# Evidence Office

Evidence Office is a local-first, dependency-free validation layer for engineering and research deliverables.

It answers a question that ordinary AI document tools usually leave implicit:

> Which source supports this claim, can the source be found, and can another person audit the exact location?

This project does not pretend to replace a domain expert. It creates a deterministic evidence manifest, indexes declared CSV/JSON/text, read-only DOCX/DOCM/XLSX/XLSM/PPTX/PPTM sources, and static SLX model structure, checks claim-to-source links, and writes machine-readable and human-readable review reports.

The report includes a claim ledger, so a reviewer can read every statement, its
claim note, and its exact evidence references and reference notes without
reopening the manifest.

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
For safety, `demo` and `init` refuse to overwrite a nonempty directory; choose a
new output path when rerunning them.

Run the test suite without third-party test dependencies:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Real project workflow

For a real engineering or research package, use the built-in lifecycle instead of starting from a hand-written folder:

```bash
evidence-office init \
  --out ./energy-review \
  --project "Energy control review" \
  --description "Evidence package for a course or engineering review"

# Put source files in energy-review/sources/ or another path below the workspace.
evidence-office intake \
  ./energy-review/manifest.json \
  --root ./energy-review \
  sources/results.csv sources/report.docx sources/deck.pptx

# Add a verified claim without manually editing JSON.
evidence-office claim add \
  ./energy-review/manifest.json \
  --root ./energy-review \
  --id C-001 \
  --statement "Efficiency is 0.91." \
  --status verified \
  --source sources/results.csv \
  --anchor row:1/field:value

# Check the manifest.
evidence-office validate ./energy-review/manifest.json

# Produce the review packet.
evidence-office build \
  ./energy-review/manifest.json \
  --out ./energy-review/dist
```

The build atomically commits six useful outputs:

- `evidence-report.json` for CI or downstream tools;
- `evidence-report.html` for a human review page;
- `evidence-map.md` for a portable Markdown review packet;
- `source-index.json` for source fingerprints and available anchors;
- `manifest.snapshot.json` for the exact canonical manifest accepted by the build;
- `package-index.json` for SHA-256 checksums of the other five generated files.

All six files are staged before replacement. If staging or commit fails, the
previous generated set is restored instead of leaving a mixed old/new package.

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

The manifest schema is intentionally strict: array entries must be objects and
unknown fields are rejected instead of being silently discarded during a
workflow command.

Common anchors:

| Source | Anchor examples |
| --- | --- |
| CSV | `row:1`, `row:1/field:value` |
| XLSX/XLSM | `sheet:Results/cell:B2`, `sheet:Results/row:2`, `sheet:Results/cell:B2/value:91` |
| DOCX | `paragraph:3`, `table:1/row:2/cell:1` |
| PPTX | `slide:4`, `slide:4/text` (presentation order, including after slide reordering) |
| JSON | `key:metrics`, `item:2`, `json:/metrics/efficiency`, `json:/runs/0/id` |
| Markdown/text | `line:12` |
| SLX | `system:Controler`, `block:562`, `block:562/type:SubSystem`, `block-path:Controler/Energy%20Management%20Strategy` |

Macro-enabled Office files are parsed as ZIP/XML data only. Evidence Office
does not execute VBA, formulas, embedded objects, links, or application code.

SLX packages are also read as bounded ZIP/XML data. The index exposes system,
block SID, block type, and percent-encoded block-path anchors, plus block counts
and the recorded Simulink release. Reports label these sources `static-only` and
`runtime_validated: false`: the model is never loaded, compiled, or simulated.

For a `verified` claim, a generic file-level anchor such as `file` is intentionally rejected. It proves only that a file exists, not where the claim is supported.

JSON also supports escaped JSON Pointer-style anchors. Use `~0` for `~` and
`~1` for `/` inside an object key, for example `json:/metrics/a~1b`.

## Commands

```bash
# Human-readable validation; exit code 1 means blocking errors.
evidence-office validate manifest.json --format text

# Strict validation; warnings also produce exit code 1 for CI gates.
evidence-office validate manifest.json --strict

# Machine-readable validation for CI.
evidence-office validate manifest.json --format json --out validation.json

# Standalone HTML report and JSON report package.
evidence-office build manifest.json --out dist/

# Strict build; still writes the report package, but fails on warnings.
evidence-office build manifest.json --out dist/ --strict

# Check that sources and manifest semantics have not changed since the package was built.
evidence-office audit manifest.json --package dist/

# Inspect the anchors available in one source.
evidence-office inspect results.csv --root .

# Keep a large model inventory readable.
evidence-office inspect model.slx --root . --anchor-prefix block-path: --limit 50
```

`inspect` includes an explicit `status`, total/matched anchor counts, and a
truncation flag. `--anchor-prefix` is repeatable. It returns exit code `1` when
parsing is unavailable or the file changes during indexing, so it can be used
as a preflight gate rather than silently printing only file-level anchors.

Exit codes:

- `0`: passed or passed with warnings;
- `1`: validation completed and found blocking errors, or `--strict` found review warnings;
- `2`: the command itself could not read or parse the requested input.

`audit` returns exit code `1` when a source fingerprint differs from the
package baseline, when a previously packaged source is missing, when a new
declared source was added after the build, or when the manifest's canonical
content changed. It also verifies every generated file against
`package-index.json`, detecting missing or modified reports. Formatting-only
manifest JSON changes do not create false drift. An
audit failure is a delivery gate for a stale package, not a program crash. The
command also preserves validation warnings; add `--strict` when those warnings
must block delivery.

## Safety and honest limits

Evidence Office validates the evidence links that are declared in the manifest. It does not prove that a simulation is scientifically correct, that an experiment was performed correctly, or that an engineering conclusion is safe. A green report means that this version's deterministic checks passed.

Input parsing is fail-closed and resource-bounded: JSON and text-like sources
are limited to 64 MiB, Office XML to 64 MiB per member and 256 MiB in total,
ZIP/XML archives to 10,000 entries, each source to 250,000 anchors, and each
anchor to 4,096 characters. Split a larger source or add a purpose-built
adapter rather than weakening these limits. JSON duplicate keys, NaN/Infinity,
numeric overflow, invalid Unicode, ambiguous CSV headers/rows, duplicate ZIP
members/relationships, XML DTDs, and incomplete package relationships are
rejected.

The package checksum inventory detects accidental or uncoordinated changes; it
is not a digital signature. A party able to replace both a report and
`package-index.json` can recompute the checksums. Signed manifests remain a
separate roadmap item.

The current package does not execute MATLAB, Simulink, SolidWorks, PowerPoint,
WPS, or Windows-only workflows. MathWorks documents SLX as a compressed OPC
package while warning that its internal content can change; unsupported future
layouts therefore fail closed instead of being guessed. Do not describe a
static file scan as dynamic runtime acceptance. See the official
[SLX format guidance](https://www.mathworks.com/help/simulink/ug/save-models.html).

## Architecture

```text
manifest.json
        ↓
model.py         →  canonical manifest + derived report state
        ↓
declared files
        ↓
source_index.py  →  immutable fingerprints, Office anchors, and static SLX inventory
        ↓
validator.py     →  blocking errors and visible warnings
        ↓
report.py        →  JSON + standalone HTML
        ↓
audit.py         →  post-build source drift gate
        ↓
CI / review / downstream Office compiler

storage.py       →  strict JSON + atomic persistence shared by the workflow
```

The core deliberately has no LLM dependency. `ProjectManifest.to_mapping()` is
the single serialization boundary, and report status/exit behavior is derived
instead of stored in parallel fields. AI-assisted manifest authoring can be
added later, but the evidence gate must remain deterministic and
model-independent.

GitHub Actions compiles, builds, installs, and tests the wheel on Linux with
Python 3.10, 3.12, and 3.14, plus Python 3.12 on Windows. It then runs the
installed console command through a complete demo → build → audit workflow, so
the CI path does not depend on `PYTHONPATH`. Synthetic OPC fixtures exercise
SLX success and fail-closed paths without redistributing private model files.

## Roadmap

1. Add merged-cell and named-range metadata for XLSX/XLSM.
2. Add a normalized claim/evidence export for PPT Master and DOCX generators.
3. Extend static model inventory to explicit model-reference and Stateflow anchors.
4. Add render/readback adapters only when the target runtime is actually available in CI or on a declared acceptance machine.
5. Add signed evidence manifests after the schema is stable.

## Contributing

Please read [AGENTS.md](AGENTS.md) before changing validation rules. New behaviour needs a public-interface test and must preserve the fail-closed rules. See [CONTRIBUTING.md](CONTRIBUTING.md).
