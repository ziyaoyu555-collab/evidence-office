# Changelog

## 0.6.0 — 2026-08-09

- refactor manifest serialization, report state, exit handling, and CLI rendering behind smaller shared interfaces;
- audit both source fingerprints and the canonical manifest snapshot, while ignoring formatting-only JSON changes;
- write the validated in-memory manifest into packages so a concurrent disk change cannot corrupt the accepted snapshot;
- normalize equivalent current and legacy-baseline paths and fail closed on null fields, unknown fields, invalid Unicode, invalid paths, malformed manifest entries, unreadable or malformed declared sources, missing XLSX parts, and unsupported audit schemas;
- preserve nonempty demo directories and reject blank projects before creating a workspace;
- resolve PPTX anchors by actual presentation order, suppress nonexistent text anchors for blank slides, and expose claim/evidence notes in every human report;
- harden Markdown/HTML escaping and return concise CLI errors for recursive JSON and generic filesystem failures;
- test built wheels, installed console commands, and the full workflow on Python 3.10, 3.12, and 3.14;
- expand the regression suite from 26 to 57 tests, plus a 3,000-case adversarial run and a 5,000-claim stress run.

## 0.5.0 — 2026-08-09

- add `audit` to detect source files changed, removed, or added after a package was built;
- validate the stored source-index baseline before comparing it with current files;
- expose drift-audit reports in text, JSON, and HTML CLI formats;
- run drift auditing in GitHub Actions after the synthetic package build;
- expand the regression suite from 22 to 26 tests.

## 0.4.0 — 2026-08-09

- fix `init` and `demo` crashes when the output path is an existing file;
- prevent source indexing from reading paths that resolve outside the selected root;
- add nested JSON Pointer-style anchors such as `json:/metrics/efficiency`;
- add `--strict` to `validate` and `build` so review warnings can fail CI;
- make report HTML read its displayed package version from the runtime;
- expand the regression suite from 18 to 22 tests.

## 0.3.0 — 2026-08-09

- add `init` to create a ready-to-use review workspace;
- add `intake` to register existing source files without destroying claims;
- add a portable Markdown evidence map and standalone source index to every build;
- add a CLI integration test for the complete init → intake → build flow.

## 0.2.0 — 2026-08-09

- add a claim ledger to JSON, text, and HTML reports;
- expose every claim's statement, status, and evidence references in generated reports;
- reject generic file-level anchors for `verified` claims;
- add `evidence-office --version`;
- expand regression coverage to 13 standard-library tests.

## 0.1.0 — 2026-08-09

Initial public alpha:

- deterministic manifest model;
- CSV, JSON, text, DOCX, XLSX, and PPTX source indexing;
- claim/source/anchor validation;
- blocking errors for broken evidence and visible warnings for uncertainty;
- JSON and standalone HTML reports;
- synthetic demo and standard-library test suite;
- no API key, network access, or model provider required.
