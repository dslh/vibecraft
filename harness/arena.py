"""
Arena mode: menu-driven game loop connected to a leaderboard server.

Players register (name + race), then loop through a menu choosing
to play vs CPU (with escalating default difficulty) or vs another
connected player (matchmade by the leaderboard server).
"""

import asyncio
import json
import os
import socket
import time

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.shortcuts import message_dialog
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Box, Button, Dialog, Label, RadioList, TextArea

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
    "label":              "#8b949e",
    "section-label":      "#58a6ff bold",
})

_PREFS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".arena_prefs.json")


def _load_prefs() -> dict:
    try:
        with open(_PREFS_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefs(prefs: dict):
    try:
        with open(_PREFS_PATH, "w") as f:
            json.dump(prefs, f)
    except OSError:
        pass


def _radio(title: str, values: list[tuple], default=None):
    """Show a full-screen radio list dialog. Returns the selected value or None on cancel."""
    from prompt_toolkit.shortcuts import radiolist_dialog
    result = radiolist_dialog(
        title=title,
        values=values,
        default=default,
        style=DIALOG_STYLE,
    ).run()
    return result


def _combined_dialog(title, sections, ok_text="OK", cancel_text="Cancel"):
    """Show a dialog with multiple labeled sections (widgets).

    sections: list of (label_str, widget) pairs.
    Returns True on OK, None on cancel.
    """
    result = [None]

    def on_ok():
        result[0] = True
        app.exit()

    def on_cancel():
        app.exit()

    ok_button = Button(text=ok_text, handler=on_ok)
    cancel_button = Button(text=cancel_text, handler=on_cancel)

    body_rows = []
    for label_text, widget in sections:
        body_rows.append(Window(
            FormattedTextControl([("class:section-label", label_text)]),
            height=1,
        ))
        body_rows.append(widget)
        body_rows.append(Window(height=1))  # spacer

    # Remove trailing spacer
    if body_rows:
        body_rows.pop()

    dialog = Dialog(
        title=title,
        body=HSplit(body_rows, padding=0),
        buttons=[ok_button, cancel_button],
        with_background=True,
    )

    app = Application(
        layout=Layout(dialog),
        style=DIALOG_STYLE,
        full_screen=True,
        mouse_support=True,
    )
    app.run()
    return result[0]


def tui_registration(args) -> tuple[str, Race]:
    """Show a single registration dialog with name + race."""
    prefs = _load_prefs()

    default_name = args.name or prefs.get("name") or os.getlogin()
    saved_race = RACE_MAP.get(prefs.get("race", "").lower())
    default_race = saved_race or RACE_MAP.get(args.race, Race.Terran)

    name_input = TextArea(
        text=default_name,
        multiline=False,
        height=1,
    )

    race_list = RadioList([
        (Race.Terran, "Terran"),
        (Race.Protoss, "Protoss"),
        (Race.Zerg, "Zerg"),
    ], default=default_race)

    result = _combined_dialog(
        "SC2 Bot Arena",
        [
            ("Name", name_input),
            ("Race", race_list),
        ],
        ok_text="Connect",
        cancel_text="Quit",
    )

    if result is None:
        raise SystemExit(0)

    name = name_input.text.strip() or default_name
    race = race_list.current_value

    _save_prefs({"name": name, "race": race.name})
    return name, race


def show_main_menu() -> str:
    """Show the main menu. Returns 'cpu', 'pvp', or 'quit'."""
    action_list = RadioList([
        ("cpu", "Play vs Computer"),
        ("pvp", "Play vs Player"),
        ("quit", "Quit"),
    ], default="cpu")

    result = _combined_dialog(
        "SC2 Bot Arena",
        [
            ("What would you like to do?", action_list),
        ],
        ok_text="Go",
        cancel_text="Quit",
    )

    if result is None:
        return "quit"
    return action_list.current_value


def show_cpu_menu(default_difficulty_idx: int, cancel_text: str = "Back") -> tuple[Race, Difficulty] | None:
    """Show enemy race + difficulty in a single dialog. Returns None on cancel."""
    race_list = RadioList([
        (Race.Random, "Random"),
        (Race.Terran, "Terran"),
        (Race.Protoss, "Protoss"),
        (Race.Zerg, "Zerg"),
    ], default=Race.Random)

    default_diff = DIFFICULTIES[default_difficulty_idx]
    diff_values = []
    for d in DIFFICULTIES:
        label = d.name
        if d == default_diff:
            label += "  (default)"
        diff_values.append((d, label))

    diff_list = RadioList(diff_values, default=default_diff)

    result = _combined_dialog(
        "Play vs Computer",
        [
            ("Enemy Race", race_list),
            ("Difficulty", diff_list),
        ],
        ok_text="Start",
        cancel_text=cancel_text,
    )

    if result is None:
        return None
    return race_list.current_value, diff_list.current_value


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

    # Default difficulty starts at VeryEasy, bumps up on CPU wins
    difficulty_idx = 0

    try:
        while True:
            lb.send_status(state="idle")

            if lb.pvp_enabled:
                choice = show_main_menu()
            else:
                choice = "cpu"

            if choice == "cpu":
                cancel_text = "Quit" if not lb.pvp_enabled else "Back"
                cpu_opts = show_cpu_menu(difficulty_idx, cancel_text=cancel_text)
                if cpu_opts is None:
                    if not lb.pvp_enabled:
                        break  # quit
                    continue  # back to main menu
                enemy_race, difficulty = cpu_opts
                difficulty_idx = DIFFICULTIES.index(difficulty)
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
