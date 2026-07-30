# Contributing to Cyberdeck

Cyberdeck welcomes focused fixes, tests, documentation, and provider-neutral
improvements. Discuss large provider or architecture changes in an issue first.

## Development setup

Cyberdeck requires Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check .
```

The application lives in `src/cyberdeck`. Provider transports are isolated in
`src/cyberdeck/providers`; shared UI and manager code must use negotiated
capabilities instead of provider-name conditionals. Tests use fake local
transports and must not require credentials.

## Pull requests

Keep changes bounded, add regression coverage, run the full test and Ruff
suites, and update user-facing documentation when behavior changes. Never
commit credentials, raw private transcripts, or unsanitized provider logs.
Experimental protocol reports should include the CLI version, operating system,
sanitized request/response shape, expected behavior, and recovery behavior.

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
