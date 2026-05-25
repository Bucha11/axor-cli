# axor-cli

[![PyPI](https://img.shields.io/pypi/v/axor-cli?cacheSeconds=300)](https://pypi.org/project/axor-cli/)
[![Python](https://img.shields.io/pypi/pyversions/axor-cli?cacheSeconds=300)](https://pypi.org/project/axor-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Governed agent sessions in your terminal.**

Run Claude or any OpenRouter model under axor-core governance — controlled tool permissions, token budgets, context compression, hooks, skills, memory, and full audit trail. Feature-compatible with [Claude Code](https://claude.ai/code) configuration files.

---

## Installation

```bash
# With OpenRouter (200+ models, recommended)
pip install axor-cli axor-openrouter

# With Claude directly
pip install axor-cli axor-claude

# With OpenAI
pip install axor-cli axor-openai
```

---

## Quick start

```bash
# Set API key (saved to ~/.axor/config.toml)
axor openrouter /auth

# Interactive REPL
axor openrouter

# Single task and exit
axor openrouter "refactor the auth module"

# With options
axor openrouter --policy readonly "review this PR"
axor openrouter --limit 100000 --model anthropic/claude-opus-4-7 "large migration"
axor openrouter -y "scaffold a FastAPI project"   # auto-approve all tools
```

---

## Authentication

On first run, axor prompts for an API key and saves it to `~/.axor/config.toml` (permissions: 600).

Key priority (highest wins):

| Source | When used |
|--------|-----------|
| `--api-key` flag | One-off, never saved |
| Env var (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) | CI/CD, containers |
| `~/.axor/config.toml` | Persistent, set via `/auth` |

```
> /auth              # prompt and save
> /auth --show       # show source (never shows the key)
> /auth --clear      # remove saved key
```

---

## CLI options

```
axor <adapter> [task] [options]

Adapters:  openrouter, claude, openai

Options:
  -p, --policy PRESET   readonly | sandboxed | standard | federated
  -l, --limit TOKENS    Soft token limit (triggers auto-compact and budget signals)
  -m, --model NAME      Model override (e.g. anthropic/claude-opus-4-7)
      --api-key KEY      API key for this session only (never saved)
      --tools TOOL ...   Tools to enable (default: read write edit bash search glob fetch)
      --yes, -y          Auto-approve all tool calls without prompting
      --resume           Inject last session's context as starting history
      --image PATH       Attach image file (can be repeated, vision models only)
      --thinking TOKENS  Extended thinking budget in tokens (e.g. 8000)
      --no-skills        Skip CLAUDE.md and .claude/skills/
      --no-plugins       Skip .claude/plugins/
      --list-adapters    Show installed adapters and exit
      --version          Show version
```

---

## REPL commands

### Built-in

| Command | Description |
|---------|-------------|
| `/auth [--show\|--clear]` | Manage API key |
| `/model [name]` | Show available models; restart hint for switching |
| `/init` | Generate `CLAUDE.md` from the current codebase |
| `/memory` | List memories saved for this project |
| `/memory add <text>` | Save text to persistent memory |
| `/memory forget <key>` | Delete a memory by key |
| `/memory search <query>` | Full-text search memories |
| `/todos` | Show the model's current task list |
| `/telemetry [on\|off\|preview]` | Manage local telemetry |
| `/help` | All commands including loaded skills |
| `!<text>` | Shorthand for `/memory add <text>` |
| `exit` / `quit` / `^D` | Exit |

### Governed (handled by axor-core)

| Command | Description |
|---------|-------------|
| `/cost` | Token usage for this session |
| `/policy` | Last execution policy |
| `/compact` | Compress context (reduces token usage) |
| `/clear` | Clear all context fragments and cache |
| `/status` | Session overview |
| `/tools` | Tools available under the current policy |

### Skills

Skills in `.claude/skills/` or `~/.claude/skills/` are available as `/skillname`. See [Skills](#skills) below.

---

## Tool approval

When a tool needs approval, axor shows:

```
  write(path='auth.py', content='...')  [y/n/a/?]
```

| Key | Action |
|-----|--------|
| `y` / Enter | Allow once |
| `n` | Deny |
| `a` | Always allow this tool for the rest of the session |
| `?` | Show help |

Tools that are always auto-approved (non-destructive): `read`, `search`, `glob`, `fetch`.

---

## @file and @url references

Prefix any file path or URL with `@` to inject its content into the task:

```
> review @./src/auth.py for security issues
> summarize @https://docs.example.com/api
> compare @./old.py and @./new.py
```

The content is prepended as a `<context src="...">` block; the `@ref` is stripped from the task text.

---

## Configuration files

axor-cli reads the same config files as [Claude Code](https://claude.ai/code).

### CLAUDE.md

Place a `CLAUDE.md` in your project root. It's loaded as the system prompt context at session start, giving the model standing instructions about your project.

Generate one automatically:

```
> /init
```

### `.claudeignore`

Works like `.gitignore`. Files and directories matching these patterns are excluded from `read`, `glob`, `search`, and `/init` tree walks.

```
# .claudeignore
*.pyc
__pycache__
node_modules
.venv
dist/
secrets.env
```

### `~/.claude/settings.json` and `.claude/settings.json`

Tool permission rules and hooks. Project settings override user settings.

```json
{
  "permissions": {
    "allow": ["Read", "Bash(npm *)"],
    "deny":  ["Bash(rm -rf *)", "Write(/etc/*)"]
  },
  "hooks": {
    "PreToolUse":  [{"matcher": "bash", "command": "echo 'Running: $TOOL_INPUT'"}],
    "PostToolUse": [{"command": "notify-send 'Tool done'"}],
    "Stop":        [{"command": "say Done"}],
    "SessionStart":[{"command": "npm run build 2>&1 || true"}]
  }
}
```

Permission rule format: `ToolName` (blanket) or `ToolName(glob_pattern)` (pattern match on primary arg).

Hook env vars: `TOOL_NAME`, `TOOL_INPUT` (JSON), `TOOL_RESULT`. PreToolUse hooks block the call on non-zero exit.

---

## Skills

Skills are markdown files in `.claude/skills/` (project) or `~/.claude/skills/` (user).

```markdown
---
description: Run the full test suite and show coverage
run: pytest --cov=src --cov-report=term-missing
---
```

Or as an agent task:

```markdown
---
description: Write and run a benchmark for the current module
---
Write a benchmark for the current module using timeit, run it, and show results.
```

Skills appear in `/help` and are invoked as `/skillname`.

---

## Memory

axor stores persistent memories in `~/.axor/memory.db` (SQLite), scoped to the project directory.

```
> !Always use type hints in this project.
  ✓ Saved to memory: Always use type hints in this project.

> /memory search type hints
> /memory forget <key>
> /memory
```

Memories are injected into the system prompt at session start.

---

## Auto-compact

When accumulated tokens exceed 75% of `--limit` (or 80,000 tokens with no limit), axor automatically compresses context and reports:

```
  → auto-compact: 45,231 → 12,108 ctx tokens  (73% freed)
```

Use `/compact` to trigger manually.

---

## Config file

`~/.axor/config.toml` — auto-created with permissions 600:

```toml
[openrouter]
api_key = "sk-or-..."

[claude]
api_key = "sk-ant-..."

# OpenRouter routing (optional)
[openrouter.routing]
mode             = "smart"   # smart | cascade | flat
prefer_free_at_depth = 3
root_model       = "anthropic/claude-sonnet-4-6"

# MCP servers (optional)
[[mcp.servers]]
name    = "filesystem"
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

See [axor-openrouter](https://github.com/Bucha11/axor-openrouter) for full routing and MCP documentation.

---

## Available adapters

```
$ axor --list-adapters

Available adapters:
  openrouter   installed
  claude       installed
  openai       not installed  →  pip install axor-openai
```

Each adapter must expose `make_session(**kwargs) -> GovernedSession`.

---

## Repository structure

```
axor-cli/
├── axor_cli/
│   ├── main.py           CLI entrypoint, REPL loop, argument parsing
│   ├── adapters.py       Adapter registry, lazy imports, build_session()
│   ├── auth.py           Key management — ~/.axor/config.toml, priority chain
│   ├── display.py        Terminal output — color, spinner, markdown renderer
│   ├── streaming.py      Connects GovernedSession to terminal (callbacks, approval)
│   ├── hooks.py          Hook runner — PreToolUse, PostToolUse, Stop, SessionStart
│   ├── permissions.py    Settings.json allow/deny rules
│   ├── skill_commands.py Skill discovery from .claude/skills/*.md
│   ├── memory_provider.py SQLite memory store with FTS5 full-text search
│   ├── session_store.py  Session history persistence for --resume
│   ├── mcp_config.py     MCP server config loader
│   ├── routing_config.py OpenRouter cascade/smart routing config
│   ├── images.py         Multimodal image encoding (data URIs)
│   ├── telemetry.py      Optional telemetry bridge
│   └── _version.py
└── tests/
```

---

## Requirements

- Python 3.11+
- [`axor-core`](https://github.com/Bucha11/axor-core) >= 0.5.0
- At least one adapter: [`axor-claude`](https://github.com/Bucha11/axor-claude), `axor-openrouter`, or `axor-openai`

---

## Ecosystem

| Package | Role |
|---------|------|
| [`axor-core`](https://github.com/Bucha11/axor-core) | Governance kernel |
| [`axor-claude`](https://github.com/Bucha11/axor-claude) | Claude / Claude Code adapter — `axor claude` subcommand |
| [`axor-memory-sqlite`](https://github.com/Bucha11/axor-memory-sqlite) | Cross-session memory (`/memory`, `!` shorthand) |
| [`axor-telemetry`](https://github.com/Bucha11/axor-telemetry) | Privacy-preserving governance feedback (`/telemetry`) |
| [`axor-classifier-simple`](https://github.com/Bucha11/axor-classifier-simple) | ML task signal derivation (optional) |
| [`axor-classifier-llm`](https://github.com/Bucha11/axor-classifier-llm) | LLM verifier for gray-zone escalation (optional) |
| [`axor-langchain`](https://github.com/Bucha11/axor-langchain) | LangChain governance middleware |
| [`axor-benchmarks`](https://github.com/Bucha11/axor-benchmarks) | Governance proof layer |

---

## License

MIT
