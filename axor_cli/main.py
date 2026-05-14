from __future__ import annotations

"""
axor CLI — governed agent sessions from the terminal.

Usage:
    axor claude                         # interactive REPL
    axor claude "refactor auth module"  # single task and exit
    axor claude --policy readonly       # with preset policy
    axor claude --limit 100000          # with soft token limit
    axor claude --model claude-opus-4-7 # specific model
    axor --list-adapters                # show available adapters
"""

import argparse
import asyncio
import os
import sys

# ensure axor-core is importable when running from source
_here = os.path.dirname(os.path.abspath(__file__))
for _candidate in [
    os.path.join(_here, "..", "..", "axor-core"),
    os.path.join(_here, "..", "..", "..", "axor-core"),
]:
    if os.path.isdir(os.path.join(_candidate, "axor_core")):
        sys.path.insert(0, os.path.abspath(_candidate))
        break

from axor_cli import display, auth, adapters, streaming, telemetry
from axor_cli._version import __version__
from axor_cli.hooks import load_hooks, HookRunner
from axor_cli.session_store import save_turn, SessionHistoryLoader
from axor_cli.skill_commands import load_skill_commands


# ── @file / @url expansion ─────────────────────────────────────────────────────

import re as _re
_AT_REF = _re.compile(r'@((?:https?://\S+)|(?:[\w./~-][^\s@]*\.\w+))')

async def _expand_at_refs(text: str) -> str:
    """
    Expand @<path> and @<url> references in task text.

    @./src/main.py        → reads file, prepends content block
    @~/notes.md           → reads file from home dir
    @https://example.com  → fetches URL, prepends content block

    Refs are stripped from the task text; their content is prepended.
    Unknown refs are left as-is with a warning comment.
    """
    refs = _AT_REF.findall(text)
    if not refs:
        return text

    task_clean = _re.sub(r' {2,}', ' ', _AT_REF.sub("", text)).strip()
    parts: list[str] = []

    for ref in refs:
        if ref.startswith("http://") or ref.startswith("https://"):
            content = await _fetch_url(ref)
        else:
            content = _read_file(ref)

        if content is None:
            parts.append(f"[could not load @{ref}]")
        else:
            parts.append(f"<context src=\"{ref}\">\n{content}\n</context>")

    return "\n\n".join(parts) + ("\n\n" + task_clean if task_clean else "")


def _read_file(ref: str) -> str | None:
    from pathlib import Path
    path = Path(ref).expanduser()
    if not path.exists():
        # try relative to cwd
        path = Path.cwd() / ref
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


