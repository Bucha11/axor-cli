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
    }

    try:
        await _stream_run(session, task, policy, spinner, summary)
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
) -> None:
    text_received = False

    # streaming path — session.executor exposes set_text_callback()
    # Use getattr to avoid depending on GovernedSession internals
    executor = getattr(session, "executor", None) or getattr(session, "_executor", None)
    if executor and hasattr(executor, "set_text_callback"):
        def on_text(chunk: str) -> None:
            nonlocal text_received
            if not text_received:
                spinner.stop()
                print()          # newline between prompt and output
                text_received = True
            display.stream_text(chunk)

        executor.set_text_callback(on_text)

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

    display.print_completion(
        policy=summary["policy"],
        input_tokens=summary["input_tokens"],
        output_tokens=summary["output_tokens"],
        cancelled=summary["cancelled"],
    )
