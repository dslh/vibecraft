#!/usr/bin/env python3
"""Chat interface for SC2 bot development using the Claude Agent SDK.

Usage:
    .venv/bin/python3 chat.py
    .venv/bin/python3 chat.py --verbose

Requires:
    pip install claude-agent-sdk mcp rich prompt_toolkit
    ANTHROPIC_API_KEY in .env or environment
"""

import argparse
import asyncio
import json
import os
import sys
import threading

if sys.platform == "win32":
    import msvcrt
else:
    import select
    import termios
    import tty

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    UserMessage,
)
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
SC2_DIR = os.path.dirname(BOT_DIR)
HISTORY_FILE = os.path.join(BOT_DIR, ".chat_history")

console = Console()

SYSTEM_PROMPT = """\
You are an SC2 bot developer. You help the user write and debug a StarCraft II bot that runs via a hot-reloading harness.

## Working Directory

Your working directory is `bot/` (absolute path: {bot_dir}).
ALL relative paths are relative to this directory. For example:
- `bot_src/bot.py` — the bot entry point
- `cheatsheets/api.md` — the shared API cheatsheet

## Project Layout

- `bot_src/` — Bot code. The entry point is `bot_src/bot.py`, which defines a `BotAI` subclass with `on_step`, callbacks like `on_unit_destroyed`, etc. Code can be split across multiple files in `bot_src/`.
- `cheatsheets/` — API reference files. Read `cheatsheets/api.md` (not just `api.md`). These are pre-written references — read them instead of digging through python-sc2 source.
  - `cheatsheets/api.md` — Shared API: BotAI state, Unit/Units, economy, building, tech, map, events, debug commands.
  - `cheatsheets/terran.md` / `cheatsheets/protoss.md` / `cheatsheets/zerg.md` — Race-specific units, abilities, upgrades.
- `../python-sc2/` — The python-sc2 library source (available for deeper reference).

## How the Harness Works

The harness (`run.py`) hot-reloads all `.py` files in `bot_src/` on every game tick when changes are detected. The user's `BotAI` subclass methods are called as unbound methods on the live bot instance, so `self` is the real BotAI with full game state. Instance variables on `self` persist across reloads. Errors are caught and logged without crashing the game.

## Your MCP Tools

You have SC2-specific tools available via the `sc2` MCP server:

- `game_info` — Static game metadata (race, map, opponent, start positions)
- `game_state` — Current resources, supply, army, structures, production queue, upgrades, enemy intel
- `game_events` — Recent event stream (units lost/killed, buildings completed, upgrades)
- `game_errors` — Recent bot errors with tracebacks. **Check this first when debugging.**
- `bot_log` — Recent bot log messages from `self.log()` calls
- `run_command` — Execute Python code in the running game. `self` is the BotAI instance. Common imports (UnitTypeId, AbilityId, UpgradeId, Race, Point2) are pre-loaded. Use this to inspect state or issue one-off orders.

## Workflow

1. At session start, read `cheatsheets/api.md`. If a game is running, use `game_info` to check the race and read the matching race cheatsheet too.
2. Use `game_state`, `game_events`, and `bot_log` to understand what's happening in a running game.
3. Edit files in `bot_src/` to implement or fix bot logic. Changes take effect on the next game tick.
4. Use `run_command` to test ideas or issue one-off commands without modifying bot code.
5. Check `game_errors` when something goes wrong.

## Key Rules

- `bot_src/bot.py` must define a `BotAI` subclass — the harness looks for it.
- Instance variables on `self` persist across hot-reloads, but module-level state is reset.
- Keep bot code simple and robust — errors are caught but waste game time.
- Read cheatsheets before writing code. They have the exact API you need.
"""


# ── Keystroke watcher ────────────────────────────────────────────────────────

class _KeyWatcherBase:
    """Watches stdin for keystrokes via a background thread.

    Keys are pushed into an asyncio queue for the event loop to consume.
    Call stop() to restore the terminal before using prompt_toolkit.
    """

    def __init__(self):
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._active = False
        self._thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop):
        self._active = True
        self._thread = threading.Thread(target=self._run, args=(loop,), daemon=True)
        self._thread.start()

    def stop(self):
        self._active = False
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None

    def _run(self, loop: asyncio.AbstractEventLoop):
        raise NotImplementedError

    async def wait_key(self) -> bytes:
        return await self._queue.get()


