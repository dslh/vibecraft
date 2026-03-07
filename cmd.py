#!/usr/bin/env python3
"""Send a command to the running SC2 bot for execution on the next game tick.

Usage:
    ./cmd.py 'self.minerals'
    ./cmd.py 'len(self.workers.idle)'
    ./cmd.py 'self.units(UnitTypeId.MARINE).first.attack(self.enemy_start_locations[0])'
    echo 'for w in self.workers.idle:
        w.gather(self.mineral_field.closest_to(w))' | ./cmd.py

The code runs inside the game loop with `self` bound to the BotAI instance.
Common SC2 imports (UnitTypeId, AbilityId, etc.) are pre-loaded.
If the last statement is an expression, its value is printed automatically.
"""

import json
import os
import sys
import time
import uuid

COMMANDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "commands")
DEFAULT_TIMEOUT = 30


def main():
    if len(sys.argv) > 1:
        code = " ".join(sys.argv[1:])
    elif not sys.stdin.isatty():
        code = sys.stdin.read()
    else:
        print("Usage: cmd.py 'code' or echo 'code' | cmd.py", file=sys.stderr)
        sys.exit(1)

    if not code.strip():
        sys.exit(0)

    os.makedirs(COMMANDS_DIR, exist_ok=True)

    cmd_id = f"{time.time():.6f}_{uuid.uuid4().hex[:8]}"
    cmd_file = os.path.join(COMMANDS_DIR, f"{cmd_id}.py")
    result_file = os.path.join(COMMANDS_DIR, f"{cmd_id}.result")

    with open(cmd_file, "w") as f:
        f.write(code)

    # Poll for result
    start = time.time()
    while time.time() - start < DEFAULT_TIMEOUT:
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

            if result.get("stdout"):
                print(result["stdout"], end="")
            if result.get("stderr"):
                print(result["stderr"], end="", file=sys.stderr)
            if not result["ok"]:
                if result.get("error"):
                    print(result["error"], file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
        time.sleep(0.05)

    print(
        f"Timed out after {DEFAULT_TIMEOUT}s waiting for result. Is the game running?",
        file=sys.stderr,
    )
    try:
        os.unlink(cmd_file)
    except FileNotFoundError:
        pass
    sys.exit(1)


if __name__ == "__main__":
    main()
