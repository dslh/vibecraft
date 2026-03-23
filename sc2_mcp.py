#!/usr/bin/env python3
"""MCP server exposing SC2 game state and command execution tools.

Run standalone:
    .venv/bin/python3 sc2_mcp.py

Or use via .mcp.json for Claude Code integration.
"""

import json
import os
import re
import time
import uuid

from mcp.server.fastmcp import FastMCP

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BOT_DIR, "log")
COMMANDS_DIR = os.path.join(BOT_DIR, "commands")

mcp = FastMCP("sc2")


def _read_file(path: str) -> str:
    """Read a file, returning a friendly error if it doesn't exist."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return "No game running? File not found: " + os.path.basename(path)


def _read_tail(path: str, lines: int) -> str:
    """Read the last N lines of a file."""
    try:
        with open(path) as f:
            all_lines = f.readlines()
    except FileNotFoundError:
        return "No events yet. File not found: " + os.path.basename(path)
    return "".join(all_lines[-lines:])


@mcp.tool()
def game_info() -> str:
    """Read static game metadata (race, map, opponent, start positions). Written once at game start."""
    return _read_file(os.path.join(LOG_DIR, "game.txt"))


@mcp.tool()
def game_state() -> str:
    """Read current game state: resources, supply, army, structures, production queue, upgrades, enemy units/structures. Updated every ~2 seconds."""
    return _read_file(os.path.join(LOG_DIR, "snapshot.txt"))


@mcp.tool()
def game_events(lines: int = 50) -> str:
    """Read recent game events (units lost/killed, buildings completed, upgrades, reloads, errors)."""
    return _read_tail(os.path.join(LOG_DIR, "events.log"), lines)


@mcp.tool()
def game_errors(lines: int = 20) -> str:
    """Read recent bot errors with full tracebacks. Check this first when debugging bot crashes."""
    return _read_tail(os.path.join(LOG_DIR, "errors.log"), lines)


@mcp.tool()
def bot_log(lines: int = 50) -> str:
    """Read recent bot log messages from self.log() calls, timestamped with in-game time."""
    return _read_tail(os.path.join(LOG_DIR, "bot.log"), lines)


def _game_ended() -> bool:
    """Check if the game has ended by looking for the GAME ENDED marker in snapshot.txt."""
    snapshot_path = os.path.join(LOG_DIR, "snapshot.txt")
    try:
        with open(snapshot_path) as f:
            return "GAME ENDED" in f.read()
    except FileNotFoundError:
        return False


def _current_game_seconds() -> float | None:
    """Parse current game time in seconds from snapshot.txt, or None if unavailable."""
    snapshot_path = os.path.join(LOG_DIR, "snapshot.txt")
    try:
        with open(snapshot_path) as f:
            first_line = f.readline()
    except FileNotFoundError:
        return None
    m = re.match(r"Game Time:\s*(\d+):(\d+)", first_line)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


@mcp.tool()
def wait_until(game_time: str) -> str:
    """Block until the in-game clock reaches the specified time, then return.

    Args:
        game_time: Target time in M:SS or MM:SS format (e.g. "3:55", "12:00").

    Returns the game time when the wait completed.
    """
    m = re.match(r"^(\d+):(\d{2})$", game_time.strip())
    if not m:
        return f"Error: invalid time format '{game_time}'. Use M:SS or MM:SS (e.g. '3:55')."

    target_seconds = int(m.group(1)) * 60 + int(m.group(2))

    timeout = 1200  # 20 minute wall-clock safety limit
    start = time.time()
    while time.time() - start < timeout:
        if _game_ended():
            return f"Game ended before reaching {game_time}."
        current = _current_game_seconds()
        if current is not None and current >= target_seconds:
            mins, secs = divmod(int(current), 60)
            return f"Reached game time {mins}:{secs:02d} (target was {game_time})."
        time.sleep(1)

    return f"Timed out after {timeout}s wall-clock waiting for game time {game_time}. Is the game running?"


@mcp.tool()
def run_command(code: str) -> str:
    """Execute Python code inside the running game loop on the next tick.

    `self` (or `bot`) is the BotAI instance. Common imports (UnitTypeId, AbilityId,
    UpgradeId, Race, Point2) are pre-loaded. If the last statement is an expression,
    its value is printed automatically.

    Examples:
        run_command("self.minerals")
        run_command("len(self.workers.idle)")
        run_command("await self.build(UnitTypeId.SUPPLYDEPOT, near=self.townhalls.first.position)")
    """
    if not code.strip():
        return "Error: empty code"

    os.makedirs(COMMANDS_DIR, exist_ok=True)

    cmd_id = f"{time.time():.6f}_{uuid.uuid4().hex[:8]}"
    cmd_file = os.path.join(COMMANDS_DIR, f"{cmd_id}.py")
    result_file = os.path.join(COMMANDS_DIR, f"{cmd_id}.result")

    with open(cmd_file, "w") as f:
        f.write(code)

    # Poll for result (same protocol as cmd.py)
    timeout = 30
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(result_file):
            with open(result_file) as f:
                result = json.load(f)
            # Clean up
            try:
                os.unlink(result_file)
            except FileNotFoundError:
                pass
            try:
                os.unlink(cmd_file)
            except FileNotFoundError:
                pass

            output_parts = []
            if result.get("stdout"):
                output_parts.append(result["stdout"])
            if result.get("stderr"):
                output_parts.append("STDERR: " + result["stderr"])
            if not result["ok"] and result.get("error"):
                output_parts.append("ERROR: " + result["error"])

            return "\n".join(output_parts) if output_parts else "(no output)"

        time.sleep(0.05)

    # Timed out — clean up command file
    try:
        os.unlink(cmd_file)
    except FileNotFoundError:
        pass
    return f"Timed out after {timeout}s waiting for result. Is the game running?"


if __name__ == "__main__":
    mcp.run()