if sys.platform == "win32":

    class _KeyWatcher(_KeyWatcherBase):
        """Windows implementation using msvcrt."""

        def _run(self, loop: asyncio.AbstractEventLoop):
            import time
            while self._active:
                if msvcrt.kbhit():
                    data = msvcrt.getch()
                    # Read any immediately following bytes (escape sequences)
                    while msvcrt.kbhit():
                        data += msvcrt.getch()
                    loop.call_soon_threadsafe(self._queue.put_nowait, data)
                else:
                    time.sleep(0.05)

else:

    class _KeyWatcher(_KeyWatcherBase):
        """Unix implementation using termios/cbreak mode."""

        def __init__(self):
            super().__init__()
            self._fd = sys.stdin.fileno()
            self._old_settings = None

        def start(self, loop: asyncio.AbstractEventLoop):
            self._old_settings = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            super().start(loop)

        def stop(self):
            super().stop()
            if self._old_settings is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
                self._old_settings = None

        def _run(self, loop: asyncio.AbstractEventLoop):
            while self._active:
                r, _, _ = select.select([self._fd], [], [], 0.1)
                if r and self._active:
                    data = os.read(self._fd, 32)
                    loop.call_soon_threadsafe(self._queue.put_nowait, data)


# ── Tool call summaries ──────────────────────────────────────────────────────

def _summarize_tool(name: str, inputs: dict) -> str:
    """Return a short human-readable summary of a tool call."""
    display_name = name.removeprefix("mcp__sc2__")

    if name == "Read":
        path = inputs.get("file_path", "?")
        return f"Read {_short_path(path)}"

    if name == "Write":
        path = inputs.get("file_path", "?")
        content = inputs.get("content", "")
        lines = content.count("\n") + (1 if content else 0)
        return f"Write {_short_path(path)} ({lines} lines)"

    if name == "Edit":
        path = inputs.get("file_path", "?")
        old = inputs.get("old_string", "")
        new = inputs.get("new_string", "")
        removed = old.count("\n") + (1 if old else 0)
        added = new.count("\n") + (1 if new else 0)
        return f"Edit {_short_path(path)} (-{removed}/+{added} lines)"

    if name == "Glob":
        return f"Glob {inputs.get('pattern', '?')}"

    if name == "Grep":
        pattern = inputs.get("pattern", "?")
        path = inputs.get("path", "")
        suffix = f" in {_short_path(path)}" if path else ""
        return f"Grep /{pattern}/{suffix}"

    if display_name == "run_command":
        code = inputs.get("code", "")
        first_line = code.split("\n")[0]
        if len(first_line) > 60:
            first_line = first_line[:57] + "..."
        return f"run_command: {first_line}"

    if display_name in ("game_info", "game_state", "game_events", "game_errors", "bot_log"):
        lines = inputs.get("lines")
        suffix = f" (last {lines})" if lines else ""
        return f"{display_name}{suffix}"

    if name == "TodoWrite":
        return None  # handled by _print_todo_write

    if name == "TodoRead":
        return "TodoRead"

    if name in ("TaskCreate", "TaskUpdate"):
        subject = inputs.get("subject", "")
        status = inputs.get("status", "")
        suffix = f" [{status}]" if status else ""
        return f"{name}: {subject}{suffix}" if subject else name

    if name == "TaskList":
        return "TaskList"

    return display_name


_TODO_ICONS = {
    "completed": "\u2713",   # ✓
    "in_progress": "\u25b6",  # ▶
    "pending": "\u25cb",      # ○
}


