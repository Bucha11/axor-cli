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
        default=["read", "write", "edit", "bash", "search", "glob"],
        metavar="TOOL",
        help="Tools to enable (default: read write edit bash search glob)",
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
        import re as _re
        image_refs = _re.findall(r'\[image:\s*([^\]]+)\]', line)
        task_text  = _re.sub(r'\[image:\s*[^\]]+\]', '', line).strip()
        task_payload = build_multimodal_task(task_text or line, image_refs)
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
    if not hook_runner._cfg.is_empty():
        await hook_runner.run_session_start()

    # single task mode
    if args.task:
        from axor_cli.images import build_multimodal_task
        task_payload = build_multimodal_task(args.task, args.image)
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
