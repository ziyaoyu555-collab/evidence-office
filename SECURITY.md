# Security policy

Evidence Office reads files selected by the caller and writes reports to a caller-selected output directory. It does not upload files or execute Office, MATLAB, Simulink, SolidWorks, or arbitrary code.

Please do not report real credentials or private source files in a public issue. For a security concern, contact the repository maintainer privately before publishing details.

Known design protections include:

- source paths are normalized, resolved, and checked against the selected root;
- malformed paths, including embedded NUL bytes, fail closed instead of reaching filesystem calls;
- invalid Unicode and recursively nested JSON are rejected before report rendering;
- malformed or unknown manifest fields are rejected instead of being silently discarded;
- missing or malformed declared evidence fails validation even when no claim cites it;
- verified claims require a precise anchor that exists in the indexed source;
- the build snapshots the canonical manifest object that validation actually accepted;
- audit baselines use an allowlisted schema and reject malformed or duplicate entries;
- HTML and Markdown reports escape caller-controlled claim text, paths, and anchors;
- demo generation refuses to overwrite a nonempty directory;
- the core has no network client or model-provider dependency.
