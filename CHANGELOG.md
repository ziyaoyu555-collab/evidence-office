# Changelog

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
