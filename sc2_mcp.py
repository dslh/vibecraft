#!/usr/bin/env python3
"""MCP server exposing SC2 game state and command execution tools.

Run standalone:
    .venv/bin/python3 sc2_mcp.py

Or use via .mcp.json for Claude Code integration.
"""

import json
import os
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
