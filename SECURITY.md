# Security policy

Evidence Office reads files selected by the caller and writes reports to a caller-selected output directory. It does not upload files or execute Office, MATLAB, Simulink, SolidWorks, or arbitrary code.

Please do not report real credentials or private source files in a public issue. For a security concern, contact the repository maintainer privately before publishing details.

Known design protections include:

- source paths are checked against the selected root;
- missing and malformed evidence does not become verified evidence;
- reports HTML-escape claim text and paths;
- the core has no network client or model-provider dependency.

