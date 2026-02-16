"""
SC2 Bot Harness — hot-reloads bot.py on every game tick.

Usage:
    python run.py [--map MAP_NAME] [--race RACE] [--difficulty DIFFICULTY]

While the game is running, edit bot.py and save. Your changes take effect
on the next tick. If bot.py has a syntax error or crashes, the harness
logs the error and skips that tick — the game keeps running.
"""

import argparse
import importlib
import inspect
import os
import sys
import traceback

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race, Result
from sc2.main import run_game
from sc2.player import Bot, Computer

# The bot module to hot-reload. Lives next to this file.
BOT_MODULE_NAME = "bot"
BOT_MODULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")

RACE_MAP = {r.name.lower(): r for r in Race}
DIFFICULTY_MAP = {d.name.lower(): d for d in Difficulty}


class HarnessBot(BotAI):

    def __init__(self):
        super().__init__()
        self.memory = {}
        self._bot_module = None
        self._bot_mtime = 0.0
        self._last_error = None

    async def on_step(self, iteration: int):
        # Hot-reload bot.py if it changed on disk (or on first load)
        try:
            mtime = os.path.getmtime(BOT_MODULE_PATH)
        except OSError:
            if self._last_error != "missing":
                print(f"[harness] bot.py not found at {BOT_MODULE_PATH}")
                self._last_error = "missing"
            return

        if mtime != self._bot_mtime:
            self._bot_mtime = mtime
            try:
                if BOT_MODULE_NAME in sys.modules:
                    self._bot_module = importlib.reload(sys.modules[BOT_MODULE_NAME])
                else:
                    self._bot_module = importlib.import_module(BOT_MODULE_NAME)
                self._last_error = None
                print(f"[harness] Reloaded bot.py (tick {iteration}, {self.time_formatted})")
            except Exception:
                self._last_error = "load"
                print(f"[harness] Failed to load bot.py:")
                traceback.print_exc()
                return

        if self._bot_module is None:
            return

        play_fn = getattr(self._bot_module, "play", None)
        if play_fn is None:
            if self._last_error != "no_play":
                print("[harness] No play() function found in bot.py")
                self._last_error = "no_play"
            return

        try:
            result = play_fn(self, self.memory)
            # Support async play() functions
            if inspect.isawaitable(result):
                await result
        except Exception:
            print(f"[harness] Bot error at tick {iteration} ({self.time_formatted}):")
            traceback.print_exc()

    async def on_end(self, game_result: Result):
        print(f"[harness] Game ended: {game_result}")


def main():
    parser = argparse.ArgumentParser(description="SC2 Bot Harness with hot-reload")
    parser.add_argument("--map", default="AcropolisLE", help="Map name (default: AcropolisLE)")
    parser.add_argument("--race", default="terran", choices=list(RACE_MAP.keys()), help="Bot race")
    parser.add_argument(
        "--difficulty",
        default="medium",
        choices=list(DIFFICULTY_MAP.keys()),
        help="Computer difficulty",
    )
    parser.add_argument("--enemy-race", default="random", choices=list(RACE_MAP.keys()), help="Enemy race")
    args = parser.parse_args()

    race = RACE_MAP[args.race]
    enemy_race = RACE_MAP[args.enemy_race]
    difficulty = DIFFICULTY_MAP[args.difficulty]

    print(f"[harness] Starting: {race.name} vs {difficulty.name} {enemy_race.name} on {args.map}")
    print(f"[harness] Edit {BOT_MODULE_PATH} while the game runs. Changes apply next tick.")
    print()

    run_game(
        maps.get(args.map),
        [Bot(race, HarnessBot()), Computer(enemy_race, difficulty)],
        realtime=True,
    )


if __name__ == "__main__":
    main()
