# Evidence Office project rules

These rules are release gates, not suggestions.

1. Never label a claim `verified` without a declared source and a precise anchor.
2. Missing sources, undeclared sources, unsafe paths, duplicate identifiers, invalid anchors, and invalid statuses are blocking errors.
3. `unverified` and `assumption` are allowed only when the report keeps them visible as warnings.
4. Synthetic examples must say that they are synthetic and must never be presented as real simulation or field data.
5. The deterministic core must work without an API key, network access, or a model provider.
6. New parsers must fail closed: malformed input produces a readable validation result or a concise CLI error, never fabricated evidence.
7. A release is not complete until the full standard-library test suite, CLI smoke tests, and example build pass.
8. Do not claim PowerPoint, MATLAB, Simulink, SolidWorks, WPS, or Windows runtime acceptance unless that runtime was actually tested.
9. A final delivery archive is a separate acceptance boundary: locate every configured report/program/result artifact inside the actual archive, require an unambiguous match, compare its bytes with the validated source artifact, and block delivery on drift or ambiguity.

The project uses deep modules with small public interfaces. Prefer adding behaviour behind `validate_manifest`, `index_file`, and the CLI over exposing parser internals.
