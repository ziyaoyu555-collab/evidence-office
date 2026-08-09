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

Before release, build and install the wheel in a clean environment and run the
installed `evidence-office` command. CI repeats that check on Python 3.10, 3.12,
and 3.14, then exercises demo → build → audit without relying on `PYTHONPATH`.

## Pull requests

- Describe the user-visible behaviour.
- Add a test through the public CLI or public module function.
- Include malformed-input behaviour where relevant.
- Keep verified, unverified, and assumption semantics explicit.
- Do not include private course files, credentials, API keys, or real personal data in fixtures.
- Do not claim target-runtime acceptance without running that target runtime.
