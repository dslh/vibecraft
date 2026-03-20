"""
Arena mode: menu-driven game loop connected to a leaderboard server.

Players register (name + race), then loop through a menu choosing
to play vs CPU (with escalating default difficulty) or vs another
connected player (matchmade by the leaderboard server).
"""

import asyncio
import os
import socket
import time

from prompt_toolkit import print_formatted_text, HTML
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import radiolist_dialog, input_dialog, message_dialog
from prompt_toolkit.styles import Style

from sc2 import maps
from sc2.data import Difficulty, Race, Result
from sc2.main import run_game
from sc2.player import Bot, Computer

from .bot import BOT_PACKAGE, HarnessBot
from .leaderboard_client import LeaderboardClient

RACE_MAP = {r.name.lower(): r for r in Race}

DIFFICULTIES = [
    Difficulty.VeryEasy, Difficulty.Easy, Difficulty.Medium,
    Difficulty.MediumHard, Difficulty.Hard, Difficulty.Harder, Difficulty.VeryHard,
]

# Shared dialog style — dark theme matching the dashboard
DIALOG_STYLE = Style.from_dict({
    "dialog":             "bg:#161b22 #c9d1d9",
    "dialog frame.label": "bg:#161b22 #58a6ff bold",
    "dialog.body":        "bg:#0d1117 #c9d1d9",
    "dialog shadow":      "bg:#010409",
    "button":             "bg:#30363d #c9d1d9",
    "button.focused":     "bg:#58a6ff #0d1117 bold",
    "radio-list":         "bg:#0d1117 #c9d1d9",
    "radio":              "#58a6ff",
    "radio-checked":      "#3fb950 bold",
    "text-area":          "bg:#0d1117 #c9d1d9",
})


def _radio(title: str, values: list[tuple], default=None):
    """Show a full-screen radio list dialog. Returns the selected value or None on cancel."""
    result = radiolist_dialog(
        title=title,
        values=values,
        default=default,
        style=DIALOG_STYLE,
    ).run()
    return result


def tui_registration(args) -> tuple[str, Race]:
    """Show the registration form and return (name, race)."""
    default_name = args.name or socket.gethostname().split(".")[0]

    name = input_dialog(
        title="SC2 Bot Arena",
        text="Enter your name:",
        default=default_name,
        style=DIALOG_STYLE,
    ).run()

    if name is None:
        raise SystemExit(0)
    name = name.strip() or default_name

    race = _radio("SC2 Bot Arena — Choose Race", [
        (Race.Terran, "Terran"),
        (Race.Protoss, "Protoss"),
        (Race.Zerg, "Zerg"),
    ], default=RACE_MAP.get(args.race, Race.Terran))

    if race is None:
        raise SystemExit(0)

    return name, race


def show_main_menu() -> str:
    """Show the main menu and return the choice."""
    choice = _radio("SC2 Bot Arena", [
        ("cpu", "Play vs Computer"),
        ("pvp", "Play vs Player"),
        ("quit", "Quit"),
    ], default="cpu")

    if choice is None:
        return "quit"
    return choice


def show_cpu_menu(default_difficulty_idx: int) -> tuple[Race, Difficulty]:
    """Show CPU game options and return (enemy_race, difficulty)."""
    enemy_race = _radio("Enemy Race", [
        (Race.Random, "Random"),
        (Race.Terran, "Terran"),
        (Race.Protoss, "Protoss"),
        (Race.Zerg, "Zerg"),
    ], default=Race.Random)

    if enemy_race is None:
        enemy_race = Race.Random

    default_diff = DIFFICULTIES[default_difficulty_idx]
    diff_values = []
    for d in DIFFICULTIES:
        label = d.name
        if d == default_diff:
            label += "  (default)"
        diff_values.append((d, label))

    difficulty = _radio("Difficulty", diff_values, default=default_diff)
    if difficulty is None:
        difficulty = default_diff

    return enemy_race, difficulty