async def _fetch_url(url: str) -> str | None:
    import urllib.request
    import urllib.error
    try:
        def _get() -> str:
            req = urllib.request.Request(url, headers={"User-Agent": "axor-cli/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read(512_000)  # cap at 512 KB
                charset = resp.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        return await asyncio.to_thread(_get)
    except Exception as exc:
        display.print_info(f"@url fetch failed ({url}): {exc}")
        return None


# ── /init helper ───────────────────────────────────────────────────────────────

_INIT_CONFIG_FILES = [
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Makefile", "justfile", "Dockerfile", "docker-compose.yml",
    ".github/workflows",
    "README.md", "README.rst", "README",
]

_INIT_PROMPT = """
You are generating a CLAUDE.md file for a software project.
CLAUDE.md is read by AI coding assistants (like you) at the start of every session
to quickly understand the project without rereading the whole codebase.

Here is the collected project metadata:

{metadata}

Generate a concise, useful CLAUDE.md. Use the `write` tool to save it as `./CLAUDE.md`.

The file should contain:
1. **One-sentence project overview** — what it does, main technology
2. **Key commands** — build, test, lint, run, install (use code blocks)
3. **Project structure** — important directories, 1-line each
4. **Conventions** — coding style, branch naming, commit format if detectable
5. **Important notes** — anything an AI assistant must know to avoid mistakes

Rules:
- Be concise. An AI reads this, not a human. No marketing language.
- Only include what you can actually see in the metadata — don't invent.
- Prefer short bullet points over long prose.
- Put shell commands in ``` blocks so they're easy to copy.
""".strip()


def _collect_project_metadata(cwd: "Path") -> str:
    """Gather directory tree + key config file contents for /init."""
    from pathlib import Path
    import fnmatch

    parts: list[str] = []

    # Load .claudeignore patterns for filtering the tree
    _claudeignore: list[str] = []
    _ci_path = cwd / ".claudeignore"
    if _ci_path.exists():
        try:
            _claudeignore = [
                l.strip() for l in _ci_path.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")
            ]
        except OSError:
            pass

    def _skipped(name: str) -> bool:
        _noise = {".git", "node_modules", "__pycache__", ".venv", "venv",
                  "dist", "build", ".next", ".cache", "target", ".tox"}
        if name in _noise:
            return True
        import fnmatch
        return any(fnmatch.fnmatch(name, p.lstrip("/").rstrip("/")) for p in _claudeignore)

    # 1. Directory tree (max depth 3, skip common noise dirs)
    try:
        lines = ["## Directory structure"]
        for root, dirs, files in os.walk(cwd):
            dirs[:] = sorted(d for d in dirs if not _skipped(d))
            depth = len(Path(root).relative_to(cwd).parts)
            if depth > 3:
                dirs.clear()
                continue
            indent = "  " * depth
            rel = Path(root).relative_to(cwd)
            label = str(rel) if str(rel) != "." else "."
            if depth > 0:
                lines.append(f"{indent}{label}/")
            visible = [f for f in sorted(files) if not _skipped(f)]
            for f in visible[:20]:  # cap files per dir
                lines.append(f"{'  ' * (depth + 1)}{f}")
            if len(visible) > 20:
                lines.append(f"{'  ' * (depth + 1)}... ({len(visible) - 20} more)")
        parts.append("\n".join(lines))
    except Exception:
        pass

    # 2. Key config files
    for name in _INIT_CONFIG_FILES:
        path = cwd / name
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                # trim large files
                if len(content) > 4000:
                    content = content[:4000] + f"\n... (truncated, {len(content)} chars total)"
                parts.append(f"## {name}\n```\n{content}\n```")
            except OSError:
                pass
        elif path.is_dir():
            # .github/workflows — list filenames
            try:
                yamls = sorted(path.glob("*.yml")) + sorted(path.glob("*.yaml"))
                if yamls:
                    parts.append(f"## {name}/\n" + "\n".join(f"  {y.name}" for y in yamls[:10]))
            except OSError:
                pass

    return "\n\n".join(parts)


async def _run_init(session, args, hook_runner) -> None:
    """Handle /init: generate CLAUDE.md from project metadata via model."""
    from pathlib import Path

    cwd = Path.cwd()
    claude_md = cwd / "CLAUDE.md"

    if claude_md.exists():
        try:
            answer = await asyncio.to_thread(
                input,
                display.yellow("  CLAUDE.md already exists. Overwrite? [y/N] "),
            )
            if answer.strip().lower() not in ("y", "yes"):
                display.print_info("Aborted.")
                return
        except (EOFError, KeyboardInterrupt):
            print()
            display.print_info("Aborted.")
            return

    display.print_info("Collecting project metadata…")
    metadata = await asyncio.to_thread(_collect_project_metadata, cwd)

    prompt = _INIT_PROMPT.format(metadata=metadata)
    display.print_info("Generating CLAUDE.md…")
    await streaming.run_task(
        session, prompt,
        auto_approve=True,   # write tool approved automatically for /init
        hook_runner=hook_runner,
    )


# ── Built-in REPL commands ─────────────────────────────────────────────────────

_HELP = """
Built-in commands:
  /auth              Set or update API key (saved to ~/.axor/config.toml)
  /auth --clear      Remove saved API key
  /auth --show       Show where key is loaded from (never shows the key)
  /telemetry         Show telemetry status
  /telemetry on      Enable local telemetry (adds --remote to also ship)
  /telemetry off     Disable telemetry
  /telemetry preview Print the last queued telemetry record
  /cost              Token usage for this session
  /policy            Last execution policy
  /compact           Compress context (reduces token usage)
  /clear             Clear context fragments and cache
  /status            Session overview
  /model <name>      Switch model (adapter must support it)
  /tools             Show tools available to current policy
  /memory            List saved memories
  /memory add <text> Save text to memory (persists across sessions)
  /memory forget <k> Delete memory by key
  /memory search <q> Full-text search memories
  /todos             Show model's current task list
  /init              Generate CLAUDE.md from the current codebase
  /help              This message

Shortcuts:
  !<text>            Shorthand for /memory add <text>
  exit / quit / ^D   Exit axor
""".strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="axor",
        description="Governed agent sessions — powered by axor-core",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "adapter",
        nargs="?",
        choices=adapters.list_adapters(),
        metavar="ADAPTER",
        help=f"Adapter to use: {', '.join(adapters.list_adapters())}",
    )
    parser.add_argument(
        "task",
        nargs="?",
        help="Single task to run (skips REPL)",
    )
    parser.add_argument(
        "--policy", "-p",
        choices=["readonly", "sandboxed", "standard", "federated"],
        help="Override policy (skips automatic selection)",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        metavar="TOKENS",
        help="Soft token limit for budget optimization",
    )
    parser.add_argument(
        "--model", "-m",
        help="Model to use (default: adapter's default)",
    )
    parser.add_argument(
        "--api-key",
        help="API key (not saved — use /auth for persistent keys)",
    )
    parser.add_argument(
        "--no-skills",
        action="store_true",
        help="Skip loading CLAUDE.md and .claude/skills/",
    )
    parser.add_argument(
        "--no-plugins",
        action="store_true",
        help="Skip loading .claude/plugins/",
    )
    parser.add_argument(
        "--tools",
        nargs="+",
        default=["read", "write", "edit", "bash", "search", "glob", "fetch"],
        metavar="TOOL",
        help="Tools to enable (default: read write edit bash search glob fetch)",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-approve all tool calls without prompting",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume previous session from this directory",
    )
    parser.add_argument(
        "--image",
        metavar="PATH",
        action="append",
        default=[],
        help="Attach image file(s) to the task (can be repeated)",
    )
    parser.add_argument(
        "--thinking",
        type=int,
        metavar="TOKENS",
        default=None,
        help="Enable extended thinking with this token budget (e.g. 8000)",
    )
    parser.add_argument(
        "--list-adapters",
        action="store_true",
        help="List available adapters and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"axor {__version__}",
    )

    return parser.parse_args()


# ── REPL loop ──────────────────────────────────────────────────────────────────

async def repl(
    session,
    adapter: str,
    args: argparse.Namespace,
    hook_runner: HookRunner,
) -> None:
    """Interactive REPL loop."""
    policy_override = None
    if args.policy:
        from axor_core import presets
        policy_override = presets.get(args.policy)

    skill_cmds = load_skill_commands()

    while True:
        try:
            line = display.prompt("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            display.print_info("Bye.")
            break

        if not line:
            continue

        if line.lower() in ("exit", "quit", "q"):
            display.print_info("Bye.")
            break

        # ── /auth ──────────────────────────────────────────────────────────────
        if line.startswith("/auth"):
            parts = line.split()
            if "--clear" in parts:
                removed = auth.clear_from_config(adapter)
                if removed:
                    display.print_success(f"Key removed from ~/.axor/config.toml")
                else:
                    display.print_info("No key found in config.")

            elif "--show" in parts:
                env_var = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(adapter, "")
                sources = []
                if args.api_key:
                    sources.append("--api-key flag (this session only)")
                if env_var and os.environ.get(env_var):
                    sources.append(f"{env_var} env var")
                from axor_cli.auth import CONFIG_FILE
                if auth.load_from_config(adapter):
                    sources.append(f"~/.axor/config.toml")
                if sources:
                    display.print_info(f"Key loaded from: {', '.join(sources)}")
                else:
                    display.print_info("No key found. Run /auth to set one.")

            else:
                key = auth.prompt_and_save(adapter)
                if key:
                    # rebuild session with new key
                    display.print_success("Key set. Rebuilding session...")
                    try:
                        new_session = adapters.build_session(
                            adapter=adapter,
                            api_key=key,
                            model=args.model,
                            tools=tuple(args.tools),
                            soft_token_limit=args.limit,
                            load_skills=not args.no_skills,
                            load_plugins=not args.no_plugins,
                            telemetry=telemetry.build_pipeline(axor_version=__version__),
                        )
                        session = new_session
                        display.print_success("Session ready.")
                    except Exception as e:
                        display.print_error(f"Could not rebuild session: {e}")
            continue

        # ── /help ──────────────────────────────────────────────────────────────
        if line in ("/help", "/?"):
            print(f"\n{_HELP}\n")
            if skill_cmds:
                print("Skill commands (from .claude/skills/):")
                for sc in sorted(skill_cmds.values(), key=lambda s: s.name):
                    tag = "[bash]" if sc.run else "[task]"
                    print(f"  /{sc.name:<18} {tag}  {sc.description}")
                print()
            continue

        # ── /model ─────────────────────────────────────────────────────────────
        if line.startswith("/model"):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                models = adapters.available_models(adapter)
                display.print_info(f"Available models: {', '.join(models)}")
            else:
                display.print_info(f"Model switching requires session restart. "
                                   f"Restart with: axor {adapter} --model {parts[1]}")
            continue

        # ── /telemetry (CLI-local, not governance) ─────────────────────────────
        if line.startswith("/telemetry"):
            telemetry.handle_slash(line)
            continue

        # ── /init — generate CLAUDE.md ─────────────────────────────────────────
        if line == "/init":
            await _run_init(session, args, hook_runner)
            continue

        # ── /todos — show current model todo list ──────────────────────────────
        if line in ("/todos", "/todo"):
            store = getattr(session, "_todo_store", None)
            if store is None or not store.read():
                display.print_info("No todos yet. The model will create them when working on multi-step tasks.")
            else:
                print(f"\n{store.format()}")
            continue

        # ── Skill slash commands ────────────────────────────────────────────────
        if line.startswith("/"):
            cmd_name = line[1:].split()[0].lower()
            if cmd_name in skill_cmds:
                skill = skill_cmds[cmd_name]
                if skill.run:
                    display.print_info(f"Running: {skill.run}")
                    proc = await asyncio.create_subprocess_shell(
                        skill.run,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    stdout, _ = await proc.communicate()
                    if stdout:
                        print(stdout.decode(errors="replace"), end="")
                else:
                    summary = await streaming.run_task(
                        session, skill.task, policy=policy_override,
                        auto_approve=args.yes, hook_runner=hook_runner,
                    )
                    if summary.get("output"):
                        save_turn(skill.task, summary["output"])
                continue

        # ── Governed slash commands (forwarded to session) ─────────────────────
        if line.startswith("/"):
            result = await session.run(line)
            output = result.output
            if output and output != "[cancelled]":
                cmd_class = result.metadata.get("class", "passthrough")
                if cmd_class == "governance":
                    # structured response from envelope/trace — prefix with →
                    display.print_info(output)
                else:
                    # context commands and passthrough — plain output
                    print(f"\n{output}")
            continue

        # ── !remember shortcut → /memory add ──────────────────────────────────
        if line.startswith("!") and not line.startswith("!#"):
            text = line[1:].strip()
            if text:
                await session.save_memory(text)
                display.print_success(f"Saved to memory: {text[:60]}")
            continue

        # ── Task ───────────────────────────────────────────────────────────────
        from axor_cli.images import build_multimodal_task
        # expand @file/@url refs, then extract [image:] refs
        expanded = await _expand_at_refs(line)
        image_refs = _re.findall(r'\[image:\s*([^\]]+)\]', expanded)
        task_text  = _re.sub(r'\[image:\s*[^\]]+\]', '', expanded).strip()
        task_payload = build_multimodal_task(task_text or expanded, image_refs)
        summary = await streaming.run_task(
            session, task_payload, policy=policy_override,
            auto_approve=args.yes, hook_runner=hook_runner,
        )
        if summary.get("output"):
            save_turn(line, summary["output"])


# ── Main ───────────────────────────────────────────────────────────────────────

async def async_main() -> int:
    args = _parse_args()

    # --list-adapters
    if args.list_adapters:
        print("\nAvailable adapters:")
        for name in adapters.list_adapters():
            available = adapters.is_available(name)
            status = display.green("installed") if available else display.red("not installed")
            hint = "" if available else f"  →  {adapters.get_install_hint(name)}"
            print(f"  {name:12} {status}{hint}")
        print()
        return 0

    # adapter required after this point
    if not args.adapter:
        print("Usage: axor <adapter> [task]")
        print("       axor --list-adapters")
        print(f"\nAvailable adapters: {', '.join(adapters.list_adapters())}")
        return 1

    adapter = args.adapter

    # check adapter installed
    if not adapters.is_available(adapter):
        display.print_error(
            f"Adapter '{adapter}' is not installed.\n"
            f"  Install with: {adapters.get_install_hint(adapter)}"
        )
        return 1

    # resolve API key
    api_key = auth.resolve_api_key(adapter, flag_key=args.api_key)
    if not api_key:
        api_key = auth.prompt_and_save(adapter)
        if not api_key:
            display.print_error("No API key. Exiting.")
            return 1

    # one-time opt-in banner (no-op after first run, suppressed by AXOR_NO_BANNER)
    telemetry.maybe_show_first_run_banner()
    pipeline = telemetry.build_pipeline(axor_version=__version__)

    # build session
    try:
        session = adapters.build_session(
            adapter=adapter,
            api_key=api_key,
            model=args.model,
            tools=tuple(args.tools),
            soft_token_limit=args.limit,
            load_skills=not args.no_skills,
            load_plugins=not args.no_plugins,
            resume=args.resume,
            thinking_budget=args.thinking,
            telemetry=pipeline,
        )
    except Exception as e:
        display.print_error(f"Could not start session: {e}")
        return 1

    policy_override = None
    if args.policy:
        from axor_core import presets
        try:
            policy_override = presets.get(args.policy)
        except KeyError as e:
            display.print_error(str(e))
            return 1

    # load hooks and fire SessionStart
    hook_runner = HookRunner(load_hooks())
    if not hook_runner.is_empty():
        await hook_runner.run_session_start()

    # single task mode
    if args.task:
        from axor_cli.images import build_multimodal_task
        expanded_task = await _expand_at_refs(args.task)
        task_payload = build_multimodal_task(expanded_task, args.image)
        await streaming.run_task(
            session, task_payload, policy=policy_override,
            auto_approve=args.yes, hook_runner=hook_runner,
        )
        return 0

    # interactive REPL
    model = args.model or adapters.default_model(adapter)
    display.print_header(adapter=adapter, model=model, version=__version__)
    await repl(session, adapter=adapter, args=args, hook_runner=hook_runner)
    return 0


def main() -> None:
    """Entry point registered in pyproject.toml."""
    try:
        code = asyncio.run(async_main())
        sys.exit(code)
    except KeyboardInterrupt:
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
