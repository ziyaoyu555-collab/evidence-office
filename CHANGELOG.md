# Changelog

## 0.9.0 — 2026-08-14

- add manifest-configured submission archive identity and structure checks, including SHA-256, ZIP CRC integrity, required members, and optional single-root validation;
- add generic content gates for required or forbidden regex patterns across declared reports, code, notebooks, and other text-readable evidence;
- add generic cross-artifact consistency probes that extract one value per source and compare it with an optional project baseline and tolerance;
- index Python and Jupyter Notebook sources as first-class evidence instead of treating them as file-only attachments;
- add explicit runtime boundary checks so static inspection cannot be reported as dynamic execution, with configurable warning or blocking severity;
- preserve v0.8 source/package audit compatibility and the existing manifest workflow when no new checks are configured;
- add regression coverage for archive identity, content failures, Notebook indexing, cross-file mismatch, and unverified runtime boundaries.

## 0.8.0 — 2026-08-09

- add bounded, read-only SLX package indexing with system, block SID, block type, and percent-encoded block-path anchors;
- expose model release, UUID, system count, block count, and block-type inventory while marking every SLX source `static-only` and `runtime_validated: false`;
- add repeatable `inspect --anchor-prefix` filtering, `--limit`, total/matched counts, and explicit truncation status for large source inventories;
- re-hash every source after anchor extraction so same-size edits with restored timestamps cannot be accepted as one immutable snapshot;
- cap each evidence anchor at 4,096 characters across source indexers to prevent one hostile field, key, sheet, or block name from amplifying report size;
- show analysis mode in text, Markdown, and HTML source inventories;
- preserve full v0.7 checksum-package audit compatibility after advancing the current package schema to 0.8;
- add a pinned Ruff quality gate so every pull request rejects lint and static-analysis regressions;
- expand the regression suite from 90 to 98 tests and add a deterministic 1,000-case malformed-SLX stress run plus real R2021a model verification.

## 0.7.0 — 2026-08-09

- reject ambiguous or nonstandard JSON, including duplicate keys, NaN/Infinity, overflowing exponents, invalid Unicode, and oversized documents;
- bound text and Office indexing by bytes, archive entries, XML size, and anchor count; reject XML DTDs/entities, duplicate ZIP members/relationships, incomplete PPTX metadata, and ambiguous XLSX sheets/cells;
- detect source files changed between hashing and anchor extraction instead of combining two versions into one snapshot;
- add read-only DOCM, XLSM, and PPTM indexing plus precise XLSX numeric, shared-string, and inline-string value anchors;
- protect manifests, declared sources, and audit baselines from CLI output collisions;
- stage and atomically commit all generated files with rollback on failures and platform-stable newlines;
- add `package-index.json` and audit generated-file checksums as well as source/manifest drift;
- make `inspect` fail visibly on unavailable parsing and neutralize terminal and bidirectional controls in human output;
- expand the regression suite from 57 to 90 tests, run adversarial JSON/Office/package mutation checks, and add a Windows 3.12 CI workflow alongside Linux 3.10/3.12/3.14.

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
