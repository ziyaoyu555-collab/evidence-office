# Contributing

Thank you for helping make engineering deliverables easier to audit.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The core intentionally uses the Python standard library. Do not add a runtime dependency just to make a parser convenient; explain the tradeoff and add a fixture first.

## Pull requests

- Describe the user-visible behaviour.
- Add a test through the public CLI or public module function.
- Include malformed-input behaviour where relevant.
- Keep verified, unverified, and assumption semantics explicit.
- Do not include private course files, credentials, API keys, or real personal data in fixtures.
- Do not claim target-runtime acceptance without running that target runtime.

