# axor-cli

[![CI](https://github.com/Bucha11/axor-cli/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Bucha11/axor-cli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/axor-cli?cacheSeconds=300)](https://pypi.org/project/axor-cli/)
[![Python](https://img.shields.io/pypi/pyversions/axor-cli?cacheSeconds=300)](https://pypi.org/project/axor-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)


**Governed agent sessions in your terminal.**

Run Claude (or other LLMs) under axor-core governance — controlled context, explicit tool permissions, token optimization, and full audit trail.

---

## Installation

```bash
# CLI + Claude adapter
pip install axor-cli[claude]

# or step by step
pip install axor-cli
pip install axor-claude
```

---

## Quick Start

```bash
# Interactive REPL
axor claude

# Single task and exit
axor claude "refactor the auth module"

# With options
axor claude --policy readonly "review this PR for security issues"
axor claude --limit 100000 "migrate the entire codebase to Go"
axor claude --model claude-opus-4-5 "design the new architecture"
```

---

## Authentication

On first run, axor asks for your API key and saves it to `~/.axor/config.toml` (permissions: 600):

```
$ axor claude

  No API key found for 'claude'.
  (checked: --api-key flag, ANTHROPIC_API_KEY env var, ~/.axor/config.toml)

  Anthropic API key (hidden): ****
  Save to ~/.axor/config.toml for future sessions? [Y/n]: y
  ✓ Key saved to ~/.axor/config.toml (permissions: 600)
```

Key priority (highest to lowest):

| Source | When used |
|--------|-----------|
| `--api-key` flag | One-off override, never saved |
| `ANTHROPIC_API_KEY` env var | CI/CD, containers |
| `~/.axor/config.toml` | Persistent, set via `/auth` |

Manage saved keys with `/auth` in the REPL:

```
> /auth              # set or update key (prompts, then saves)
> /auth --show       # show where key is loaded from (never shows the key)
> /auth --clear      # remove saved key
```

---

## Interactive REPL

```
$ axor claude
axor v0.1.0 │ adapter: claude │ model: claude-sonnet-4-5
Type a task, a /command, or 'exit' to quit.

> refactor the auth module to add rate limiting
  ↳ read(path='auth.py') → def authenticate(token):…
  ↳ write(path='auth.py') → …
✓ done │ policy: moderate_mutative │ tokens: 1,247 (in: 800 out: 447)

> /cost
  → Tokens spent this session: 1,247

> /compact
  → Context compaction requested — will apply on next execution.

> exit
  → Bye.
```

### REPL commands

| Command | Class | Description |
|---------|-------|-------------|
| `/auth` | built-in | Set or update API key |
| `/auth --clear` | built-in | Remove saved key |
| `/auth --show` | built-in | Show key source (never the key itself) |
| `/model` | built-in | List available models |
| `/help` | built-in | All commands |
| `/cost` | governed | Token usage for this session |
| `/policy` | governed | Last execution policy |
| `/compact` | governed | Compress context |
| `/status` | governed | Session overview |
| `/tools` | governed | Tools available to current policy |
| `exit` / `quit` / `^D` | — | Exit |

Governed commands (`/cost`, `/policy`, etc.) are handled by axor-core — they never reach the executor.

---

## CLI options

```
axor <adapter> [task] [options]

Arguments:
  adapter           Adapter: claude, openai
  task              Single task — runs and exits (skips REPL)

Options:
  -p, --policy      Preset: readonly, sandboxed, standard, federated
  -l, --limit       Soft token limit (budget optimization signals)
  -m, --model       Model override (e.g. claude-opus-4-5)
  --api-key         API key for this session (never saved)
  --tools           Tools to enable (default: read write bash search glob)
  --no-skills       Skip CLAUDE.md and .claude/skills/
  --no-plugins      Skip .claude/plugins/
  --list-adapters   Show installed adapters and exit
  --version         Show version
```

---

## Examples

```bash
# Analysis only — no writes, no bash
axor claude --policy readonly "find all security issues in auth.py"

# Specific tools only
axor claude --tools read search "find all TODO comments"

# Large migration with budget
axor claude --limit 200000 "rewrite the API layer to use async/await"

# Specific model
axor claude --model claude-opus-4-5 "design the new microservices architecture"

# No extension loading (faster startup)
axor claude --no-skills --no-plugins "quick question"

# CI — reads key from env, single task, exits
ANTHROPIC_API_KEY=sk-ant-... axor claude "run code review"
```

---

## Adapters

```bash
axor --list-adapters

Available adapters:
  claude       installed
  openai       not installed  →  pip install axor-openai
```

Each adapter package must expose `make_session(**kwargs) -> GovernedSession`.

---

## Streaming output

When an adapter supports streaming (e.g. `axor-claude`), text is printed to the terminal as it arrives — no waiting for the full response. A spinner shows while Claude is thinking.

Non-streaming adapters print the full output when execution completes.

---

## Config file

`~/.axor/config.toml` — auto-created with `chmod 600`:

```toml
[claude]
api_key = "sk-ant-..."

[openai]
api_key = "sk-..."
```

---

## Repository structure

```
axor-cli/
├── axor_cli/
│   ├── main.py        CLI entrypoint, REPL loop, argument parsing
│   ├── auth.py        Key management — ~/.axor/config.toml, priority chain
│   ├── adapters.py    Adapter registry, lazy imports, build_session()
│   ├── display.py     Terminal formatting — color, spinner, streaming output
│   ├── streaming.py   Connects GovernedSession to terminal display
│   └── _version.py
└── tests/
    ├── conftest.py         tmp_home fixture, anthropic mock
    └── unit/
        ├── test_auth.py        11 tests — config file, permissions, priority
        ├── test_adapters.py     8 tests — registry, availability, session build
        ├── test_display.py      display formatting
        └── test_streaming.py   11 tests — output, callback, error, policy override
```

---

## Running tests

```bash
pytest tests/unit/   # no API key needed, anthropic SDK mocked
```

---

## Requirements

- Python 3.11+
- `axor-core >= 0.1.0`
- At least one adapter: `axor-claude` or `axor-openai`

---

## License

MIT
