# Contributing to axor-cli

## Setup

```bash
git clone https://github.com/your-org/axor-cli
cd axor-cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[claude,dev]"
```

## Running tests

```bash
pytest tests/unit/          # no API key needed
```

## Architecture

axor-cli is a thin shell around axor-core + adapters:

- `auth.py`     — key management only, no business logic
- `adapters.py` — lazy imports, delegates to adapter's make_session()
- `display.py`  — terminal output only, no execution logic
- `streaming.py` — connects GovernedSession to terminal display
- `main.py`     — REPL + argument parsing

**No governance logic in CLI.** Policy, context, capabilities — all in axor-core.

## Adding an adapter

1. Add entry to `_REGISTRY` in `adapters.py`
2. Add env var to `_ENV_VARS` in `auth.py`
3. Adapter package must expose `make_session(**kwargs) -> GovernedSession`

## Pull request checklist

- [ ] `pytest tests/unit/` passes
- [ ] No governance logic added to CLI
- [ ] New adapter registered in both `adapters.py` and `auth.py`