def _print_todo_write(inputs: dict):
    """Print a TodoWrite call as a formatted task list."""
    todos = inputs.get("todos", [])
    if not todos:
        console.print(Text("  > Tasks: (empty)", style="dim cyan"))
        return
    console.print(Text("  > Tasks:", style="dim cyan"))
    for todo in todos:
        status = todo.get("status", "pending")
        icon = _TODO_ICONS.get(status, "?")
        content = todo.get("content", "(no content)")
        if status == "completed":
            style = "dim green"
        elif status == "in_progress":
            style = "bold cyan"
        else:
            style = "dim"
        console.print(Text(f"    {icon} {content}", style=style))


def _short_path(path: str) -> str:
    """Shorten an absolute path to be relative to BOT_DIR or SC2_DIR."""
    for base, prefix in [(BOT_DIR, ""), (SC2_DIR, "../")]:
        if path.startswith(base + "/"):
            return prefix + path[len(base) + 1:]
    return os.path.basename(path)


# ── Message display ──────────────────────────────────────────────────────────

def _print_message(msg, verbose: bool, live: Live | None):
    """Print a message from the agent."""

    if isinstance(msg, AssistantMessage):
        if live is not None:
            live.stop()

        for block in msg.content:
            if isinstance(block, TextBlock):
                console.print(Markdown(block.text))
            elif isinstance(block, ToolUseBlock):
                summary = _summarize_tool(block.name, block.input)
                if summary is None:
                    # Special display (e.g. TodoWrite)
                    if block.name == "TodoWrite":
                        _print_todo_write(block.input)
                else:
                    console.print(Text(f"  > {summary}", style="dim cyan"))
                if verbose:
                    console.print(Text(f"    {json.dumps(block.input, indent=2)}", style="dim"))

                if live is not None:
                    live.start()

        if verbose and msg.error:
            console.print(Text(f"  [error: {msg.error}]", style="bold red"))

    elif isinstance(msg, ResultMessage):
        if live is not None:
            live.stop()

        parts = []
        if msg.num_turns is not None:
            parts.append(f"{msg.num_turns} turns")
        if msg.total_cost_usd is not None:
            parts.append(f"${msg.total_cost_usd:.4f}")
        if msg.duration_ms is not None:
            secs = msg.duration_ms / 1000
            if secs >= 60:
                parts.append(f"{secs / 60:.1f}m")
            else:
                parts.append(f"{secs:.1f}s")
        if parts:
            console.print(Text(f"  [{' | '.join(parts)}]", style="dim"))
        if msg.is_error and msg.result:
            console.print(Text(f"Error: {msg.result}", style="bold red"))

    elif isinstance(msg, UserMessage):
        if verbose:
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    content = block.content
                    if isinstance(content, str) and len(content) > 200:
                        content = content[:200] + "..."
                    err_style = "red" if block.is_error else "dim"
                    console.print(Text(f"    = {content}", style=err_style))

    elif isinstance(msg, SystemMessage):
        if verbose:
            console.print(Text(f"  [system: {msg.subtype}]", style="dim magenta"))


# ── Response + interrupt handling ────────────────────────────────────────────

async def _drain_response(client, verbose: bool, live: Live):
    """Consume all messages from the agent response stream."""
    async for msg in client.receive_response():
        _print_message(msg, verbose, live)


