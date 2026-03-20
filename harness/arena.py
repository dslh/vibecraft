"""
Arena mode: menu-driven game loop connected to a leaderboard server.

Players register (name + race), then loop through a menu choosing
to play vs CPU (with escalating default difficulty) or vs another
connected player (matchmade by the leaderboard server).
"""

import asyncio
import socket
import time

from rich.console import Console
from rich.text import Text

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

console = Console()


def _input(prompt: str) -> str:
    """Prompt for input, stripping whitespace."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0)


def tui_registration(args) -> tuple[str, Race]:
    """Show the registration form and return (name, race)."""
    console.print()
    console.print("[bold]== SC2 Bot Arena ==[/bold]")
    console.print()

    # Name
    default_name = args.name or socket.gethostname().split(".")[0]
    name = _input(f"  Name [{default_name}]: ") or default_name

    # Race
    console.print()
    console.print("  Race:")
    console.print("    [blue][1][/blue] Terran   [yellow][2][/yellow] Protoss   [purple][3][/purple] Zerg")
    race_choice = _input("  > ")

    race_names = {"1": "terran", "2": "protoss", "3": "zerg"}
    # Also accept the race name directly
    race_key = race_names.get(race_choice, race_choice.lower())
    if race_key not in RACE_MAP or RACE_MAP[race_key] == Race.Random:
        console.print(f"  [dim]Defaulting to {args.race}[/dim]")
        race_key = args.race
    race = RACE_MAP[race_key]

    console.print()
    console.print(f"  [bold]{name}[/bold] — [bold]{race.name}[/bold]")
    console.print()

    return name, race


def show_main_menu() -> str:
    """Show the main menu and return the choice."""
    console.print()
    console.print("[bold]== Main Menu ==[/bold]")
    console.print("  [cyan][1][/cyan] Play vs Computer")
    console.print("  [green][2][/green] Play vs Player")
    console.print("  [dim][3][/dim] Quit")
    choice = _input("  > ")

    if choice in ("1", "cpu"):
        return "cpu"
    elif choice in ("2", "pvp"):
        return "pvp"
    elif choice in ("3", "q", "quit"):
        return "quit"
    else:
        return "cpu"  # default


def show_cpu_menu(default_difficulty_idx: int) -> tuple[Race, Difficulty]:
    """Show CPU game options and return (enemy_race, difficulty)."""
    console.print()
    console.print("  Enemy race:")
    console.print("    [blue][1][/blue] Terran   [yellow][2][/yellow] Protoss   [purple][3][/purple] Zerg   [dim][4][/dim] Random")
    race_choice = _input("  > ") or "4"

    enemy_race_map = {"1": Race.Terran, "2": Race.Protoss, "3": Race.Zerg, "4": Race.Random}
    enemy_race = enemy_race_map.get(race_choice, Race.Random)

    console.print()
    default_diff = DIFFICULTIES[default_difficulty_idx]
    console.print(f"  Difficulty [bold][{default_diff.name}][/bold]:")
    for i, d in enumerate(DIFFICULTIES):
        marker = " *" if i == default_difficulty_idx else ""
        console.print(f"    [dim][{i + 1}][/dim] {d.name}{marker}")
    diff_choice = _input("  > ")

    if diff_choice and diff_choice.isdigit():
        idx = int(diff_choice) - 1
        if 0 <= idx < len(DIFFICULTIES):
            difficulty = DIFFICULTIES[idx]
        else:
            difficulty = default_diff
    else:
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

    console.print()
    console.print(f"  [bold]Starting:[/bold] {race.name} vs {opponent_desc} on {args.map}")
    console.print(f"  [dim]Edit files in {BOT_PACKAGE}/ while the game runs.[/dim]")
    console.print()

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

    lb.send_status(state="playing_pvp", opponent=opponent_name)

    console.print()
    console.print(f"  [bold]PvP:[/bold] {role} vs {opponent_name} on {args.map}")
    console.print(f"  [dim]Edit files in {BOT_PACKAGE}/ while the game runs.[/dim]")
    console.print()

    if role == "host":
        result, game_time = asyncio.run(
            host_pvp_game(args.map, race, base_port,
                          opponent_name=opponent_name, lb=lb)
        )
    else:
        result, game_time = asyncio.run(
            join_pvp_game(opponent_ip, args.map, race, base_port,
                          opponent_name=opponent_name, lb=lb)
        )

    return result, game_time


def run_arena(args):
    """Main entry point for arena mode."""
    name, race = tui_registration(args)

    lb = LeaderboardClient(args.leaderboard, name=name, race=race.name)
    lb.start()

    console.print(f"  [dim]Connecting to leaderboard at {args.leaderboard}...[/dim]")
    if not lb.wait_for_connect(timeout=15):
        console.print("  [red]Could not connect to leaderboard server.[/red]")
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
                    console.print("  [green bold]Victory![/green bold]")
                    difficulty_idx = min(difficulty_idx + 1, len(DIFFICULTIES) - 1)
                else:
                    console.print(f"  [red]{result_name}[/red]")

            elif choice == "pvp":
                lb.queue_pvp()
                console.print()
                console.print("  [yellow]Waiting for opponent...[/yellow] (Ctrl+C to cancel)")

                try:
                    match = lb.wait_for_match(timeout=3600)
                except KeyboardInterrupt:
                    lb.cancel_pvp()
                    console.print("  [dim]Cancelled.[/dim]")
                    continue

                if not match:
                    console.print("  [red]Match cancelled.[/red]")
                    continue

                result, game_time = play_pvp_game(args, race, match, lb)
                result_name = result.name if result else "Unknown"
                lb.send_game_complete(
                    result=result_name, game_time=game_time,
                    opponent=match["opponent_name"], game_type="pvp",
                )

                if result == Result.Victory:
                    console.print("  [green bold]Victory![/green bold]")
                else:
                    console.print(f"  [red]{result_name}[/red]")

            elif choice == "quit":
                break

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        lb.send_status(state="disconnected")
        time.sleep(0.3)
        lb.close()
        console.print()
        console.print("  [dim]Disconnected.[/dim]")
