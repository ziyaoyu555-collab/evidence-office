# Changelog

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