def play_cpu_game(args, race: Race, enemy_race: Race, difficulty: Difficulty,
                  lb: LeaderboardClient) -> tuple[Result | None, float]:
    """Launch a vs-CPU game and return (result, game_time)."""
    harness_bot = HarnessBot()
    harness_bot._map_name = args.map
    harness_bot._opponent_info = f"{difficulty.name} {enemy_race.name}"
    harness_bot._harness_state.lb = lb

    opponent_desc = f"{difficulty.name} {enemy_race.name}"
    lb.send_status(state="playing_cpu", opponent=opponent_desc)

    print(f"\n  Starting: {race.name} vs {opponent_desc} on {args.map}")
    print(f"  Edit files in {BOT_PACKAGE}/ while the game runs.\n")

    players = [Bot(race, harness_bot), Computer(enemy_race, difficulty)]
    game_start = time.time()

    try:
        result = run_game(maps.get(args.map), players, realtime=True)
    except (KeyboardInterrupt, SystemExit):
        if not harness_bot._harness_state.game_ended:
            from .state_writer import write_game_ended_marker
            write_game_ended_marker("ABANDONED")
        raise
    game_time = time.time() - game_start

    return result, game_time


def play_pvp_game(args, race: Race, match: dict,
                  lb: LeaderboardClient) -> tuple[Result | None, float]:
    """Launch a PvP game based on match info from the server."""
    from .lan import host_pvp_game, join_pvp_game

    role = match["role"]
    opponent_name = match["opponent_name"]
    base_port = match["base_port"]
    opponent_ip = match.get("opponent_ip", "")
    same_machine = match.get("same_machine", False)

    lb.send_status(state="playing_pvp", opponent=opponent_name)

    print(f"\n  PvP: {role} vs {opponent_name} on {args.map}")
    print(f"  Edit files in {BOT_PACKAGE}/ while the game runs.\n")

    if role == "host":
        result, game_time = asyncio.run(
            host_pvp_game(args.map, race, base_port,
                          opponent_name=opponent_name, lb=lb,
                          same_machine=same_machine)
        )
    else:
        result, game_time = asyncio.run(
            join_pvp_game(opponent_ip, args.map, race, base_port,
                          opponent_name=opponent_name, lb=lb,
                          same_machine=same_machine)
        )

    return result, game_time


def run_arena(args):
    """Main entry point for arena mode."""
    name, race = tui_registration(args)

    lb = LeaderboardClient(args.leaderboard, name=name, race=race.name)
    lb.start()

    print(f"  Connecting to leaderboard at {args.leaderboard}...")
    if not lb.wait_for_connect(timeout=15):
        print("  Could not connect to leaderboard server.")
        return

    # Default difficulty starts at Medium, bumps up on CPU wins
    difficulty_idx = 2

    try:
        while True:
            lb.send_status(state="idle")
            choice = show_main_menu()

            if choice == "cpu":
                enemy_race, difficulty = show_cpu_menu(difficulty_idx)
                result, game_time = play_cpu_game(args, race, enemy_race, difficulty, lb)

                result_name = result.name if result else "Unknown"
                opponent_desc = f"{difficulty.name} {enemy_race.name}"
                lb.send_game_complete(
                    result=result_name, game_time=game_time,
                    opponent=opponent_desc, game_type="cpu",
                )

                if result == Result.Victory:
                    difficulty_idx = min(difficulty_idx + 1, len(DIFFICULTIES) - 1)
                    message_dialog(
                        title="Victory!",
                        text=f"Won vs {opponent_desc} in {game_time:.0f}s",
                        style=DIALOG_STYLE,
                    ).run()
                else:
                    message_dialog(
                        title=result_name,
                        text=f"vs {opponent_desc} in {game_time:.0f}s",
                        style=DIALOG_STYLE,
                    ).run()

            elif choice == "pvp":
                lb.queue_pvp()
                print("\n  Waiting for opponent... (Ctrl+C to cancel)")

                try:
                    match = lb.wait_for_match(timeout=3600)
                except KeyboardInterrupt:
                    lb.cancel_pvp()
                    print("  Cancelled.")
                    continue

                if not match:
                    print("  Match cancelled.")
                    continue

                result, game_time = play_pvp_game(args, race, match, lb)
                result_name = result.name if result else "Unknown"
                lb.send_game_complete(
                    result=result_name, game_time=game_time,
                    opponent=match["opponent_name"], game_type="pvp",
                )

                if result == Result.Victory:
                    message_dialog(
                        title="Victory!",
                        text=f"Won vs {match['opponent_name']} in {game_time:.0f}s",
                        style=DIALOG_STYLE,
                    ).run()
                else:
                    message_dialog(
                        title=result_name,
                        text=f"vs {match['opponent_name']} in {game_time:.0f}s",
                        style=DIALOG_STYLE,
                    ).run()

            elif choice == "quit":
                break

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        lb.send_status(state="disconnected")
        time.sleep(0.3)
        lb.close()
        print("\n  Disconnected.")