async def _run_query(client, verbose: bool, is_tty: bool) -> str | None:
    """Run one agent query cycle. Returns queued follow-up input, or None."""
    live = Live(
        Spinner("dots", text="thinking...", style="cyan"),
        console=console,
        transient=True,
    )
    live.start()

    response_task = asyncio.create_task(_drain_response(client, verbose, live))

    # If not a real terminal, just await the response — no key watching.
    if not is_tty:
        await response_task
        live.stop()
        return None

    watcher = _KeyWatcher()
    watcher.start(asyncio.get_event_loop())
    next_input = None

    try:
        while not response_task.done():
            key_task = asyncio.create_task(watcher.wait_key())
            done, _ = await asyncio.wait(
                {response_task, key_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Response finished naturally — clean up pending key task.
            if response_task in done:
                key_task.cancel()
                break

            # A key was pressed.
            if key_task in done:
                data = key_task.result()

                if data == b'\x1b':
                    # Escape — hard interrupt, return to prompt.
                    live.stop()
                    watcher.stop()
                    await client.interrupt()
                    await asyncio.wait_for(response_task, timeout=5.0)
                    console.print(Text("  (interrupted)", style="dim yellow"))
                    break

                if not data.startswith(b'\x1b'):
                    # Printable key — interrupt and prompt for new input.
                    live.stop()
                    watcher.stop()
                    await client.interrupt()
                    await asyncio.wait_for(response_task, timeout=5.0)
                    console.print(Text("  (interrupted)", style="dim yellow"))
                    first_chars = data.decode("utf-8", errors="replace")
                    # Prompt with first typed chars pre-filled.
                    try:
                        next_input = await asyncio.to_thread(
                            _prompt_session.prompt, "You: ", default=first_chars
                        )
                    except (EOFError, KeyboardInterrupt):
                        pass
                    break

                # Escape sequence (arrow keys etc.) — ignore, loop again.
    except asyncio.TimeoutError:
        response_task.cancel()
    finally:
        watcher.stop()
        live.stop()

    return next_input


# ── Main ─────────────────────────────────────────────────────────────────────

_prompt_session: PromptSession  # module-level so _run_query can use it


async def main(verbose: bool = False):
    global _prompt_session

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT.format(bot_dir=BOT_DIR),
        cwd=BOT_DIR,
        add_dirs=[os.path.join(SC2_DIR, "python-sc2")],
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "mcp__sc2__*"],
        disallowed_tools=["Bash"],
        mcp_servers={
            "sc2": {
                "command": os.path.join(
                    BOT_DIR, ".venv",
                    "Scripts" if sys.platform == "win32" else "bin",
                    "python.exe" if sys.platform == "win32" else "python3",
                ),
                "args": [os.path.join(BOT_DIR, "sc2_mcp.py")],
            }
        },
        permission_mode="acceptEdits",
        max_turns=30,
    )

    _prompt_session = PromptSession(history=FileHistory(HISTORY_FILE))
    is_tty = sys.stdin.isatty()

    async with ClaudeSDKClient(options=options) as client:
        console.print("[bold]SC2 Bot Development Chat[/bold]")
        if verbose:
            console.print("[dim](verbose mode)[/dim]")
        hints = ["'quit' to exit"]
        if is_tty:
            hints.append("Esc to interrupt")
            hints.append("type to interrupt & follow up")
        console.print(f"[dim]{' | '.join(hints)}[/dim]\n")

        next_input = None

        while True:
            if next_input is not None:
                user_input = next_input
                next_input = None
                if not user_input.strip():
                    continue
                if user_input.strip().lower() in ("quit", "exit", "q"):
                    break
            else:
                try:
                    user_input = await asyncio.to_thread(
                        _prompt_session.prompt, "You: ", multiline=False
                    )
                except (EOFError, KeyboardInterrupt):
                    break

                if user_input.strip().lower() in ("quit", "exit", "q"):
                    break
                if not user_input.strip():
                    continue

            console.print()
            await client.query(user_input)
            next_input = await _run_query(client, verbose, is_tty)
            console.print()


ENV_FILE = os.path.join(BOT_DIR, ".env")


def _ensure_api_key():
    """Load API key from .env, or prompt and save it."""
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)

    if os.environ.get("ANTHROPIC_API_KEY"):
        return

    console.print("No ANTHROPIC_API_KEY found in .env or environment.")
    console.print("Get your API key from [link=https://console.anthropic.com/]console.anthropic.com[/link]\n")

    key = console.input("[bold]Paste your API key: [/bold]").strip()
    if not key:
        console.print("[red]No key provided.[/red]")
        sys.exit(1)

    os.environ["ANTHROPIC_API_KEY"] = key

    # Append to .env
    with open(ENV_FILE, "a") as f:
        f.write(f"ANTHROPIC_API_KEY={key}\n")
    console.print(f"[dim]Saved to {os.path.basename(ENV_FILE)}[/dim]\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SC2 Bot Development Chat")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show tool results, system messages, and full tool inputs",
    )
    args = parser.parse_args()

    _ensure_api_key()

    try:
        asyncio.run(main(verbose=args.verbose))
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")
