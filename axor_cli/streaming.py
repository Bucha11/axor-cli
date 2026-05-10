from __future__ import annotations

"""
Streaming execution driver for axor-cli.

Connects GovernedSession to the terminal:
  - shows spinner while waiting for first token
  - prints text chunks as they arrive via set_text_callback()
  - falls back to full output for non-streaming adapters
  - prints completion stats
"""

import asyncio
from typing import Any

from axor_core import GovernedSession
from axor_core.contracts.policy import ExecutionPolicy

from axor_cli import display


async def run_task(
    session: GovernedSession,
    task: str,
    policy: ExecutionPolicy | None = None,
    auto_approve: bool = False,
) -> dict[str, Any]:
    """
    Run a task and stream output to terminal.

    Returns execution summary:
        {policy, input_tokens, output_tokens, cancelled, error}
    """
    spinner = display.Spinner(prefix="  ")
    spinner.start()

    summary: dict[str, Any] = {
        "policy":        "unknown",
        "input_tokens":  0,
        "output_tokens": 0,
        "cancelled":     False,
        "error":         None,
        "output":        "",
    }

    try:
        await _stream_run(session, task, policy, spinner, summary, auto_approve)
    except asyncio.CancelledError:
        spinner.stop()
        summary["cancelled"] = True
        display.print_completion(
            policy=summary["policy"],
            input_tokens=summary["input_tokens"],
            output_tokens=summary["output_tokens"],
            cancelled=True,
        )
    except Exception as e:
        spinner.stop()
        display.print_error(str(e))
        summary["error"] = str(e)

    return summary


async def _stream_run(
    session: GovernedSession,
    task: str,
    policy: ExecutionPolicy | None,
    spinner: display.Spinner,
    summary: dict[str, Any],
    auto_approve: bool = False,
) -> None:
    text_received = False

    # streaming path — session.executor exposes set_text_callback()
    # Use getattr to avoid depending on GovernedSession internals
    executor = getattr(session, "executor", None) or getattr(session, "_executor", None)

    def _ensure_spinner_stopped() -> None:
        nonlocal text_received
        if not text_received:
            spinner.stop()
            print()
            text_received = True

    if executor and hasattr(executor, "set_text_callback"):
        def on_text(chunk: str) -> None:
            _ensure_spinner_stopped()
            display.stream_text(chunk)

        executor.set_text_callback(on_text)

    # Capture pre-edit file content for diff display.
    _pre_edit: dict[str, str] = {}

    def _capture_pre_edit(tool_name: str, args: dict) -> None:
        if tool_name in ("edit", "write"):
            path = args.get("path") or args.get("file_path") or ""
            if path:
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        _pre_edit[path] = f.read()
                except OSError:
                    _pre_edit[path] = ""

    def _show_diff(tool_name: str, args: dict, result: Any) -> None:
        if tool_name not in ("edit", "write"):
            return
        approved = not (isinstance(result, dict) and result.get("error") == "tool_denied")
        if not approved:
            return
        path = args.get("path") or args.get("file_path") or ""
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                new_content = f.read()
        except OSError:
            return
        old_content = _pre_edit.get(path, "")
        display.print_diff(old_content, new_content, path)

    if executor and hasattr(executor, "set_tool_callbacks"):
        def on_tool_start(tool_name: str, args: dict) -> None:
            _ensure_spinner_stopped()
            _capture_pre_edit(tool_name, args)
            if auto_approve or tool_name in display._AUTO_APPROVE:
                display.print_tool_call(tool_name, args, approved=True)

        def on_tool_end(tool_name: str, args: dict, result: Any) -> None:
            approved = not (isinstance(result, dict) and result.get("error") == "tool_denied")
            display.print_tool_result(tool_name, str(result), approved=approved)
            _show_diff(tool_name, args, result)

        executor.set_tool_callbacks(on_tool_start, on_tool_end)

    if not auto_approve and executor and hasattr(executor, "set_approval_callback"):
        async def on_approval(tool_name: str, args: dict) -> bool:
            _ensure_spinner_stopped()
            return await display.prompt_approval(tool_name, args)

        executor.set_approval_callback(on_approval)

    result = await session.run(task, policy=policy)

    # ensure spinner stopped even on error/empty output
    spinner.stop()

    if not text_received:
        # non-streaming adapter — print result all at once
        if result.output and result.output != "[cancelled]":
            print()
            print(result.output)

    display.end_stream()

    summary["policy"]        = result.metadata.get("policy", "unknown")
    summary["input_tokens"]  = result.token_usage.input_tokens
    summary["output_tokens"] = result.token_usage.output_tokens
    summary["cancelled"]     = result.metadata.get("cancelled", False)
    summary["output"]        = result.output or ""

    display.print_completion(
        policy=summary["policy"],
        input_tokens=summary["input_tokens"],
        output_tokens=summary["output_tokens"],
        cancelled=summary["cancelled"],
    )
